"""估值可信度评分 0-100（方案第十一章）。

因素与权重：
  财务数据完整性 20% ｜ 盈利稳定性 15% ｜ 现金流稳定性 15% ｜ 模型适配程度 15%
  预测误差 15%（回测上线前取中性值，方案阶段 4）｜ 会计复杂度 10% ｜ 模型一致性 10%
并输出触发的降低可信度原因清单（持续亏损、终值占比过高、模型分歧过大、
现金流与利润长期背离、股本持续稀释等）。
"""
from __future__ import annotations

from typing import Any


def _score_completeness(completeness: float) -> float:
    return max(0.0, min(1.0, completeness))


def _score_earnings_stability(summary: dict[str, Any]) -> float:
    stat = summary.get("net_margin_stat") or {}
    mean, std = stat.get("mean"), stat.get("std")
    loss_years = summary.get("loss_years") or 0
    total = max(summary.get("total_years") or 1, 1)
    score = 1.0
    if mean is None or mean <= 0:
        return 0.15
    cv = (std or 0) / abs(mean)
    score -= min(0.6, cv * 0.8)          # 利润率波动越大越低
    score -= 0.4 * (loss_years / total)  # 亏损年份占比
    return max(0.0, score)


def _score_cashflow_stability(summary: dict[str, Any]) -> float:
    stat = summary.get("ocf_to_net_income_stat") or {}
    mean, std = stat.get("mean"), stat.get("std")
    neg_fcf = summary.get("negative_fcf_years") or 0
    total = max(summary.get("total_years") or 1, 1)
    if mean is None:
        return 0.3
    score = 1.0
    score -= min(0.5, abs(mean - 1.0) * 0.5)  # OCF/NI 偏离 1 越远越差
    score -= min(0.3, (std or 0) * 0.3)
    score -= 0.3 * (neg_fcf / total)
    return max(0.0, score)


def _score_model_fit(industry_caveat: str | None, fcff_applicable: bool) -> float:
    """行业与模型适配：金融类公司在 MVP 用通用模型 → 大幅降分。"""
    if industry_caveat and not fcff_applicable:
        return 0.25
    if industry_caveat:
        return 0.6
    return 0.9


def _score_accounting_complexity(latest: dict[str, Any], restatement_count: int) -> float:
    score = 1.0
    gw = latest.get("goodwill_to_equity")
    if gw is not None:
        score -= min(0.4, gw * 0.8)  # 商誉/净资产越高越复杂
    score -= min(0.3, restatement_count * 0.15)
    return max(0.0, score)


def _score_model_agreement(divergence: float | None) -> float:
    if divergence is None:
        return 0.5
    return max(0.0, 1.0 - divergence * 2.5)  # 分歧 40% 时归零


WEIGHTS = {
    "data_completeness": 0.20,
    "earnings_stability": 0.15,
    "cashflow_stability": 0.15,
    "model_fit": 0.15,
    "forecast_error": 0.15,
    "accounting_complexity": 0.10,
    "model_agreement": 0.10,
}


def confidence_score(
    completeness: float,
    summary: dict[str, Any],
    latest: dict[str, Any],
    divergence: float | None,
    terminal_value_share: float | None,
    industry_caveat: str | None,
    fcff_applicable: bool,
    restatement_count: int = 0,
) -> dict[str, Any]:
    factors = {
        "data_completeness": _score_completeness(completeness),
        "earnings_stability": _score_earnings_stability(summary),
        "cashflow_stability": _score_cashflow_stability(summary),
        "model_fit": _score_model_fit(industry_caveat, fcff_applicable),
        "forecast_error": 0.60,  # 回测体系上线前的中性值（方案阶段 4 后由真实误差替换）
        "accounting_complexity": _score_accounting_complexity(latest, restatement_count),
        "model_agreement": _score_model_agreement(divergence),
    }
    score = sum(factors[k] * WEIGHTS[k] for k in WEIGHTS) * 100.0

    # ---- 降低可信度的情形（方案第十一章清单）----
    reasons: list[str] = []
    if (summary.get("loss_years") or 0) >= 2:
        reasons.append("公司存在多个亏损年度")
    if terminal_value_share is not None and terminal_value_share > 0.70:
        reasons.append(f"DCF 终值占比 {terminal_value_share:.0%}，估值高度依赖远期假设")
    if divergence is not None and divergence > 0.25:
        reasons.append(f"不同模型估值分歧 {divergence:.0%}，超过 25%")
    ocf_ni = (summary.get("ocf_to_net_income_stat") or {}).get("mean")
    if ocf_ni is not None and ocf_ni < 0.6:
        reasons.append("经营现金流长期显著低于净利润")
    dilution = summary.get("share_dilution_cagr")
    if dilution is not None and dilution > 0.02:
        reasons.append(f"股本以年均 {dilution:.1%} 持续稀释")
    gw = latest.get("goodwill_to_equity")
    if gw is not None and gw > 0.3:
        reasons.append(f"商誉/净资产 {gw:.0%}，会计复杂度高")
    if restatement_count > 0:
        reasons.append(f"存在 {restatement_count} 次财务报告重述")
    if industry_caveat:
        reasons.append(industry_caveat)

    return {
        "score": round(score, 1),
        "factors": {k: round(v, 3) for k, v in factors.items()},
        "weights": WEIGHTS,
        "reasons": reasons,
    }
