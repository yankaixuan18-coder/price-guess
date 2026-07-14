"""行业估值模板与模型权重（方案第九、十章 industry_model_config）。

MVP 覆盖第一批行业（消费/制造/软件/互联网/公用事业），
银行、保险等第二批行业保留配置占位并在 caveat 中说明当前使用通用模型的局限。
权重不做简单平均，按行业特征分配；模型不可用时权重重新归一。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IndustryConfig:
    industry_code: str
    industry_name: str
    primary_models: list[str]
    model_weight: dict[str, float]           # 各模型融合权重（方案第十章）
    terminal_growth_limit: float = 0.03      # 永续增长率上限
    wacc_range: tuple[float, float] = (0.06, 0.14)
    exit_ev_ebitda_hint: float | None = None # 退出倍数参考
    scenario_multiple_shift: dict[str, float] = field(
        default_factory=lambda: {"pessimistic": -0.20, "base": 0.0, "optimistic": 0.20}
    )
    warning_rules: list[str] = field(default_factory=list)
    caveat: str | None = None


INDUSTRY_CONFIGS: dict[str, IndustryConfig] = {
    "consumer": IndustryConfig(
        industry_code="consumer", industry_name="消费品",
        primary_models=["fcff", "relative_pe"],
        model_weight={"fcff": 0.50, "relative_pe": 0.30, "relative_ev_ebitda": 0.10, "relative_pb": 0.10},
        terminal_growth_limit=0.03, wacc_range=(0.070, 0.130), exit_ev_ebitda_hint=14.0,
        warning_rules=["高端消费注意渠道库存周期"],
    ),
    "manufacturing": IndustryConfig(
        industry_code="manufacturing", industry_name="一般制造业",
        primary_models=["fcff", "relative_ev_ebitda"],
        model_weight={"fcff": 0.45, "relative_pe": 0.20, "relative_ev_ebitda": 0.25, "relative_pb": 0.10},
        terminal_growth_limit=0.025, wacc_range=(0.075, 0.130), exit_ev_ebitda_hint=10.0,
        warning_rules=["注意资本开支周期与产能利用率"],
    ),
    "software": IndustryConfig(
        industry_code="software", industry_name="软件与互联网",
        primary_models=["fcff", "relative_pe"],
        model_weight={"fcff": 0.45, "relative_pe": 0.30, "relative_ev_ebitda": 0.20, "relative_pb": 0.05},
        terminal_growth_limit=0.035, wacc_range=(0.075, 0.140), exit_ev_ebitda_hint=18.0,
        warning_rules=["SBC 高的公司必须使用稀释股本", "关注 Rule of 40"],
    ),
    "internet": IndustryConfig(
        industry_code="internet", industry_name="互联网平台",
        primary_models=["fcff", "relative_pe"],
        model_weight={"fcff": 0.45, "relative_pe": 0.30, "relative_ev_ebitda": 0.20, "relative_pb": 0.05},
        terminal_growth_limit=0.035, wacc_range=(0.080, 0.140), exit_ev_ebitda_hint=15.0,
        warning_rules=["投资资产占比高时应考虑 SOTP（第二阶段）"],
        caveat="控股型平台的投资组合价值未单独估值，SOTP 在路线图中",
    ),
    "utilities": IndustryConfig(
        industry_code="utilities", industry_name="公用事业",
        primary_models=["fcff", "relative_ev_ebitda"],
        model_weight={"fcff": 0.50, "relative_pe": 0.15, "relative_ev_ebitda": 0.25, "relative_pb": 0.10},
        terminal_growth_limit=0.025, wacc_range=(0.055, 0.110), exit_ev_ebitda_hint=9.0,
        warning_rules=["股息政策稳定的公司后续应叠加 DDM"],
    ),
    # ---- 第二批行业（占位，方案第十八章阶段 3）----
    "bank": IndustryConfig(
        industry_code="bank", industry_name="银行",
        primary_models=["relative_pb"],
        model_weight={"relative_pb": 0.70, "relative_pe": 0.30},
        terminal_growth_limit=0.03,
        caveat="银行应使用 PB-ROE / 剩余收益 / DDM（阶段 3），当前仅提供相对估值，FCFF 不适用",
    ),
    "insurance": IndustryConfig(
        industry_code="insurance", industry_name="保险",
        primary_models=["relative_pb"],
        model_weight={"relative_pb": 0.70, "relative_pe": 0.30},
        terminal_growth_limit=0.03,
        caveat="保险应使用 P/EV 与剩余收益模型（阶段 3），当前仅提供相对估值",
    ),
}

DEFAULT_CONFIG = IndustryConfig(
    industry_code="general", industry_name="通用",
    primary_models=["fcff"],
    model_weight={"fcff": 0.45, "relative_pe": 0.25, "relative_ev_ebitda": 0.20, "relative_pb": 0.10},
    terminal_growth_limit=0.03, wacc_range=(0.070, 0.130), exit_ev_ebitda_hint=10.0,
)

# FCFF 不适用的行业（金融类：经营现金流口径与 WACC 框架不匹配）
FCFF_EXCLUDED_INDUSTRIES = {"bank", "insurance"}


def get_industry_config(industry_code: str) -> IndustryConfig:
    return INDUSTRY_CONFIGS.get(industry_code, DEFAULT_CONFIG)
