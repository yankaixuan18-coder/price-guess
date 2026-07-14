"""估值监控与提醒规则（方案 12.6）。

触发条件（MVP 实现）：
- 股价进入合理价值区间（悲观值 ~ 基准值之间，或低于悲观值）；
- 安全边际超过自选股设定阈值；
- 相邻两次估值变化超过 10%；
- 数据质量检查未通过（财务指标异常）。
WACC 变化与增发/回购/分红事件提醒依赖阶段 2 数据管道，列入路线图。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Alert, QualityCheckResult, ValuationRun, WatchlistItem

VALUATION_CHANGE_THRESHOLD = 0.10


def evaluate_alerts(db: Session) -> list[Alert]:
    """重新评估全部自选股的提醒（幂等：清空 active 后重建）。"""
    db.query(Alert).filter(Alert.status == "active").delete()
    alerts: list[Alert] = []
    watchlist = db.query(WatchlistItem).all()
    for item in watchlist:
        runs = (
            db.query(ValuationRun)
            .filter(ValuationRun.company_id == item.company_id)
            .order_by(ValuationRun.created_at.desc())
            .limit(2)
            .all()
        )
        if runs:
            latest = runs[0]
            fusion = (latest.summary or {}).get("fusion", {})
            price = latest.price_used
            fair = fusion.get("weighted_fair_value_trading_ccy")
            pess = fusion.get("value_pessimistic_trading_ccy")
            mos = fusion.get("safety_margin")
            if price is not None and fair is not None:
                if pess is not None and price < pess:
                    alerts.append(Alert(
                        company_id=item.company_id, rule="price_below_pessimistic", severity="info",
                        message=f"现价 {price:.2f} 低于悲观情景价值 {pess:.2f}",
                        payload={"price": price, "pessimistic": pess},
                    ))
                elif price < fair:
                    alerts.append(Alert(
                        company_id=item.company_id, rule="price_in_value_range", severity="info",
                        message=f"现价 {price:.2f} 进入合理价值区间（合理价值 {fair:.2f}）",
                        payload={"price": price, "fair_value": fair},
                    ))
            if mos is not None and mos >= item.target_margin_of_safety:
                alerts.append(Alert(
                    company_id=item.company_id, rule="margin_of_safety_above_target", severity="info",
                    message=f"安全边际 {mos:.0%} 超过设定阈值 {item.target_margin_of_safety:.0%}",
                    payload={"safety_margin": mos, "target": item.target_margin_of_safety},
                ))
        if len(runs) == 2:
            f0 = (runs[1].summary or {}).get("fusion", {}).get("weighted_fair_value_trading_ccy")
            f1 = (runs[0].summary or {}).get("fusion", {}).get("weighted_fair_value_trading_ccy")
            if f0 and f1 and abs(f1 / f0 - 1.0) > VALUATION_CHANGE_THRESHOLD:
                alerts.append(Alert(
                    company_id=item.company_id, rule="valuation_change_gt_10pct", severity="warn",
                    message=f"合理价值由 {f0:.2f} 变为 {f1:.2f}（{f1 / f0 - 1.0:+.0%}），请核查假设或新财报影响",
                    payload={"previous": f0, "current": f1},
                ))
        issues = (
            db.query(QualityCheckResult)
            .filter(
                QualityCheckResult.company_id == item.company_id,
                QualityCheckResult.passed == 0,
                QualityCheckResult.severity == "risk",
            )
            .all()
        )
        for issue in issues:
            alerts.append(Alert(
                company_id=item.company_id, rule=f"quality:{issue.check_name}", severity="risk",
                message=issue.detail or issue.check_name,
            ))
    db.add_all(alerts)
    db.commit()
    return alerts
