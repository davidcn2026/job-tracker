"""联网搜索：助手唯一的工具。

设计要点：
  1. **可插拔**：不同服务商的接口形状不同，统一在 web_search() 后面。
     当前实现博查（Bocha，国内直连、按量计费）和 Tavily。
  2. **没有 key 时明确报错，不静默降级**：助手会如实告诉用户"搜索未配置"，
     而不是编一段话冒充搜索结果 —— 那是最危险的行为。
  3. 返回**带来源 URL 的摘要**，让用户能核对，也让模型有据可依。
  4. 用标准库 urllib 而不是 httpx：本项目依赖的 openai SDK 带的是 httpx2，
     直接 import httpx 会 ModuleNotFoundError。搜索是一次性短请求，
     用 urllib + to_thread 足够，还少一个依赖。
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from app.core.config import settings

TIMEOUT_SECONDS = 30


class SearchError(Exception):
    """搜索失败（网络 / 服务商报错）。"""


class SearchNotConfigured(SearchError):
    """没有配置搜索服务。助手应据此明确告知用户，而不是编造内容。"""


async def web_search(query: str, *, count: int = 5) -> str:
    """执行一次搜索，返回给模型看的纯文本摘要（含来源链接）。"""
    provider = (settings.search_provider or "").strip().lower()
    api_key = (settings.search_api_key or "").strip()

    if not provider:
        raise SearchNotConfigured(
            "搜索服务未配置。请在 .env 里设置 SEARCH_PROVIDER=bocha（或 tavily）"
            "和 SEARCH_API_KEY。"
        )
    if not api_key:
        raise SearchNotConfigured("SEARCH_API_KEY 未设置，无法联网搜索。")

    if provider == "bocha":
        return await _bocha(query, api_key, count)
    if provider == "tavily":
        return await _tavily(query, api_key, count)

    raise SearchNotConfigured(f"不认识的搜索服务：{provider}（支持 bocha / tavily）")


def _post_json(url: str, payload: dict, api_key: str) -> dict:
    """同步 POST，返回解析后的 JSON。调用方用 to_thread 包成异步。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise SearchError(f"搜索服务返回 {e.code}：{body}") from e
    except urllib.error.URLError as e:
        raise SearchError(f"搜索请求失败：{e.reason}") from e
    except Exception as e:
        raise SearchError(f"搜索失败：{e}") from e


async def _bocha(query: str, api_key: str, count: int) -> str:
    data = await asyncio.to_thread(
        _post_json,
        "https://api.bochaai.com/v1/web-search",
        {"query": query, "summary": True, "count": count},
        api_key,
    )

    pages = (((data.get("data") or {}).get("webPages") or {}).get("value")) or []
    if not pages:
        return f"搜索「{query}」没有找到结果。"

    lines = [f"搜索「{query}」的前 {len(pages)} 条结果："]
    for index, page in enumerate(pages, start=1):
        title = page.get("name") or ""
        url = page.get("url") or ""
        snippet = page.get("summary") or page.get("snippet") or ""
        lines.append(f"\n[{index}] {title}\n来源：{url}\n摘要：{snippet}")
    return "\n".join(lines)


async def _tavily(query: str, api_key: str, count: int) -> str:
    data = await asyncio.to_thread(
        _post_json,
        "https://api.tavily.com/search",
        {"api_key": api_key, "query": query, "max_results": count, "include_answer": False},
        api_key,
    )

    results = data.get("results") or []
    if not results:
        return f"搜索「{query}」没有找到结果。"

    lines = [f"搜索「{query}」的前 {len(results)} 条结果："]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"\n[{index}] {item.get('title', '')}\n"
            f"来源：{item.get('url', '')}\n"
            f"摘要：{(item.get('content') or '')[:500]}"
        )
    return "\n".join(lines)
