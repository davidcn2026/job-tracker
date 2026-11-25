from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.job import Source, Status

# 模型只输出这四档。「待定」不在这里——它由多次采样不一致时在聚合层产生。
Verdict = Literal["推荐投递", "可考虑投递", "可以投递", "不建议投递"]


class AnalysisResult(BaseModel):
    """模型对一份 JD 的分析结果。

    字段顺序即语义顺序：先判有无核心缺失（blocking），再看命中情况，
    最后给档位和一句话结论。
    """

    match_score: int = Field(ge=0, le=100)
    verdict: Verdict
    blocking_gaps: list[str] = Field(default_factory=list)  # 核心硬性要求中"完全没有"的项
    gaps: list[str] = Field(default_factory=list)           # 次要 / 加分项缺失，不影响档位
    matched: list[str] = Field(default_factory=list)        # 候选人已满足的要求
    summary: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _enforce_blocking_rule(self) -> "AnalysisResult":
        """核心能力缺失 → 强制「不建议投递」且分数不超过 49。

        不靠提示词祈祷：模型给的档位和分数可能自相矛盾（比如把缺 Java 的岗位
        判成「可以投递」）。这条产品规则「主要能力缺失一律不建议」由代码兜底，
        才能保证同一份 JD 的结论稳定。
        """
        if self.blocking_gaps:
            self.verdict = "不建议投递"
            if self.match_score > 49:
                self.match_score = 49
        return self


class ResumeOCR(BaseModel):
    """从简历图片（拍照 / 截图）里转录出来的文本。

    只做"逐字转录"，不做总结改写 —— 简历原文才是分析要用的东西。
    """

    text: str = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class JobDraft(BaseModel):
    """从截图（或粘贴文本）里抽出来的岗位草稿。

    与 JobIn 的区别：这里的字段**全都可空**——截图可能只拍到半屏，
    公司名、薪资都可能没出现。所以它不能直接入库，
    必须先由用户在前端表单里确认/补全，再走 POST /jobs。

    confidence 是模型对抽取结果的自我评估，用于前端提示"这个可能不准"。
    它不入库，只作为一次性的展示提示。
    """

    company: str | None = Field(default=None, max_length=100)
    position: str | None = Field(default=None, max_length=100)
    status: Status = "待投"
    source: Source = "其他"
    source_detail: str | None = Field(default=None, max_length=100)
    salary_min: int | None = Field(default=None, ge=0, le=1000)
    salary_max: int | None = Field(default=None, ge=0, le=1000)
    salary_note: str | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=500)
    published_at: date | None = None
    company_business: str | None = Field(default=None, max_length=200)
    description: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("salary_min", "salary_max", mode="before")
    @classmethod
    def _normalize_salary_unit(cls, value: object) -> object:
        """把"元"折算回"千元"。

        实测踩到过：截图写「25-40K」，模型返回 25000 / 40000（按元理解），
        而本字段的单位是「千元/月」、上限 1000 → 校验失败 → 整个请求 503。
        用户截图明明能识别却报"服务不可用"，是坏体验。

        所以 >= 1000 一律当作"元"折回千元。月薪 1000 元以下的工作不存在，
        这个阈值不会误伤。
        """
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 1000:
            return round(value / 1000)
        return value

    @model_validator(mode="after")
    def _fix_salary_range(self) -> "JobDraft":
        """模型可能把上下限写反（如 25/15）。批量场景下直接交换比报错好——
        这只是一份待用户确认的草稿，不该因为顺序问题让整次抽取失败。"""
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            self.salary_min, self.salary_max = self.salary_max, self.salary_min
        return self
