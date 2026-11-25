"""岗位库管理员助手：一个带联网搜索工具的独立智能体。

与 analyze_jd 的分工：
    analyze_jd   一次性结构化打分（固定 JSON schema），写进 jobs 表
    assistant    多轮对话 + 工具调用，输出自然语言

上下文顺序（固定，利于 DeepSeek 上下文缓存）：
    system（角色 + 简历 + 岗位库摘要） → 最近历史 → 本轮用户消息
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssistantMessage, Job, User
from app.services.llm import call_llm_tools
from app.services.search import SearchError, SearchNotConfigured, web_search

logger = logging.getLogger(__name__)

# 连续调用工具的上限：防止模型陷入"搜了又问、问了又搜"的死循环
MAX_TOOL_ROUNDS = 3

# 带多少条历史（约 6 轮对话）。太多会白烧 token，太少会忘上下文。
HISTORY_LIMIT = 12

# 助手唯一的工具
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网搜索。用于查询一家公司的主营业务、业务板块、财报数据、"
                "融资情况、近期新闻。不要用它查招聘岗位信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，尽量具体，例如「字节跳动 2024 营收 业务构成」",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

ASSISTANT_SYSTEM = """你是这个投递记录系统的岗位库管理员，兼用户的求职助手。

你的职责：
1. 帮用户看懂自己的岗位库：哪些值得优先准备、哪些可以放一放
2. 回答公司相关的问题（主营业务、业务板块、财报、规模、近期动态）
3. 帮用户准备面试：预测会问什么、怎么表达已有经历

硬性规则（必须遵守）：
- 涉及公司的事实（营收、业务构成、融资、裁员、财报）**必须先调用 web_search**，再回答
- 回答时给出你依据的来源（域名或标题），让用户能自己核对
- 搜不到就明确说"我没搜到"，**绝不用记忆里的印象冒充搜索结果**
- 你没有用户的面试经历，也没有企业内部信息；拿不准就说拿不准
- 薪资、员工评价、离职原因这类信息，只转述你能查到的公开说法，
  并注明"这是网络上的说法，未经核实"
- 中文回答，简洁，直接给结论，不要客套和铺垫

【用户简历】
{profile}

【岗位库现状】
{digest}
"""


def build_digest(jobs: list[Job]) -> str:
    """把岗位库压缩成一段文字给模型看。

    不传全部字段——只给它做判断需要的：公司、岗位、分数、状态。
    JD 全文太长，需要时让它自己说要看哪一条（暂未提供该工具）。
    """
    if not jobs:
        return "岗位库是空的。"

    analyzed = [j for j in jobs if j.match_score is not None]
    lines = [f"共 {len(jobs)} 个岗位，其中 {len(analyzed)} 个已打分。"]

    if analyzed:
        ranked = sorted(analyzed, key=lambda j: j.match_score or 0, reverse=True)[:8]
        lines.append("匹配度最高的几个：")
        for job in ranked:
            lines.append(
                f"- {job.company} / {job.position}：{job.match_score} 分"
                f"（{job.verdict or '未定档'}，当前状态 {job.status}）"
            )

    pending = [j for j in jobs if j.match_score is None]
    if pending:
        names = "、".join(f"{j.company}/{j.position}" for j in pending[:5])
        lines.append(f"还有 {len(pending)} 个未打分：{names}"
                     + ("……" if len(pending) > 5 else ""))

    return "\n".join(lines)


async def _load_history(db: AsyncSession, user_id: int) -> list[AssistantMessage]:
    rows = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.user_id == user_id)
        .order_by(AssistantMessage.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return list(reversed(rows.scalars().all()))


async def _save(db: AsyncSession, user_id: int, role: str, content: str,
                tool_name: str | None = None) -> AssistantMessage:
    message = AssistantMessage(
        user_id=user_id, role=role, content=content, tool_name=tool_name
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def chat(db: AsyncSession, user: User, text: str, jobs: list[Job]) -> AssistantMessage:
    """跑一轮助手对话，返回最终的 assistant 消息。

    流程：
        存用户消息 → 组装上下文 → 循环（调模型 → 若有工具调用则执行并回填）→ 存回答
    """
    await _save(db, user.id, "user", text)

    profile = (user.profile_text or "").strip() or "（用户还没有上传简历）"
    system = ASSISTANT_SYSTEM.format(profile=profile[:6000], digest=build_digest(jobs))

    messages: list[dict] = [{"role": "system", "content": system}]
    for item in await _load_history(db, user.id):
        # tool 消息在下一轮由下面按需回填，历史里只恢复 user / assistant
        if item.role in ("user", "assistant"):
            messages.append({"role": item.role, "content": item.content})

    for _round in range(MAX_TOOL_ROUNDS):
        response = await call_llm_tools(messages, TOOLS)
        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            answer = (message.content or "").strip() or "（模型没有返回内容）"
            return await _save(db, user.id, "assistant", answer)

        # 有工具调用：先把模型的"我要调用什么"记进上下文，再执行
        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in message.tool_calls
            ],
        })

        for call in message.tool_calls:
            result = await _run_tool(db, user.id, call.function.name, call.function.arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

    # 连续调满工具轮次还没收口：强制让它给结论
    messages.append({
        "role": "user",
        "content": "请基于上面的搜索结果直接给结论，不要再搜索了。",
    })
    response = await call_llm_tools(messages)
    answer = (response.choices[0].message.content or "").strip() or "（模型没有返回内容）"
    return await _save(db, user.id, "assistant", answer)


async def _run_tool(db: AsyncSession, user_id: int, name: str, arguments: str) -> str:
    """执行一次工具调用，结果同时存库（用户能看到助手查了什么）。"""
    if name != "web_search":
        result = f"未知工具：{name}"
        await _save(db, user_id, "tool", result, tool_name=name)
        return result

    import json

    try:
        query = (json.loads(arguments or "{}").get("query") or "").strip()
    except Exception:
        query = ""

    if not query:
        result = "工具调用缺少 query 参数。"
        await _save(db, user_id, "tool", result, tool_name=name)
        return result

    try:
        result = await web_search(query)
    except SearchNotConfigured as e:
        # 明确告诉模型"没配搜索"，它才能如实告诉用户，而不是编造
        result = f"搜索不可用：{e}"
    except SearchError as e:
        result = f"搜索失败：{e}"
    except Exception as e:  # 兜底，别让工具异常把整个对话打断
        logger.exception("web_search 异常")
        result = f"搜索异常：{e}"

    await _save(db, user_id, "tool", f"搜索：{query}\n{result}", tool_name=name)
    return result
