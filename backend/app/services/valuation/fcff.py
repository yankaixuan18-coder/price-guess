"""FCFF 折现现金流模型（方案 8.1）。

FCFF = EBIT ×（1-税率）+ 折旧摊销 - 资本开支 - 营运资本增加
企业价值 = 预测期 FCFF 现值 + 终值现值
股权价值 = 企业价值 - 净债务 - 优先股 - 少数股东权益 + 非经营性资产

硬校验（方案第二十章模型标准）：
- WACC <= 永续增长率时禁止计算（抛出 ValueError）；
- 终值占比 > 70% 时输出告警（方案二十一风险 3）；
- 每股价值使用稀释后股本。
终值同时计算永续增长法与退出倍数法，两者差异过大（>35%）时提示（方案 8.1）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TERMINAL_SHARE_WARN = 0.70
TERMINAL_METHOD_DIVERGENCE_WARN = 0.35


@dataclass
class FcffAssumptions:
    """FCFF 模型假设。比率均为小数。金额单位与基期报表一致（百万，报告币种）。"""

    revenue_growth: list[float]        # 逐年收入增速（长度=预测年数）
    terminal_ebit_margin: float        # 稳态 EBIT 利润率（预测期线性滑向该值）
    wacc: float
    terminal_growth: float
    tax_rate: float
    da_pct_revenue: float              # 折旧摊销 / 收入
    capex_pct_revenue: float           # 资本开支 / 收入
    wc_pct_revenue: float              # 营运资本 / 收入（增量法：ΔWC = 比例 × Δ收入）
    exit_ev_ebitda: float | None = None  # 退出倍数法参考倍数


@dataclass
class FcffBase:
    """估值基期数据（最近一个完整财年）。"""

    revenue: float
    ebit_margin: float                 # 基期 EBIT 利润率
    net_debt: float
    minority_interest: float = 0.0
    preferred_equity: float = 0.0
    non_operating_assets: float = 0.0  # 非经营性资产（如长期股权投资）
    diluted_shares: float = 1.0        # 百万股


@dataclass
class FcffResult:
    enterprise_value: float
    equity_value: float
    value_per_share: float
    pv_explicit: float
    pv_terminal: float
    terminal_value_share: float        # 终值现值占企业价值比例
    terminal_value_gordon: float       # 永续增长法终值（未折现）
    terminal_value_exit: float | None  # 退出倍数法终值（未折现）
    forecast_table: list[dict[str, float]]
    warnings: list[str] = field(default_factory=list)


def run_fcff(base: FcffBase, a: FcffAssumptions) -> FcffResult:
    if a.wacc <= a.terminal_growth:
        raise ValueError(
            f"WACC ({a.wacc:.2%}) 必须大于永续增长率 ({a.terminal_growth:.2%})，已禁止计算"
        )
    if base.diluted_shares <= 0:
        raise ValueError("稀释股本必须为正")

    warnings: list[str] = []
    n = len(a.revenue_growth)
    if n < 3:
        warnings.append("预测期少于 3 年，估值高度依赖终值")

    # 预测期：EBIT 利润率从基期线性过渡到稳态
    table: list[dict[str, float]] = []
    revenue = base.revenue
    pv_explicit = 0.0
    fcff_last = 0.0
    ebitda_last = 0.0
    for t in range(1, n + 1):
        revenue = revenue * (1.0 + a.revenue_growth[t - 1])
        margin = base.ebit_margin + (a.terminal_ebit_margin - base.ebit_margin) * t / n
        ebit = revenue * margin
        nopat = ebit * (1.0 - a.tax_rate)
        da = revenue * a.da_pct_revenue
        capex = revenue * a.capex_pct_revenue
        prev_revenue = table[-1]["revenue"] if table else base.revenue
        delta_wc = a.wc_pct_revenue * (revenue - prev_revenue)
        fcff = nopat + da - capex - delta_wc
        df = (1.0 + a.wacc) ** t
        pv = fcff / df
        pv_explicit += pv
        fcff_last, ebitda_last = fcff, ebit + da
        table.append({
            "year": t, "revenue": revenue, "revenue_growth": a.revenue_growth[t - 1],
            "ebit_margin": margin, "ebit": ebit, "nopat": nopat, "da": da,
            "capex": capex, "delta_wc": delta_wc, "fcff": fcff,
            "discount_factor": 1.0 / df, "pv_fcff": pv,
        })

    # 终值法一：永续增长（Gordon）
    tv_gordon = fcff_last * (1.0 + a.terminal_growth) / (a.wacc - a.terminal_growth)
    # 终值法二：退出倍数（EV/EBITDA）
    tv_exit = ebitda_last * a.exit_ev_ebitda if a.exit_ev_ebitda else None
    if tv_exit is not None and tv_gordon > 0 and tv_exit > 0:
        div = abs(tv_gordon - tv_exit) / ((tv_gordon + tv_exit) / 2.0)
        if div > TERMINAL_METHOD_DIVERGENCE_WARN:
            warnings.append(
                f"永续增长法与退出倍数法终值差异 {div:.0%}，超过 {TERMINAL_METHOD_DIVERGENCE_WARN:.0%}，"
                "请复核稳态假设"
            )
    terminal_value = tv_gordon  # 以永续增长法为主口径
    pv_terminal = terminal_value / (1.0 + a.wacc) ** n

    ev = pv_explicit + pv_terminal
    tv_share = pv_terminal / ev if ev > 0 else 1.0
    if tv_share > TERMINAL_SHARE_WARN:
        warnings.append(
            f"终值现值占企业价值 {tv_share:.0%}，超过 {TERMINAL_SHARE_WARN:.0%}，估值高度依赖远期假设"
        )
    if fcff_last <= 0:
        warnings.append("预测期末 FCFF 为负，永续增长法终值不可靠")

    equity = ev - base.net_debt - base.preferred_equity - base.minority_interest + base.non_operating_assets
    vps = equity / base.diluted_shares
    if equity < 0:
        warnings.append("股权价值为负：企业价值不足以覆盖净债务及少数股东权益")

    return FcffResult(
        enterprise_value=ev,
        equity_value=equity,
        value_per_share=vps,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        terminal_value_share=tv_share,
        terminal_value_gordon=tv_gordon,
        terminal_value_exit=tv_exit,
        forecast_table=table,
        warnings=warnings,
    )


def result_to_dict(r: FcffResult) -> dict[str, Any]:
    return {
        "enterprise_value": r.enterprise_value,
        "equity_value": r.equity_value,
        "value_per_share": r.value_per_share,
        "pv_explicit": r.pv_explicit,
        "pv_terminal": r.pv_terminal,
        "terminal_value_share": r.terminal_value_share,
        "terminal_value_gordon": r.terminal_value_gordon,
        "terminal_value_exit": r.terminal_value_exit,
        "forecast_table": r.forecast_table,
        "warnings": r.warnings,
    }
