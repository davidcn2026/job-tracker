from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
