"""估值结果融合（方案第十章）。

综合价值 = Σ 模型价值 × 行业权重；模型不可用时权重重新归一，不做简单算术平均。
输出：悲观/基准/乐观价值、加权合理价值、上下行空间、安全边际、模型分歧度。
"""
from __future__ import annotations

import statistics
from typing import Any

from app.services.valuation.industry_config import IndustryConfig


def fuse_models(
    model_values: dict[str, dict[str, float | None]],
    industry: IndustryConfig,
    current_price: float | None,
) -> dict[str, Any]:
    """融合各模型×情景的每股价值（报告币种）。

    model_values: {model_name: {scenario: value_per_share|None}}
    """
    weights = dict(industry.model_weight)
    scenarios = ("pessimistic", "base", "optimistic")
    fused: dict[str, float | None] = {}
    weight_used: dict[str, dict[str, float]] = {}
    for sc in scenarios:
        avail = {
            m: v[sc] for m, v in model_values.items()
            if v.get(sc) is not None and weights.get(m, 0) > 0 and v[sc] > 0
        }
        if not avail:
            fused[sc] = None
            weight_used[sc] = {}
            continue
        total_w = sum(weights[m] for m in avail)
        norm = {m: weights[m] / total_w for m in avail}
        fused[sc] = sum(avail[m] * norm[m] for m in avail)
        weight_used[sc] = {m: round(w, 4) for m, w in norm.items()}

    fair = fused.get("base")
    # 模型分歧度：基准情景各模型价值的变异系数（方案第十章"模型分歧程度"）
    base_vals = [v["base"] for v in model_values.values() if v.get("base") is not None and v["base"] > 0]
    divergence = None
    if len(base_vals) >= 2 and statistics.fmean(base_vals) > 0:
        divergence = statistics.pstdev(base_vals) / statistics.fmean(base_vals)

    upside = downside = safety_margin = None
    if fair is not None and current_price and current_price > 0:
        upside = fair / current_price - 1.0
        safety_margin = 1.0 - current_price / fair if fair > 0 else None
        if fused.get("pessimistic") is not None:
            downside = fused["pessimistic"] / current_price - 1.0

    return {
        "value_pessimistic": fused.get("pessimistic"),
        "value_base": fair,
        "value_optimistic": fused.get("optimistic"),
        "weighted_fair_value": fair,
        "current_price": current_price,
        "upside": upside,                    # (合理价值/现价 - 1)
        "downside_to_pessimistic": downside, # 悲观情景对应涨跌幅
        "safety_margin": safety_margin,      # 1 - 现价/合理价值
        "model_divergence": divergence,
        "weights_used": weight_used,
        "industry_weights_config": {k: v for k, v in industry.model_weight.items()},
    }
