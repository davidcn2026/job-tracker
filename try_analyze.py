"""手动测试 AI 岗位匹配分析。

用法:
    python try_analyze.py data/test_jds/jd1_agent_intern.txt
    python try_analyze.py                 # 无参数：从标准输入粘贴 JD，Ctrl+Z 回车结束

输出: 分数 / 一句话结论 / 命中项 / 缺失项，以及耗时。
"""

import asyncio
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from app.schemas.llm import AnalysisResult
from app.services.llm import PROFILE_SUMMARY, SYSTEM_PROMPT, LLMError, call_llm


def read_jd() -> str:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).read_text(encoding="utf-8")

    print("粘贴 JD 内容，结束后按 Ctrl+Z 再回车：", file=sys.stderr)
    return sys.stdin.read()


async def analyze(jd: str) -> AnalysisResult:
    user = f"【JD原文】\n{jd}\n\n【我的技能】\n{PROFILE_SUMMARY}"
    raw = await call_llm(SYSTEM_PROMPT, user)
    try:
        return AnalysisResult.model_validate_json(raw)
    except ValidationError as e:
        raise LLMError(f"模型输出不符合格式: {e}") from e


async def main() -> None:
    jd = read_jd().strip()
    if not jd:
        print("JD 为空", file=sys.stderr)
        return

    start = time.perf_counter()
    try:
        result = await analyze(jd)
    except LLMError as e:
        print(f"分析失败: {e}")
        return
    elapsed = time.perf_counter() - start

    print(f"\n用时: {elapsed:.1f} 秒")
    print(f"分数: {result.match_score}")
    print(f"结论: {result.summary}")

    print("\n命中:")
    for item in result.matched:
        print(f"  + {item}")

    print("\n缺失:")
    for item in result.gaps:
        print(f"  - {item}")


if __name__ == "__main__":
    asyncio.run(main())
