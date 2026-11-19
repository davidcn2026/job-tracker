from openai import AsyncOpenAI
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.llm import AnalysisResult

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

PROFILE_SUMMARY: str = """【目标岗位】AI 应用开发 / Python 后端开发（校招或实习）
【学历】南昌航空大学 网络工程 本科，2027 届

【语言与框架】Python 熟练（asyncio / async-await）；FastAPI（路由、依赖注入、中间件、全局异常处理）；Pydantic v2 校验；RESTful API 与 OpenAPI
【数据存储】SQLAlchemy 2.0 异步 ORM（实体映射、条件/聚合/分页查询、多表关联、ForeignKey）；MySQL 8（建表、关联查询、索引基础）；Redis（缓存策略、key 设计、失效与 TTL）
【认证与安全】JWT 认证链路（注册 / 登录 / Token 校验 / 改密）、密码加盐哈希、Depends 统一鉴权
【AI 应用】LLM API 集成封装（Prompt 构造、超时重试、降级、结果缓存）；RAG（文本切分、向量化检索、ChromaDB）；Agent 工具调用与权限闸门
【测试与工程】pytest + httpx 接口测试、unittest、Git / GitHub、Docker 镜像构建与部署、Linux 常用命令

【项目一】Coding Agent Harness：从零实现可执行本地命令的编码 Agent。Agent Loop + 工具查表分发（bash/read_file/write_file/edit_file/glob 共 5 个）+ 三级权限闸门（静态 deny-list、上下文正则规则、人工确认）+ 四事件 hook 扩展点 + JSONL 审计日志。
【项目二】新闻头条后端（前后端分离资讯平台）：FastAPI + SQLAlchemy 2.0 异步栈，routers/schemas/models/crud 分层，统一响应模型与全局异常处理器，JWT 完整认证链路，Redis 缓存热点数据，封装第三方大模型问答模块，pytest 接口测试，Docker 部署。

【明确边界】无大厂实习经历；深度学习仅学完《深度学习入门》前 5 章，无模型训练 / 微调实战；无高并发与分布式系统经验；无算法竞赛经历。
"""


async def call_llm(system: str, user: str) -> str:
    """底层调用，返回模型原始文本。

    要点：
    - httpx.AsyncClient(timeout=30.0)
    - 失败（超时/非 200）抛 LLMError
    """
    try:
        response = await _client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            timeout=30,
            response_format={"type": "json_object"},
        )
    except Exception as e:          # 任何 SDK /

        # 网络 / 超时失败都归为 LLMError
        raise LLMError(f"模型调用失败: {e}") from e

    content = response.choices[0].message.content
    if not content:
        raise LLMError("模型返回了空内容")
    return content


async def analyze_jd(jd: str) -> AnalysisResult:
    """业务层：拼提示词 → 调模型 → 解析 JSON → 校验 → 返回结构。

    失败一律抛 LLMError（含模型输出格式不对），由 router 翻译成 503。
    """
    if not settings.deepseek_api_key:
        raise LLMError("未配置 DEEPSEEK_API_KEY，无法进行 AI 分析")

    if not jd.strip():
        raise LLMError("JD 内容为空")

    # 固定内容放在前面：SYSTEM_PROMPT + PROFILE_SUMMARY 每次都相同，
    # 前缀稳定才能命中上下文缓存（命中后输入价格远低于未命中）。
    # JD 截断到 1500 字：岗位要求基本都在前半部分，可省 30%~50% 输入 token。
    user_content = f"【我的技能】\n{PROFILE_SUMMARY}\n\n【JD原文】\n{jd[:1500]}"

    raw = await call_llm(SYSTEM_PROMPT, user_content)

    try:
        return AnalysisResult.model_validate_json(raw)
    except ValidationError as e:
        # 模型输出不是合法 JSON，或字段/枚举/范围不合规
        raise LLMError(f"模型输出不符合格式: {e}") from e