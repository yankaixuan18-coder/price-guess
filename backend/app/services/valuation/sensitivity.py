"""敏感性分析（方案 12.3 敏感性矩阵）：WACC × 永续增长率 双向矩阵。"""
from __future__ import annotations

from typing import Any

from app.services.valuation.fcff import FcffAssumptions, FcffBase, run_fcff


def wacc_growth_matrix(
    base: FcffBase,
    a: FcffAssumptions,
    wacc_step: float = 0.005,
    growth_step: float = 0.0025,
    n_steps: int = 2,
) -> dict[str, Any]:
    """以基准 WACC / 永续增长率为中心，生成 (2n+1)×(2n+1) 每股价值矩阵。

    WACC <= g 的格子返回 None（禁止计算，方案第二十章）。
    """
    waccs = [a.wacc + i * wacc_step for i in range(-n_steps, n_steps + 1)]
    growths = [a.terminal_growth + i * growth_step for i in range(-n_steps, n_steps + 1)]
    values: list[list[float | None]] = []
    for w in waccs:
        row: list[float | None] = []
        for g in growths:
            if w <= g + 0.001 or w <= 0:
                row.append(None)
                continue
            trial = FcffAssumptions(
                revenue_growth=list(a.revenue_growth),
                terminal_ebit_margin=a.terminal_ebit_margin,
                wacc=w,
                terminal_growth=g,
                tax_rate=a.tax_rate,
                da_pct_revenue=a.da_pct_revenue,
                capex_pct_revenue=a.capex_pct_revenue,
                wc_pct_revenue=a.wc_pct_revenue,
            )
            try:
                row.append(round(run_fcff(base, trial).value_per_share, 4))
            except ValueError:
                row.append(None)
        values.append(row)
    return {
        "axis_x": "terminal_growth",
        "axis_y": "wacc",
        "x_values": [round(g, 6) for g in growths],
        "y_values": [round(w, 6) for w in waccs],
        "values": values,
    }
