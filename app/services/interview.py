"""面试练习的核心逻辑：题目指纹、关键点拆解、回答评估 + 三层追问。

三个设计约束（都是和用户讨论后定的）：
  1. **不打分**，只判断关键点覆盖情况（covered / wrong / missing）。
     分数是虚假的精确，而且同一答案两次评分会飘。
  2. **追问固定三层**（事实 → 决策 → 边界），不让模型自由发挥。
     好处：可预测、降方差、提示词稳定、天然收口。
  3. **评估和生成追问合并成一次调用**，两者输入完全相同，
     分开只是多花一次输入 token。
"""

from __future__ import annotations

from pydantic import ValidationError

from app.schemas.llm import AnswerEval, InterviewQuestion, KeyPointsResult
from app.services.llm import LLMError, call_llm

# 追问层数的硬上限。真实技术面对一个点的追问通常就是三层：
#   1 事实：你做了什么
#   2 决策：为什么这么做
#   3 边界：什么时候会坏
# 第 4 层超出校招范围。代码强制收口，不靠模型自觉。
MAX_DEPTH = 3

LAYER_NAMES = {1: "事实层", 2: "决策层", 3: "边界层"}

LAYER_GUIDE = {
    1: (
        "让候选人说得更具体：哪个组件、什么参数、多少量级。"
        "例：你说的缓存，具体缓存了哪些字段？key 怎么设计？"
    ),
    2: (
        "问为什么这么选，要求与替代方案对比。"
        "例：为什么先更新库再删缓存？反过来会怎样？"
    ),
    3: (
        "问什么情况下会坏：失败、超时、并发、数据量涨 10 倍。"
        "例：删缓存失败了呢？脏数据窗口多大？"
    ),
}


def question_hash(text: str) -> str:
    """题目文本指纹（FNV-1a 32 位）。

    用途：把答案绑定到"题目内容"而不是"题号"——重新生成面试题后
    顺序会变，但题目文本不变则指纹不变，答案就能找回来。

    **前端有一份完全相同的实现**（app.js 里的 questionHash），
    两边必须一致，否则查不到答案。用 FNV-1a 而不是 sha256，
    是因为 JS 里同步算 sha256 要用 SubtleCrypto（异步），很别扭。
    """
    value = 0x811C9DC5
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return f"{value:08x}"


KEY_POINTS_SYSTEM = """你是面试教练。
给定若干道面试题及其参考答案，为每道题拆出「候选人必须说到的要点」。

输出 json：{"points": [[要点, 要点, ...], ...]}
长度和顺序必须与输入的题目完全一致。

每道题 3~5 条。要求：
1. 每条必须是可判断的具体知识点，不能是「要讲清楚原理」这种空话
2. 覆盖面试官真正在意的：核心概念、关键取舍、失败场景
3. 参考答案里没写、但这题必须提到的，可以按行业通用认知补充
4. 每条 15~40 字，中文，不要编号
"""


async def extract_key_points(questions: list[InterviewQuestion]) -> list[list[str]]:
    """给一批题目批量拆关键点（一次调用，比逐题便宜得多）。"""
    if not questions:
        return []

    lines = []
    for index, question in enumerate(questions, start=1):
        lines.append(
            f"{index}. 题目：{question.question}\n"
            f"   参考答案：{question.reference_answer}"
        )
    user_content = "\n\n".join(lines)

    raw = await call_llm(KEY_POINTS_SYSTEM, user_content, timeout=120, max_tokens=4000)

    try:
        result = KeyPointsResult.model_validate_json(raw)
    except ValidationError as e:
        raise LLMError(f"拆解关键点失败，模型输出不符合格式: {e}") from e

    # 数量对不上就补齐/截断，不要让整批失败
    points = list(result.points)
    if len(points) < len(questions):
        points += [[] for _ in range(len(questions) - len(points))]
    return points[: len(questions)]


EVAL_SYSTEM = """你是面试官，正在评估候选人对一道技术面试题的回答。

我每次会给你：题目、必须说到的要点清单、当前是第几层追问，
以及到目前为止的问答记录和候选人的最新回答。

你的任务有两件：

【一】判断候选人最新回答对每一条要点的覆盖情况：
- covered  提到了且正确
- wrong    提到了但理解错了（顺序说反、因果搞反、概念混淆）
           这类最危险，必须挑出来
- missing  完全没提到
同一条要点只能出现在一个分类里。不要为了凑数硬塞，也不要漏判。

【二】如果要继续追问，给出下一个问题。
追问必须按固定三层结构，当前层数我会告诉你：
  1 事实层：让候选人更具体（哪个组件、什么参数、多少量级）
  2 决策层：问为什么这么选，要求与替代方案对比
  3 边界层：问什么情况下会坏（失败、超时、并发、数据量涨 10 倍）
第 3 层回答完之后不再追问，next_question 填 null。

硬性规则：
1. 追问必须引用候选人答案里的具体表述，例如「你说先更新库再删缓存，那……」
   不要问通用问题，那等于让候选人背题库
2. 不要打分、不要给等级。只判断覆盖 + 给追问
3. verdict 一句话点出最关键的问题，不要空泛表扬
4. 禁止说「某公司往年考过」这类没有依据的话

输出 json，字段如下（要点编号从 0 开始）：
- covered: [要点编号, ...]        提到了且正确
- wrong: [{"index": 编号, "why": "错在哪"}, ...]
- missing: [要点编号, ...]        完全没提到
- verdict: "一句话总评"
- next_question: "下一层追问" 或 null
- next_layer: "1" / "2" / "3" 或 null
"""


async def evaluate_answer(
    question: InterviewQuestion,
    transcript: list[dict],
    answer: str,
    depth: int,
) -> AnswerEval:
    """评估一次回答，并按当前层数决定是否给出下一层追问。

    depth 是"已经追问过的层数"：
      0 → 初次回答，评估后追问第 1 层（事实层）
      1 → 追问第 2 层
      2 → 追问第 3 层
      3 → 到上限，收口（next_question = None）
    """
    points_text = "\n".join(
        f"{index}. {point}" for index, point in enumerate(question.key_points)
    )

    history_text = ""
    if transcript:
        chunks = []
        for item in transcript:
            layer_name = LAYER_NAMES.get(item.get("layer"), "追问")
            chunks.append(
                f"追问（{layer_name}）：{item.get('question', '')}\n"
                f"候选人回答：{item.get('answer', '')}"
            )
        history_text = "\n\n".join(chunks)

    next_depth = depth + 1
    if next_depth > MAX_DEPTH:
        layer_instruction = (
            "这已经是第 3 层追问的回答，不再追问：next_question 和 "
            "next_layer 都填 null。verdict 里给这道题的收口总结："
            "覆盖了几条要点、哪条说错、哪条始终没提到。"
        )
        layer_value = "null"
    else:
        layer_instruction = (
            f"接下来是第 {next_depth} 层追问（{LAYER_NAMES[next_depth]}）。"
            f"这一层要问什么：{LAYER_GUIDE[next_depth]}"
        )
        layer_value = str(next_depth)

    user_content = (
        f"【题目】{question.question}\n\n"
        f"【必须说到的要点】\n{points_text or '（未提供要点，按参考答案自行判断）'}\n\n"
        f"【参考答案】{question.reference_answer}\n\n"
        f"【已追问层数】{depth} / {MAX_DEPTH}\n"
        f"【下一层指令】{layer_instruction}\n"
        f"【next_layer 应填】{layer_value}\n\n"
        f"【之前的多轮问答】\n{history_text or '（这是第一次回答，没有追问历史）'}\n\n"
        f"【候选人最新回答】\n{answer}"
    )

    raw = await call_llm(EVAL_SYSTEM, user_content, timeout=90, max_tokens=2000)

    try:
        result = AnswerEval.model_validate_json(raw)
    except ValidationError as e:
        raise LLMError(f"评估失败，模型输出不符合格式: {e}") from e

    # 到上限时兜底清空追问：不能只靠模型听话
    if depth >= MAX_DEPTH:
        result.next_question = None
        result.next_layer = None

    return result


def derive_status(covered: int, total: int, depth: int) -> str:
    """由覆盖率和追问深度推导掌握状态。

    不做主观打分：掌握度就是这个可数的比值。
    """
    if total == 0:
        return "tried"
    ratio = covered / total
    if ratio >= 0.8:
        return "mastered"
    if ratio >= 0.4 or depth >= 2:
        # 深挖到第 2~3 层才卡住：基础有，只是不够深
        return "partial"
    return "tried"
