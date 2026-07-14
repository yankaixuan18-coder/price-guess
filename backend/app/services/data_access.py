"""数据访问辅助：时点查询（point-in-time）、汇率换算、行情与股本快照。

时点原则（方案 2.4）：任何 as_of 日期的查询只返回 effective_at <= as_of 的财务数据，
同一财年取 revision_version 最大的一版（更正后的官方报告优先，方案 15.3）。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import (
    Company,
    DailyPrice,
    Dividend,
    FinancialFactsCanonical,
    FinancialPeriod,
    FxRate,
    InterestRate,
    Listing,
    PeerLink,
    Security,
    ShareCount,
)
from app.services import metrics as metrics_svc


def get_company(db: Session, company_id: str) -> Company | None:
    return db.get(Company, company_id)


def get_primary_listing(db: Session, company_id: str) -> Listing | None:
    return (
        db.query(Listing)
        .join(Security, Listing.security_id == Security.security_id)
        .filter(Security.company_id == company_id)
        .order_by(Listing.is_primary.desc())
        .first()
    )


def get_listings(db: Session, company_id: str) -> list[Listing]:
    return (
        db.query(Listing)
        .join(Security, Listing.security_id == Security.security_id)
        .filter(Security.company_id == company_id)
        .all()
    )


def fx_to_cny(db: Session, currency: str, as_of: date) -> float:
    if currency == "CNY":
        return 1.0
    row = (
        db.query(FxRate)
        .filter(FxRate.currency == currency, FxRate.rate_date <= as_of)
        .order_by(FxRate.rate_date.desc())
        .first()
    )
    if row is None:
        raise ValueError(f"缺少 {currency} 兑 CNY 汇率（as_of {as_of}）")
    return row.rate_to_cny


def fx_convert(db: Session, amount: float, from_ccy: str, to_ccy: str, as_of: date) -> float:
    if from_ccy == to_ccy:
        return amount
    return amount * fx_to_cny(db, from_ccy, as_of) / fx_to_cny(db, to_ccy, as_of)


def latest_price(db: Session, listing_id: str, as_of: date) -> DailyPrice | None:
    return (
        db.query(DailyPrice)
        .filter(DailyPrice.listing_id == listing_id, DailyPrice.trade_date <= as_of)
        .order_by(DailyPrice.trade_date.desc())
        .first()
    )


def price_series(db: Session, listing_id: str, until: date | None = None) -> list[DailyPrice]:
    q = db.query(DailyPrice).filter(DailyPrice.listing_id == listing_id)
    if until:
        q = q.filter(DailyPrice.trade_date <= until)
    return q.order_by(DailyPrice.trade_date).all()


def latest_share_count(db: Session, company_id: str, as_of: date) -> ShareCount | None:
    return (
        db.query(ShareCount)
        .filter(ShareCount.company_id == company_id, ShareCount.as_of <= as_of)
        .order_by(ShareCount.as_of.desc())
        .first()
    )


def risk_free_rate(db: Session, market: str, as_of: date) -> float:
    row = (
        db.query(InterestRate)
        .filter(InterestRate.market == market, InterestRate.rate_date <= as_of)
        .order_by(InterestRate.rate_date.desc())
        .first()
    )
    if row is None:
        # 缺数据时使用保守默认值
        return {"CN": 0.023, "US": 0.042, "HK": 0.037}.get(market, 0.03)
    return row.rate


def annual_periods_asof(db: Session, company_id: str, as_of: date) -> list[FinancialPeriod]:
    """时点可用的年报期：effective_at <= as_of，每财年取最大修订版。"""
    sub = (
        db.query(
            FinancialPeriod.fiscal_year.label("fy"),
            func.max(FinancialPeriod.revision_version).label("maxrev"),
        )
        .filter(
            FinancialPeriod.company_id == company_id,
            FinancialPeriod.period_type == "FY",
            FinancialPeriod.effective_at <= as_of,
        )
        .group_by(FinancialPeriod.fiscal_year)
        .subquery()
    )
    return (
        db.query(FinancialPeriod)
        .join(sub, and_(
            FinancialPeriod.fiscal_year == sub.c.fy,
            FinancialPeriod.revision_version == sub.c.maxrev,
        ))
        .filter(
            FinancialPeriod.company_id == company_id,
            FinancialPeriod.period_type == "FY",
            FinancialPeriod.effective_at <= as_of,
        )
        .order_by(FinancialPeriod.fiscal_year)
        .all()
    )


def dividends_by_year(db: Session, company_id: str) -> dict[int, float]:
    rows = db.query(Dividend).filter(Dividend.company_id == company_id).all()
    return {r.fiscal_year: r.dps for r in rows}


def build_metric_rows(db: Session, company_id: str, as_of: date) -> list[dict[str, Any]]:
    """构造逐年指标输入行（含股本与分红）。"""
    periods = annual_periods_asof(db, company_id, as_of)
    dps_map = dividends_by_year(db, company_id)
    rows: list[dict[str, Any]] = []
    for p in periods:
        if p.facts is None:
            continue
        sc = latest_share_count(db, company_id, p.period_end)
        rows.append(metrics_svc.year_row(
            fiscal_year=p.fiscal_year,
            facts=p.facts,
            diluted_shares=(sc.diluted_weighted_shares or sc.total_shares) if sc else None,
            total_shares=sc.total_shares if sc else None,
            dps=dps_map.get(p.fiscal_year),
        ))
    return rows


def facts_asof(db: Session, company_id: str, as_of: date) -> tuple[FinancialPeriod, FinancialFactsCanonical] | None:
    """as_of 时点最新可用年报。"""
    periods = annual_periods_asof(db, company_id, as_of)
    for p in reversed(periods):
        if p.facts is not None:
            return p, p.facts
    return None


def peer_company_ids(db: Session, company_id: str) -> list[tuple[str, str | None]]:
    rows = db.query(PeerLink).filter(PeerLink.company_id == company_id).all()
    return [(r.peer_company_id, r.rule) for r in rows]


# ---------------------------------------------------------------------------
# 市场快照与倍数
# ---------------------------------------------------------------------------

def market_snapshot(db: Session, company_id: str, as_of: date) -> dict[str, Any] | None:
    """当前价格、市值、净债务、汇率快照（估值与倍数计算的公共输入）。

    金额统一为报告币种（百万）；每股数据同时给出交易币种。
    """
    company = get_company(db, company_id)
    listing = get_primary_listing(db, company_id)
    if company is None or listing is None:
        return None
    px = latest_price(db, listing.listing_id, as_of)
    sc = latest_share_count(db, company_id, as_of)
    pair = facts_asof(db, company_id, as_of)
    if px is None or sc is None or pair is None:
        return None
    period, facts = pair
    report_ccy = company.report_currency
    trading_ccy = listing.trading_currency
    fx = fx_to_cny(db, trading_ccy, as_of) / fx_to_cny(db, report_ccy, as_of)  # 1 交易币 = ? 报告币
    price_report_ccy = px.close * fx
    market_cap = price_report_ccy * sc.total_shares  # 报告币种，百万
    from app.services import standardize as std

    nd = std.net_debt(facts)
    ev = market_cap + nd + (facts.minority_interest or 0.0) + (facts.preferred_equity or 0.0)
    return {
        "as_of": as_of.isoformat(),
        "listing_id": listing.listing_id,
        "ticker": listing.ticker,
        "market": listing.market,
        "price": px.close,
        "price_date": px.trade_date.isoformat(),
        "trading_currency": trading_ccy,
        "report_currency": report_ccy,
        "fx_trading_to_report": fx,
        "price_report_ccy": price_report_ccy,
        "total_shares": sc.total_shares,
        "diluted_shares": sc.diluted_weighted_shares or sc.total_shares,
        "market_cap": market_cap,
        "net_debt": nd,
        "enterprise_value": ev,
        "latest_period": {
            "fiscal_year": period.fiscal_year,
            "period_end": period.period_end.isoformat(),
            "published_at": period.published_at.isoformat() if period.published_at else None,
            "quality_grade": period.quality_grade,
            "accounting_standard": period.accounting_standard,
            "period_id": period.id,
        },
    }


def current_multiples(db: Session, company_id: str, as_of: date) -> dict[str, Any] | None:
    """当前 PE/PB/EV-EBITDA/股息率/FCF 收益率。"""
    snap = market_snapshot(db, company_id, as_of)
    if snap is None:
        return None
    pair = facts_asof(db, company_id, as_of)
    assert pair is not None
    _, f = pair
    from app.services import standardize as std

    calibers = std.profit_calibers(f)
    ebitda = std.ebitda(f)
    mcap, ev = snap["market_cap"], snap["enterprise_value"]
    fcf = None
    if f.cash_flow_from_operations is not None:
        fcf = f.cash_flow_from_operations - (f.capital_expenditure or 0.0)
    dps_map = dividends_by_year(db, company_id)
    latest_dps = dps_map.get(max(dps_map)) if dps_map else None
    div_yield = None
    if latest_dps is not None and snap["price_report_ccy"] > 0:
        div_yield = latest_dps / snap["price_report_ccy"]
    return {
        "pe": mcap / calibers.normalized if calibers.normalized and calibers.normalized > 0 else None,
        "pe_reported": mcap / calibers.reported if calibers.reported and calibers.reported > 0 else None,
        "pb": mcap / f.shareholders_equity if f.shareholders_equity and f.shareholders_equity > 0 else None,
        "ev_ebitda": ev / ebitda if ebitda and ebitda > 0 else None,
        "ps": mcap / f.revenue if f.revenue and f.revenue > 0 else None,
        "dividend_yield": div_yield,
        "fcf_yield": fcf / mcap if fcf is not None and mcap > 0 else None,
        "market_cap": mcap,
        "enterprise_value": ev,
    }


def historical_multiple_series(db: Session, company_id: str, as_of: date) -> dict[str, list[dict[str, Any]]]:
    """历史 PE/PB/EV-EBITDA 序列（时点口径：每个价格日只用当时已披露的年报）。"""
    listing = get_primary_listing(db, company_id)
    company = get_company(db, company_id)
    if listing is None or company is None:
        return {"pe": [], "pb": [], "ev_ebitda": []}
    prices = price_series(db, listing.listing_id, until=as_of)
    periods = annual_periods_asof(db, company_id, as_of)
    if not prices or not periods:
        return {"pe": [], "pb": [], "ev_ebitda": []}
    from app.services import standardize as std

    out: dict[str, list[dict[str, Any]]] = {"pe": [], "pb": [], "ev_ebitda": []}
    pi = 0
    usable: FinancialPeriod | None = None
    for px in prices:
        while pi < len(periods) and periods[pi].effective_at and periods[pi].effective_at <= px.trade_date:
            usable = periods[pi]
            pi += 1
        if usable is None or usable.facts is None:
            continue
        f = usable.facts
        sc = latest_share_count(db, company_id, px.trade_date)
        if sc is None:
            continue
        try:
            fx = (
                fx_to_cny(db, listing.trading_currency, px.trade_date)
                / fx_to_cny(db, company.report_currency, px.trade_date)
            )
        except ValueError:
            continue
        mcap = px.close * fx * sc.total_shares
        d = px.trade_date.isoformat()
        calibers = std.profit_calibers(f)
        if calibers.normalized and calibers.normalized > 0:
            out["pe"].append({"date": d, "value": mcap / calibers.normalized})
        if f.shareholders_equity and f.shareholders_equity > 0:
            out["pb"].append({"date": d, "value": mcap / f.shareholders_equity})
        ebitda = std.ebitda(f)
        if ebitda and ebitda > 0:
            ev = mcap + std.net_debt(f) + (f.minority_interest or 0.0) + (f.preferred_equity or 0.0)
            out["ev_ebitda"].append({"date": d, "value": ev / ebitda})
    return out
