"""盈利预测引擎 —— 一级：历史趋势预测（方案 7.1）+ 三情景默认假设（方案 7.2）。

从历史指标自动生成 悲观 / 基准 / 乐观 三套默认假设，全部可被用户覆盖
（AssumptionSet 中每个参数记录来源 default / user_override）。
二级经营驱动与三级机器学习预测在路线图中（方案 7.1）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.services.valuation.industry_config import IndustryConfig

FORECAST_YEARS = 5

# 情景参数方向（方案 7.2 表：收入增速 低/中/高，WACC 高/中/低，永续增长 低/中/高）
SCENARIOS = ("pessimistic", "base", "optimistic")


@dataclass
class WaccInputs:
    risk_free: float
    erp: float
    beta: float
    credit_spread: float
    tax_rate: float
    market_cap: float     # 股权市值（报告币种，百万）
    total_debt: float     # 有息负债（报告币种，百万）


def compute_wacc(w: WaccInputs) -> dict[str, float]:
    """WACC = E/(D+E)×Ke + D/(D+E)×Kd×(1-T)（方案 8.1）。"""
    ke = w.risk_free + w.beta * w.erp
    kd = w.risk_free + w.credit_spread
    total = max(w.market_cap + w.total_debt, 1e-9)
    we = w.market_cap / total
    wd = w.total_debt / total
    wacc = we * ke + wd * kd * (1 - w.tax_rate)
    return {"ke": ke, "kd": kd, "weight_equity": we, "weight_debt": wd, "wacc": wacc}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def default_assumptions(
    summary: dict[str, Any],
    latest_annual: dict[str, Any],
    market: str,
    risk_free: float,
    beta: float,
    market_cap: float,
    total_debt: float,
    industry: IndustryConfig,
) -> dict[str, dict[str, float]]:
    """生成三情景默认假设。返回 {scenario: {param: value}}。

    参数含义与 FcffAssumptions 一致；revenue_growth_5y 为 5 年均匀年增速。
    """
    tax = latest_annual.get("effective_tax_rate") or 0.25

    # ---- 收入增速：3 年与 5 年 CAGR 融合，向长期均值收敛（均值回归，方案 7.1）----
    g3 = summary.get("revenue_cagr_3y")
    g5 = summary.get("revenue_cagr_5y")
    hist_g = next((v for v in (g3, g5) if v is not None), 0.05)
    if g3 is not None and g5 is not None:
        hist_g = 0.6 * g3 + 0.4 * g5
    base_g = _clamp(0.75 * hist_g + 0.25 * 0.04, -0.05, 0.25)  # 向 4% 长期名义增速回归
    spread = max(0.03, abs(base_g) * 0.4)
    pess_g = _clamp(base_g - spread, -0.10, 0.22)
    opt_g = _clamp(base_g + spread, -0.03, 0.30)

    # ---- 稳态 EBIT 利润率：当前与 5 年均值折中 ----
    cur_m = latest_annual.get("ebit_margin") or 0.10
    avg_m = (summary.get("ebit_margin_stat") or {}).get("mean") or cur_m
    base_m = 0.5 * cur_m + 0.5 * avg_m
    m_spread = max(0.01, abs(base_m) * 0.12)
    pess_m = max(0.01, base_m - m_spread)
    opt_m = base_m + m_spread

    # ---- WACC（CAPM）----
    erp = settings.equity_risk_premium.get(market, 0.055)
    spread_kd = settings.credit_spread.get(market, 0.015)
    wacc_detail = compute_wacc(WaccInputs(
        risk_free=risk_free, erp=erp, beta=beta, credit_spread=spread_kd,
        tax_rate=tax, market_cap=market_cap, total_debt=total_debt,
    ))
    lo, hi = industry.wacc_range
    base_wacc = _clamp(wacc_detail["wacc"], lo, hi)

    # ---- 永续增长率：默认 2/2.5/3%，受行业上限约束 ----
    tg_limit = industry.terminal_growth_limit
    base_tg = min(0.025, tg_limit)
    pess_tg = min(0.02, tg_limit - 0.002)
    opt_tg = min(0.03, tg_limit)

    # ---- 再投资相关比率：取近三年均值（缺失回退经验值）----
    da_pct = latest_annual.get("da_pct") or 0.04
    capex_pct = latest_annual.get("capex_to_revenue") or 0.05
    wc_pct = latest_annual.get("wc_pct") or 0.05

    def _pack(g: float, m: float, wacc: float, tg: float, mult_shift: float) -> dict[str, float]:
        return {
            "forecast_years": FORECAST_YEARS,
            "revenue_growth_5y": round(g, 4),
            "terminal_ebit_margin": round(m, 4),
            "wacc": round(wacc, 4),
            "terminal_growth": round(tg, 4),
            "tax_rate": round(tax, 4),
            "da_pct_revenue": round(da_pct, 4),
            "capex_pct_revenue": round(capex_pct, 4),
            "wc_pct_revenue": round(wc_pct, 4),
            "multiple_shift": mult_shift,
        }

    shifts = industry.scenario_multiple_shift
    return {
        "pessimistic": _pack(pess_g, pess_m, base_wacc + 0.01, pess_tg, shifts["pessimistic"]),
        "base": _pack(base_g, base_m, base_wacc, base_tg, shifts["base"]),
        "optimistic": _pack(opt_g, opt_m, max(base_wacc - 0.01, base_tg + 0.01), opt_tg, shifts["optimistic"]),
        "_wacc_detail": {k: round(v, 4) for k, v in wacc_detail.items()},
    }


def merge_overrides(
    defaults: dict[str, dict[str, float]],
    overrides: dict[str, dict[str, float]] | None,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """合并用户覆盖（方案 7.2：手动调整/参数锁定）。

    overrides 形如 {"base": {"wacc": 0.09}} 或 {"all": {...}} 作用于三情景。
    返回 (合并后假设, 参数来源标记)。
    """
    merged: dict[str, dict[str, float]] = {}
    sources: dict[str, dict[str, str]] = {}
    ov = overrides or {}
    for sc in SCENARIOS:
        merged[sc] = dict(defaults[sc])
        sources[sc] = {k: "default" for k in merged[sc]}
        for layer in ("all", sc):
            for k, v in (ov.get(layer) or {}).items():
                if k in merged[sc] and v is not None:
                    merged[sc][k] = float(v)
                    sources[sc][k] = "user_override"
    return merged, sources
