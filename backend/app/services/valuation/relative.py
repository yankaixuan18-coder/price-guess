"""相对估值（方案 8.5）：PE / PB / EV-EBITDA + 历史估值分位。

原则：可比公司不能只按行业代码选择；目标倍数使用同行中位数并做
质量调整（PB 按 ROE 相对水平调整、PE 按盈利稳定性截尾），
输出完整对比表而非只给单一倍数（"输出经过质量和增长调整的可比估值"）。
"""
from __future__ import annotations

import statistics
from bisect import bisect_left
from typing import Any


def median(vals: list[float]) -> float | None:
    clean = [v for v in vals if v is not None and v > 0]
    return statistics.median(clean) if clean else None


def percentile_rank(history: list[float], current: float | None) -> float | None:
    """当前值在历史序列中的分位（0-1）。"""
    clean = sorted(v for v in history if v is not None and v > 0)
    if current is None or current <= 0 or len(clean) < 8:
        return None
    idx = bisect_left(clean, current)
    return idx / len(clean)


def quantiles(history: list[float]) -> dict[str, float] | None:
    clean = sorted(v for v in history if v is not None and v > 0)
    if len(clean) < 8:
        return None
    def q(p: float) -> float:
        i = min(int(p * (len(clean) - 1)), len(clean) - 1)
        return clean[i]
    return {"p10": q(0.10), "p25": q(0.25), "p50": q(0.50), "p75": q(0.75), "p90": q(0.90)}


def relative_pe(
    eps_normalized: float,
    peer_pes: list[float],
    hist_pes: list[float],
    scenario_shift: float = 0.0,
) -> dict[str, Any]:
    """PE 估值：目标倍数 = 同行中位数与自身历史中位数的均值（可得性回退）。

    scenario_shift：情景对倍数的调整（悲观取低位 -20%，乐观取高位 +20%，方案 7.2 估值倍数行）。
    """
    warnings: list[str] = []
    if eps_normalized <= 0:
        return {"applicable": False, "reason": "标准化 EPS 为负，PE 不适用", "warnings": ["公司亏损，PE 模型跳过"]}
    peer_med = median(peer_pes)
    hist_q = quantiles(hist_pes)
    hist_med = hist_q["p50"] if hist_q else None
    candidates = [v for v in (peer_med, hist_med) if v is not None]
    if not candidates:
        return {"applicable": False, "reason": "缺少同行与历史 PE 数据", "warnings": ["无可用目标倍数"]}
    target = statistics.fmean(candidates) * (1.0 + scenario_shift)
    if peer_med and hist_med and abs(peer_med - hist_med) / hist_med > 0.6:
        warnings.append(f"同行中位 PE {peer_med:.1f} 与自身历史中位 {hist_med:.1f} 差异较大")
    return {
        "applicable": True,
        "target_multiple": target,
        "peer_median": peer_med,
        "history_quantiles": hist_q,
        "value_per_share": eps_normalized * target,
        "basis": "eps_normalized",
        "warnings": warnings,
    }


def relative_pb(
    bvps: float,
    roe: float | None,
    peer_pbs: list[float],
    peer_roes: list[float],
    hist_pbs: list[float],
    scenario_shift: float = 0.0,
) -> dict[str, Any]:
    """PB 估值：目标 PB = 同行中位 PB × (公司 ROE / 同行中位 ROE)，系数截断在 [0.5, 2.0]。"""
    warnings: list[str] = []
    if bvps <= 0:
        return {"applicable": False, "reason": "每股净资产为负", "warnings": ["净资产为负，PB 不适用"]}
    peer_med = median(peer_pbs)
    hist_q = quantiles(hist_pbs)
    hist_med = hist_q["p50"] if hist_q else None
    quality_factor = 1.0
    peer_roe_med = median([r for r in peer_roes if r is not None])
    if roe is not None and peer_roe_med and peer_roe_med > 0:
        quality_factor = max(0.5, min(2.0, roe / peer_roe_med))
    candidates = []
    if peer_med is not None:
        candidates.append(peer_med * quality_factor)
    if hist_med is not None:
        candidates.append(hist_med)
    if not candidates:
        return {"applicable": False, "reason": "缺少同行与历史 PB 数据", "warnings": ["无可用目标倍数"]}
    target = statistics.fmean(candidates) * (1.0 + scenario_shift)
    return {
        "applicable": True,
        "target_multiple": target,
        "peer_median": peer_med,
        "roe_quality_factor": quality_factor,
        "history_quantiles": hist_q,
        "value_per_share": bvps * target,
        "basis": "bvps",
        "warnings": warnings,
    }


def relative_ev_ebitda(
    ebitda: float,
    net_debt: float,
    minority_interest: float,
    preferred_equity: float,
    diluted_shares: float,
    peer_multiples: list[float],
    hist_multiples: list[float],
    scenario_shift: float = 0.0,
) -> dict[str, Any]:
    """EV/EBITDA 估值：fair EV = EBITDA × 目标倍数，再桥接回股权价值。"""
    warnings: list[str] = []
    if ebitda <= 0:
        return {"applicable": False, "reason": "EBITDA 为负", "warnings": ["EBITDA 为负，EV/EBITDA 不适用"]}
    peer_med = median(peer_multiples)
    hist_q = quantiles(hist_multiples)
    hist_med = hist_q["p50"] if hist_q else None
    candidates = [v for v in (peer_med, hist_med) if v is not None]
    if not candidates:
        return {"applicable": False, "reason": "缺少同行与历史倍数", "warnings": ["无可用目标倍数"]}
    target = statistics.fmean(candidates) * (1.0 + scenario_shift)
    ev = ebitda * target
    equity = ev - net_debt - minority_interest - preferred_equity
    if equity <= 0:
        warnings.append("EV 扣除净债务后股权价值为负")
    return {
        "applicable": True,
        "target_multiple": target,
        "peer_median": peer_med,
        "history_quantiles": hist_q,
        "enterprise_value": ev,
        "equity_value": equity,
        "value_per_share": equity / diluted_shares if diluted_shares > 0 else None,
        "basis": "ebitda",
        "warnings": warnings,
    }
