import asyncio
import base64

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.llm import AnalysisResult, InterviewPrep, JobDraft, ResumeOCR
from app.services.image import prepare_images

SYSTEM_PROMPT = """你是岗位匹配分析助手。根据【我的技能】判断【JD原文】是否值得投递。

规则：
1. 只依据输入信息判断，禁止编造。信息不足时在 summary 里说明，不要猜。
2. 只输出 json，不要任何解释文字。
3. blocking_gaps 的每一条都必须引用 JD 原句作为依据，格式为「JD原句」→「候选人缺失点」。
   找不到 JD 原句支撑的判定，不许写进 blocking_gaps。
 
输出字段：
- verdict: 只能是 "推荐投递" / "可考虑投递" / "可以投递" / "不建议投递" 之一
- match_score: 0-100 的整数，必须与 verdict 对应下面的区间
- blocking_gaps: 数组。每条格式为「JD原句」→「候选人缺失点」。
  例："熟练掌握 Java" → 候选人主档案中主语言为 Python，未提及 Java
- gaps: 数组。次要要求、优先项、加分项的缺失。禁止写"JD未说明""无法判断"这类信息缺失项
- matched: 数组。候选人已满足的要求，最多 5 条
- summary: 一句话说明匹配情况与主要缺口，不超过 100 字。
  禁止出现任何档位表述（如"推荐投递""可考虑投递""可以投递""不建议投递""建议投""值得投""不建议"），
  档位由 verdict 字段承载，summary 只讲理由

blocking_gaps 的判定（从严）：
- 仅当 JD 用「必须」「熟练掌握」「要求」这类硬性表述，且候选人档案里完全没有对应能力时，才算 blocking
- 「优先」「加分」「有 X 经验者优先」「了解」一律不算 blocking，放 gaps
- 例：JD 要求「熟练掌握 Java」，候选人主语言是 Python 且未提 Java → 算 blocking
- 例：JD 要求「熟悉 Linux」，候选人档案提到 Linux 常用命令 → 不算 blocking

verdict 与 match_score 的对应（严格遵守，不要跨区间）：
- 不建议投递：0-49 分，且 blocking_gaps 必须非空
- 可以投递：50-64 分。方向相关但匹配度低，批量投即可
- 可考虑投递：65-74 分。接近临界，或 JD 有 1-2 项要求表述含糊无法判定
- 推荐投递：75-100 分。硬性要求满足，方向一致，值得定制简历重点投

summary 的写法（必须遵守）：
- summary 只描述「匹配情况 + 主要缺口」，不写任何档位词。
- 正确：「方向高度契合 Agent/LLM，但 JD 硬性要求熟练掌握 Java，候选人主语言为 Python」
- 错误：「…属可考虑投递」（出现档位词）
- 错误：「…建议定制简历后投递」（出现建议投递的意思）
- 档位只由 verdict 字段表达，summary 不重复它。这样无论档位被如何调整，summary 都不会自相矛盾。
"""
 
# ===== 创建客户端（指向 DeepSeek，模块导入时执行一次） =====
_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
)


class LLMError(Exception):
    """LLM 调用失败。service 层不抛 HTTPException，由 router 翻译。"""


# ===== 截图解析提示词 =====
# 要点：
#   1. 只让它抽"截图上真实存在的文字"，避免编造公司/薪资
#   2. 不要求它猜 published_at / url —— 截图里通常没有，猜了就是脏数据
#   3. 要求 confidence，让前端能提示"这次可能不准"
EXTRACT_PROMPT = """你是招聘截图解析助手。从用户给的招聘页面截图里抽取岗位信息，只输出 json。

输出字段：
- company: 公司名；截图里没有就 null
- position: 岗位名称；没有就 null
- salary_min / salary_max: 月薪下限/上限，单位「千元/月」，整数。
  例：「15-25K」→ 15 和 25；「8-12k·13薪」→ 8 和 12。没有就 null
- salary_note: 薪资附加说明（如「13薪」「含绩效」「试用期八折」）；没有就 null
- source: 招聘渠道，只能从 ["本校","Boss直聘","自定义","其他"] 里选一个。
  截图上能看出平台名就选对应的；看不出来选 "其他"
- source_detail: 平台名 / 内推人等补充信息；没有就 null
- company_business: 公司业务或行业（如「企业级 SaaS」「互联网」「游戏研发」）；没有就 null
- description: 岗位职责 + 任职要求的完整原文，尽量逐字保留，用换行分隔；没有就 null
- confidence: 0-1 的数字，你对这次整体抽取准确度的信心

规则：
1. 只抽取截图上真实存在的文字，禁止编造、推断、补充
2. 看不清、被截断、图上没有的字段一律填 null，不要猜
3. 图里若有多条岗位，只取最主要的那一条
4. 「2027 届」「应届」「本科」这类届别与学历要求属于重要信息，放进 description 里，不要丢弃
"""


PROFILE_SUMMARY_REMOVED = None  # 占位：旧版把简历硬编码在这里，已改为 users.profile_text


# ===== 简历图片转录提示词 =====
# 只做逐字转录，不做总结：简历原文才是匹配分析要用的原料，
# 让模型顺便"提炼"会丢失细节（比如具体的项目技术栈）。
RESUME_OCR_PROMPT = """你是简历文字转录助手。把这张简历图片里的内容逐字转录成纯文本，只输出 json。

输出字段：
- text: 转录出的完整文本，保留原有分节（如「教育背景」「专业技能」「项目经历」），用换行分隔
- confidence: 0-1 的数字，你对转录准确度的信心

要求：
1. 逐字转录，不要总结、不要改写、不要补充图上没有的内容
2. 必须保留：学历与届别、技能关键词、项目/实习经历的名称与技术栈、时间范围
3. 联系方式（手机、邮箱）可以省略
4. 看不清的字写 [看不清]，不要猜测
"""



async def call_llm(
    system: str,
    user: str,
    *,
    timeout: float = 30,
    max_tokens: int | None = None,
) -> str:
    """底层调用，返回模型原始文本。

    失败（超时 / 非 200 / 网络）一律抛 LLMError。

    timeout / max_tokens 可覆盖：分析一份 JD 很快（默认 30 秒够），
    但生成 15 道带参考答案的面试题输出很长，需要更宽的时限和上限。
    """
    kwargs: dict = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "timeout": timeout,
        "response_format": {"type": "json_object"},
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    try:
        response = await _client.chat.completions.create(**kwargs)
    except Exception as e:
        raise LLMError(f"模型调用失败: {e}") from e

    content = response.choices[0].message.content
    if not content:
        raise LLMError("模型返回了空内容")
    return content


async def analyze_jd(jd: str, profile: str) -> AnalysisResult:
    """业务层：拼提示词 → 调模型 → 解析 JSON → 校验 → 返回结构。

    profile 是**用户自己上传的简历文本**，不再是硬编码在代码里的摘要——
    否则会拿别人的经历去评判你的岗位匹配度，结论毫无意义。

    失败一律抛 LLMError（含模型输出格式不对），由 router 翻译成 503。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，无法进行 AI 分析")

    if not jd.strip():
        raise LLMError("JD 内容为空")

    if not profile.strip():
        raise LLMError("简历内容为空")

    # 固定内容放在前面：SYSTEM_PROMPT + 简历每次都相同（同一用户），
    # 前缀稳定才能命中上下文缓存（命中后输入价格远低于未命中）。
    # JD 截断到 1500 字：岗位要求基本都在前半部分，可省 30%~50% 输入 token。
    # 简历截断到 6000 字：一份简历通常 2~4 KB，6000 字足够，也防有人贴一整本书。
    user_content = f"【我的技能】\n{profile[:6000]}\n\n【JD原文】\n{jd[:1500]}"

    raw = await call_llm(SYSTEM_PROMPT, user_content)

    try:
        return AnalysisResult.model_validate_json(raw)
    except ValidationError as e:
        # 模型输出不是合法 JSON，或字段/枚举/范围不合规
        raise LLMError(f"模型输出不符合格式: {e}") from e


async def call_llm_vision(system: str, text: str, image_data_url: str) -> str:
    """带图片的多模态调用，返回模型原始文本。

    与 call_llm 的差别只在 user content 的形状（图片用 image_url 传 base64 data URL）。
    超时给 60 秒：截图解析比纯文本慢，长截图尤其。
    """
    try:
        response = await _client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
            temperature=0.0,
            timeout=60,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        raise LLMError(f"模型调用失败: {e}") from e

    content = response.choices[0].message.content
    if not content:
        raise LLMError("模型返回了空内容")
    return content


async def extract_job_from_image(image_bytes: bytes, mime: str) -> JobDraft:
    """业务层：招聘截图 → 岗位草稿。

    只返回草稿，**不写库**。写库必须由用户在前端确认后再走 POST /jobs，
    因为模型会看错（比如把「15-25K」读成 25-15，或把公司名读成岗位名）。

    超长截图（高度 > 8192px）会被切片，每片单独识别后合并——见 services/image.py。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，无法识别截图")

    if not image_bytes:
        raise LLMError("图片内容为空")

    try:
        parts = prepare_images(image_bytes, mime)
    except Exception as e:
        raise LLMError(f"图片无法解析：{e}") from e

    total = len(parts)
    tasks = []
    for index, (content, part_mime) in enumerate(parts, start=1):
        if total == 1:
            instruction = "解析这张招聘截图。"
        else:
            # 关键：重新定义切片场景下 confidence 的含义。
            # 否则第 2 段只看到"任职要求"、没有公司名和薪资，会自评很低（0.2~0.3），
            # 合并后把一次很好的识别报成"信心 30%"，反而让人不敢用。
            instruction = (
                f"这是一张长截图从上往下切出的第 {index}/{total} 段，"
                "只解析本段中出现的文字，不要推测其它段的内容；"
                "本段没有出现公司名、岗位名或薪资是正常的，不要因此降低 confidence。"
                "confidence 只表示你对『本段文字的识别准确度』的信心。"
            )
        data_url = f"data:{part_mime};base64,{base64.b64encode(content).decode()}"
        tasks.append(call_llm_vision(EXTRACT_PROMPT, instruction, data_url))

    # 并行调用：切片越多越能显出并行优势
    results = await asyncio.gather(*tasks, return_exceptions=True)

    drafts: list[JobDraft] = []
    errors: list[str] = []
    for item in results:
        if isinstance(item, BaseException):
            errors.append(str(item))
            continue
        try:
            drafts.append(JobDraft.model_validate_json(item))
        except ValidationError as e:
            errors.append(f"模型输出不符合格式: {e}")

    if not drafts:
        raise LLMError(errors[0] if errors else "模型没有返回可用结果")

    return _merge_drafts(drafts)


# 合并时"从上往下第一个非空值胜出"的字段：
# 公司/岗位/薪资在截图顶部，切片越多越不该让下面的段覆盖它们。
_MERGE_SCALARS = (
    "company",
    "position",
    "salary_min",
    "salary_max",
    "salary_note",
    "company_business",
    "source_detail",
    "url",
    "published_at",
)


def _merge_drafts(drafts: list[JobDraft]) -> JobDraft:
    """把多段切片的结果合并成一份草稿。"""
    if len(drafts) == 1:
        return drafts[0]

    merged = JobDraft()

    for name in _MERGE_SCALARS:
        for draft in drafts:
            value = getattr(draft, name)
            if value is not None and value != "":
                setattr(merged, name, value)
                break

    # source 有默认值「其他」，所以只在某段给出了具体渠道时才覆盖
    merged.source = next((d.source for d in drafts if d.source != "其他"), "其他")

    # 描述按切片顺序拼接，去掉完全重复的片段（重叠区会重复识别）
    pieces: list[str] = []
    for draft in drafts:
        text = (draft.description or "").strip()
        if text and text not in pieces:
            pieces.append(text)
    merged.description = "\n".join(pieces) or None

    # 信心只统计"真有内容"的切片。
    # 长截图切出来的结尾片往往大半是空白/页脚，它会自评很低（0.2~0.3），
    # 用全体 min() 会把一次很好的识别报成"信心 30%"，反而让人不敢用。
    informative = [
        d for d in drafts
        if (d.description or "").strip() or d.company or d.position
    ]
    pool = informative or drafts
    merged.confidence = min(d.confidence for d in pool)
    return merged


async def extract_resume_from_image(image_bytes: bytes, mime: str) -> str:
    """简历图片（拍照 / 截图）→ 逐字转录的文本。

    复用 prepare_images：超长图会自动切片，每段转录后按顺序拼接。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，无法识别简历图片")

    if not image_bytes:
        raise LLMError("图片内容为空")

    try:
        parts = prepare_images(image_bytes, mime)
    except Exception as e:
        raise LLMError(f"图片无法解析：{e}") from e

    total = len(parts)
    tasks = []
    for index, (content, part_mime) in enumerate(parts, start=1):
        if total == 1:
            note = "转录这张简历图片。"
        else:
            note = (
                f"这是一张长图从上往下切出的第 {index}/{total} 段，"
                "只转录本段出现的文字，不要推测其它段的内容。"
            )
        data_url = f"data:{part_mime};base64,{base64.b64encode(content).decode()}"
        tasks.append(call_llm_vision(RESUME_OCR_PROMPT, note, data_url))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    chunks: list[str] = []
    errors: list[str] = []
    for item in results:
        if isinstance(item, BaseException):
            errors.append(str(item))
            continue
        try:
            chunks.append(ResumeOCR.model_validate_json(item).text.strip())
        except ValidationError as e:
            errors.append(f"模型输出不符合格式: {e}")

    if not chunks:
        raise LLMError(errors[0] if errors else "模型没有返回可用结果")

    merged = "\n".join(chunk for chunk in chunks if chunk)
    if len(merged) < 30:
        raise LLMError("这张图里没识别出有效的简历内容，换一张更清晰的试试")
    return merged


async def call_llm_tools(messages: list[dict], tools: list[dict] | None = None):
    """带工具的多轮调用，返回原始 response。

    与 call_llm 的区别：这里**不解析内容**，因为要读 `tool_calls` 来决定下一步。
    编排逻辑在 services/assistant.py。
    """
    kwargs: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.3,
        "timeout": 90,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        return await _client.chat.completions.create(**kwargs)
    except Exception as e:
        raise LLMError(f"模型调用失败: {e}") from e


# ===== 面试准备 =====
# 依据只有三类：JD 原文、用户简历原文、行业通用知识。
# **刻意不做"某公司往年考过什么"**——面经零散、过时、无法验证真伪，
# 让模型回忆等于让它编，而用户会把编造的题当真去准备。
INTERVIEW_SYSTEM = """你是面试教练。根据用户的简历和这道岗位的 JD，预测这场面试会问什么，并给出答题要点。

输出 json，字段如下：
- questions: 12~15 道题，按「最可能被问」排序
  每题包含：
  - question: 问题本身。要具体，禁止「请介绍一下你的项目」这种空泛题
  - basis: "resume"（来自简历）| "jd"（来自岗位要求）| "general"（行业通用知识）
  - basis_quote: 依据原句。basis=resume 时从简历原文摘，basis=jd 时从 JD 原文摘，
                 basis=general 时填空字符串
  - why_asked: 一句话说明面试官想验证什么
  - your_status: "ok"（简历里有对应经历，能答）| "gap"（简历看不出相关能力，很可能答不上来）
                 | "unknown"（无法判断）
  - reference_answer: 答题骨架，150~250 字。要具体到能照着说出来，不要泛泛而谈
  - follow_up: 面试官听到这个回答后会追问什么，一句话
- gaps_summary: 3~5 条，面试前必须补的点，按优先级排
- prep_advice: 一段话，说明这份准备怎么用、时间怎么分配

硬性规则：
1. 题目必须来自材料。basis=resume 的题必须能在简历里找到对应经历；
   basis=jd 的题必须对应 JD 的某条要求。不许出与材料无关的题
2. **禁止声称「该公司往年考过 X」**。你没有这个信息，编造会误导用户
3. 优先出深挖类题（追问项目细节、技术决策、边界情况），少出纯背诵题
4. reference_answer 必须基于简历里**真实存在的经历**组织。
   绝不能虚构用户没做过的事。简历里没有的能力，如实标 gap，
   并在答案里给「怎么答才不露怯」（如承认没做过、说明相邻经验、给出学习路径）
5. 中文，直接给内容，不要客套和铺垫
"""


async def generate_interview_prep(jd: str, profile: str) -> InterviewPrep:
    """业务层：JD + 简历 → 面试准备（预测题 + 答案 + 弱点）。

    输出很长（15 道题带答案约 4000~6000 token），所以放宽超时和上限。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，无法生成面试准备")

    if not jd.strip():
        raise LLMError("JD 内容为空")

    if not profile.strip():
        raise LLMError("简历内容为空")

    # 简历在前、JD 在后：同一用户的简历固定，前缀稳定才能命中上下文缓存
    user_content = f"【我的简历】\n{profile[:6000]}\n\n【JD原文】\n{jd[:2000]}"

    raw = await call_llm(INTERVIEW_SYSTEM, user_content, timeout=180, max_tokens=8000)

    try:
        return InterviewPrep.model_validate_json(raw)
    except ValidationError as e:
        raise LLMError(f"模型输出不符合格式: {e}") from e