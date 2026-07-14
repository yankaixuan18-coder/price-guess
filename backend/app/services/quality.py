"""数据质量控制（方案第十五章）。

每次数据导入后执行：
1. 财务报表勾稽（资产=负债+权益；现金流勾稽）；
2. 同比异常检查（收入、毛利率、股本、现金流背离、商誉、应收）；
异常数据不自动删除，写入 quality_check_results 供审核（15.2）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import FinancialFactsCanonical, FinancialPeriod, QualityCheckResult

# 勾稽允许的相对误差（结构化样例数据允许 2%，官方 XBRL 应收紧到 0.5%）
BALANCE_TOL = 0.02
CASH_TOL = 0.05


def check_balance_sheet(f: FinancialFactsCanonical) -> tuple[bool, str]:
    """资产 = 负债 + 所有者权益（含少数股东权益）。"""
    if f.total_assets is None or f.total_liabilities is None or f.shareholders_equity is None:
        return False, "缺少资产负债表关键科目，无法勾稽"
    rhs = f.total_liabilities + f.shareholders_equity + (f.minority_interest or 0.0) + (f.preferred_equity or 0.0)
    if f.total_assets == 0:
        return False, "总资产为 0"
    diff = abs(f.total_assets - rhs) / abs(f.total_assets)
    ok = diff <= BALANCE_TOL
    return ok, f"资产 {f.total_assets:,.0f} vs 负债+权益 {rhs:,.0f}，偏差 {diff:.2%}"


def check_cash_flow(prev: FinancialFactsCanonical | None, cur: FinancialFactsCanonical) -> tuple[bool, str]:
    """期初现金 + 经营 + 投资 + 融资 + 汇率影响 ≈ 期末现金。"""
    if prev is None or prev.cash_and_equivalents is None or cur.cash_and_equivalents is None:
        return True, "缺少期初现金，跳过现金流勾稽"
    flows = [cur.cash_flow_from_operations, cur.cash_flow_from_investing, cur.cash_flow_from_financing]
    if any(v is None for v in flows):
        return True, "缺少三大现金流科目，跳过"
    expected = prev.cash_and_equivalents + sum(v or 0.0 for v in flows) + (cur.fx_effect_on_cash or 0.0)
    base = max(abs(cur.cash_and_equivalents), 1.0)
    diff = abs(expected - cur.cash_and_equivalents) / base
    ok = diff <= CASH_TOL
    return ok, f"推算期末现金 {expected:,.0f} vs 实际 {cur.cash_and_equivalents:,.0f}，偏差 {diff:.2%}"


def check_yoy_anomalies(prev: FinancialFactsCanonical | None, cur: FinancialFactsCanonical) -> list[dict[str, Any]]:
    """同比异常（方案 15.2）。返回异常列表，不修改数据。"""
    issues: list[dict[str, Any]] = []
    if prev is None:
        return issues

    def _pct(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or b == 0:
            return None
        return a / b - 1.0

    rev_g = _pct(cur.revenue, prev.revenue)
    if rev_g is not None and abs(rev_g) > 2.0:
        issues.append({"check": "revenue_yoy_gt_200pct", "detail": f"收入同比 {rev_g:.0%}"})

    def _margin(f: FinancialFactsCanonical) -> float | None:
        if f.revenue in (None, 0) or f.gross_profit is None:
            return None
        return f.gross_profit / f.revenue

    m0, m1 = _margin(prev), _margin(cur)
    if m0 is not None and m1 is not None and abs(m1 - m0) > 0.30:
        issues.append({"check": "gross_margin_jump_30pp", "detail": f"毛利率 {m0:.1%} → {m1:.1%}"})

    if (cur.net_income or 0) > 0 and (cur.cash_flow_from_operations or 0) < 0 and (prev.cash_flow_from_operations or 0) < 0:
        issues.append({"check": "profit_positive_ocf_negative", "detail": "净利润为正但经营现金流连续为负"})

    gw = _pct(cur.goodwill, prev.goodwill)
    if gw is not None and gw > 0.5 and (cur.goodwill or 0) > 0.05 * (cur.total_assets or 1):
        issues.append({"check": "goodwill_spike", "detail": f"商誉同比 +{gw:.0%}"})

    ar_g = _pct(cur.accounts_receivable, prev.accounts_receivable)
    if ar_g is not None and rev_g is not None and ar_g - rev_g > 0.4:
        issues.append({"check": "ar_outgrow_revenue", "detail": f"应收增速超收入 {ar_g - rev_g:.0%}"})
    return issues


def run_quality_checks(db: Session, company_id: str) -> list[QualityCheckResult]:
    """对公司全部年报执行质量检查并落库。"""
    periods = (
        db.query(FinancialPeriod)
        .filter(FinancialPeriod.company_id == company_id, FinancialPeriod.period_type == "FY")
        .order_by(FinancialPeriod.fiscal_year)
        .all()
    )
    # 清理旧结果，重新生成
    db.query(QualityCheckResult).filter(QualityCheckResult.company_id == company_id).delete()
    results: list[QualityCheckResult] = []
    prev_facts: FinancialFactsCanonical | None = None
    for p in periods:
        f = p.facts
        if f is None:
            continue
        ok, msg = check_balance_sheet(f)
        results.append(QualityCheckResult(
            company_id=company_id, period_id=p.id, check_name="balance_sheet_identity",
            passed=1 if ok else 0, severity="warn" if ok else "risk", detail=msg,
        ))
        ok2, msg2 = check_cash_flow(prev_facts, f)
        results.append(QualityCheckResult(
            company_id=company_id, period_id=p.id, check_name="cash_flow_identity",
            passed=1 if ok2 else 0, severity="warn" if ok2 else "risk", detail=msg2,
        ))
        for issue in check_yoy_anomalies(prev_facts, f):
            results.append(QualityCheckResult(
                company_id=company_id, period_id=p.id, check_name=issue["check"],
                passed=0, severity="warn", detail=issue["detail"],
            ))
        prev_facts = f
    db.add_all(results)
    db.commit()
    return results
