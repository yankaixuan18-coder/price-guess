"""反向 DCF（方案 8.7 / 12.4）。

不预测公司值多少钱，而是从当前股价反推市场隐含假设：
- 固定利润率、WACC、永续增长率，求解使 DCF 价值 = 当前市值的
  隐含 5 年收入复合增速；
- 固定收入增速，求解隐含永续增长率；
输出与历史增速的对比，帮助判断当前价格要求的预期是否苛刻。
"""
from __future__ import annotations

from typing import Any

from app.services.valuation.fcff import FcffAssumptions, FcffBase, run_fcff

GROWTH_LO, GROWTH_HI = -0.50, 1.00
TG_LO = -0.02


def _value_at_growth(base: FcffBase, a: FcffAssumptions, g: float) -> float:
    trial = FcffAssumptions(
        revenue_growth=[g] * len(a.revenue_growth),
        terminal_ebit_margin=a.terminal_ebit_margin,
        wacc=a.wacc,
        terminal_growth=a.terminal_growth,
        tax_rate=a.tax_rate,
        da_pct_revenue=a.da_pct_revenue,
        capex_pct_revenue=a.capex_pct_revenue,
        wc_pct_revenue=a.wc_pct_revenue,
        exit_ev_ebitda=None,
    )
    return run_fcff(base, trial).value_per_share


def implied_revenue_growth(
    base: FcffBase, a: FcffAssumptions, current_price: float, tol: float = 1e-4
) -> dict[str, Any]:
    """二分法求解隐含收入增速。DCF 价值对增速单调递增，故可二分。"""
    if current_price <= 0:
        return {"solved": False, "reason": "当前价格无效"}
    lo, hi = GROWTH_LO, GROWTH_HI
    v_lo = _value_at_growth(base, a, lo)
    v_hi = _value_at_growth(base, a, hi)
    if current_price <= v_lo:
        return {"solved": False, "reason": f"即使收入年降 {-GROWTH_LO:.0%} 模型价值仍高于现价，现价隐含极端悲观预期",
                "boundary": "below", "implied_growth": lo}
    if current_price >= v_hi:
        return {"solved": False, "reason": f"即使收入年增 {GROWTH_HI:.0%} 模型价值仍低于现价，现价隐含超高增长预期",
                "boundary": "above", "implied_growth": hi}
    for _ in range(100):
        mid = (lo + hi) / 2.0
        v = _value_at_growth(base, a, mid)
        if abs(v - current_price) / current_price < tol:
            return {"solved": True, "implied_growth": mid, "model_value_at_solution": v}
        if v < current_price:
            lo = mid
        else:
            hi = mid
    return {"solved": True, "implied_growth": (lo + hi) / 2.0, "converged": False}


def implied_terminal_growth(
    base: FcffBase, a: FcffAssumptions, current_price: float, tol: float = 1e-4
) -> dict[str, Any]:
    """固定预测期假设，求解隐含永续增长率（上限 WACC-0.5%）。"""
    if current_price <= 0:
        return {"solved": False, "reason": "当前价格无效"}
    lo, hi = TG_LO, a.wacc - 0.005

    def _value_at_tg(tg: float) -> float:
        trial = FcffAssumptions(
            revenue_growth=list(a.revenue_growth),
            terminal_ebit_margin=a.terminal_ebit_margin,
            wacc=a.wacc,
            terminal_growth=tg,
            tax_rate=a.tax_rate,
            da_pct_revenue=a.da_pct_revenue,
            capex_pct_revenue=a.capex_pct_revenue,
            wc_pct_revenue=a.wc_pct_revenue,
        )
        return run_fcff(base, trial).value_per_share

    if current_price <= _value_at_tg(lo):
        return {"solved": False, "boundary": "below", "implied_terminal_growth": lo,
                "reason": "现价低于永续增长为负时的模型价值"}
    if current_price >= _value_at_tg(hi):
        return {"solved": False, "boundary": "above", "implied_terminal_growth": hi,
                "reason": "隐含永续增长率逼近 WACC，现价包含极高远期预期"}
    for _ in range(100):
        mid = (lo + hi) / 2.0
        v = _value_at_tg(mid)
        if abs(v - current_price) / current_price < tol:
            return {"solved": True, "implied_terminal_growth": mid}
        if v < current_price:
            lo = mid
        else:
            hi = mid
    return {"solved": True, "implied_terminal_growth": (lo + hi) / 2.0, "converged": False}


def reverse_dcf_report(
    base: FcffBase,
    a: FcffAssumptions,
    current_price_report_ccy: float,
    hist_revenue_cagr_3y: float | None,
    hist_revenue_cagr_5y: float | None,
    peer_growth_median: float | None = None,
) -> dict[str, Any]:
    """完整反向 DCF 报告（隐含增速 + 隐含永续增长 + 历史/同行对照）。"""
    ig = implied_revenue_growth(base, a, current_price_report_ccy)
    itg = implied_terminal_growth(base, a, current_price_report_ccy)
    verdict = None
    if ig.get("implied_growth") is not None and hist_revenue_cagr_3y is not None:
        gap = ig["implied_growth"] - hist_revenue_cagr_3y
        if gap > 0.05:
            verdict = "当前价格隐含增速显著高于近三年实际增速，市场定价了加速增长"
        elif gap < -0.05:
            verdict = "当前价格隐含增速显著低于近三年实际增速，市场定价了明显减速"
        else:
            verdict = "当前价格隐含增速与近三年实际增速大体一致"
    return {
        "current_price_report_ccy": current_price_report_ccy,
        "implied_revenue_growth_5y": ig,
        "implied_terminal_growth": itg,
        "history": {
            "revenue_cagr_3y": hist_revenue_cagr_3y,
            "revenue_cagr_5y": hist_revenue_cagr_5y,
            "peer_growth_median": peer_growth_median,
        },
        "held_constant": {
            "terminal_ebit_margin": a.terminal_ebit_margin,
            "wacc": a.wacc,
            "terminal_growth": a.terminal_growth,
            "tax_rate": a.tax_rate,
        },
        "verdict": verdict,
    }
