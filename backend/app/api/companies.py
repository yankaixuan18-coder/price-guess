"""公司数据接口：搜索/详情/财务/指标/披露/同行/历史倍数。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, FinancialPeriod, Listing, QualityCheckResult, Security
from app.services import data_access as da
from app.services import metrics as metrics_svc

router = APIRouter(prefix="/companies", tags=["companies"])


def _asof(v: date | None) -> date:
    return v or date.today()


def _company_card(db: Session, c: Company) -> dict:
    listing = da.get_primary_listing(db, c.company_id)
    return {
        "company_id": c.company_id,
        "name_zh": c.name_zh,
        "name_en": c.name_en,
        "industry_code": c.industry_code,
        "industry_name": c.industry_name,
        "market": listing.market if listing else None,
        "ticker": listing.ticker if listing else None,
        "exchange": listing.exchange if listing else None,
        "trading_currency": listing.trading_currency if listing else None,
        "report_currency": c.report_currency,
    }


@router.get("/search")
def search_companies(
    q: str = Query(default="", description="名称/代码模糊搜索，空则返回全部"),
    market: str | None = None,
    industry: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Company)
    if industry:
        query = query.filter(Company.industry_code == industry)
    companies = query.all()
    out = []
    for c in companies:
        card = _company_card(db, c)
        if market and card["market"] != market:
            continue
        if q:
            needle = q.lower()
            hay = " ".join(filter(None, [c.name_zh, c.name_en or "", card["ticker"] or "", c.company_id])).lower()
            if needle not in hay:
                continue
        out.append(card)
    return {"count": len(out), "items": out}


@router.get("/{company_id}")
def company_overview(company_id: str, as_of: date | None = None, db: Session = Depends(get_db)):
    """公司总览（方案 12.1）：价格、市值、当前倍数、最新报告、质量提示、最新估值摘要。"""
    c = da.get_company(db, company_id)
    if c is None:
        raise HTTPException(404, "公司不存在")
    asof = _asof(as_of)
    card = _company_card(db, c)
    card["description"] = c.description
    card["beta"] = c.beta
    snap = da.market_snapshot(db, company_id, asof)
    multiples = da.current_multiples(db, company_id, asof)
    hist = da.historical_multiple_series(db, company_id, asof)
    from app.services.valuation import relative as rel

    percentiles = {}
    for key in ("pe", "pb", "ev_ebitda"):
        series = [p["value"] for p in hist[key]]
        cur = (multiples or {}).get(key)
        percentiles[key] = {
            "current": cur,
            "percentile": rel.percentile_rank(series, cur),
            "quantiles": rel.quantiles(series),
        }
    # 财务风险提示：未通过的质量检查
    issues = (
        db.query(QualityCheckResult)
        .filter(QualityCheckResult.company_id == company_id, QualityCheckResult.passed == 0)
        .order_by(QualityCheckResult.checked_at.desc())
        .limit(10)
        .all()
    )
    # 最新估值摘要
    from app.models import ValuationRun

    run = (
        db.query(ValuationRun)
        .filter(ValuationRun.company_id == company_id)
        .order_by(ValuationRun.created_at.desc())
        .first()
    )
    rows = da.build_metric_rows(db, company_id, asof)
    annual = metrics_svc.compute_annual_metrics(rows)
    summary = metrics_svc.compute_summary(rows, annual)
    latest = summary.get("latest") or {}
    return {
        "company": card,
        "market_snapshot": snap,
        "current_multiples": multiples,
        "multiple_percentiles": percentiles,
        "key_metrics": {
            "roe": latest.get("roe"), "roic": latest.get("roic"),
            "gross_margin": latest.get("gross_margin"), "net_margin": latest.get("net_margin"),
            "fcf": latest.get("fcf"), "net_debt": latest.get("net_debt"),
            "revenue_cagr_3y": summary.get("revenue_cagr_3y"),
            "net_income_cagr_3y": summary.get("net_income_cagr_3y"),
        },
        "risk_flags": [
            {"check": i.check_name, "detail": i.detail, "severity": i.severity} for i in issues
        ],
        "latest_valuation": (run.summary | {
            "run_id": run.run_id, "valuation_date": run.valuation_date,
            "created_at": run.created_at.isoformat(),
        }) if run and run.summary else None,
    }


@router.get("/{company_id}/financials")
def company_financials(company_id: str, as_of: date | None = None, db: Session = Depends(get_db)):
    """原始口径年报数据（统一科目宽表，方案 12.2 数据底座）。"""
    if da.get_company(db, company_id) is None:
        raise HTTPException(404, "公司不存在")
    periods = da.annual_periods_asof(db, company_id, _asof(as_of))
    items = []
    for p in periods:
        f = p.facts
        if f is None:
            continue
        fact_cols = {
            col.name: getattr(f, col.name)
            for col in f.__table__.columns
            if col.name not in ("id", "period_id")
        }
        items.append({
            "fiscal_year": p.fiscal_year,
            "period_end": p.period_end.isoformat(),
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "effective_at": p.effective_at.isoformat() if p.effective_at else None,
            "revision_version": p.revision_version,
            "accounting_standard": p.accounting_standard,
            "currency": p.currency,
            "quality_grade": p.quality_grade,
            "facts": fact_cols,
        })
    return {"company_id": company_id, "unit": "百万（报告币种）", "items": items}


@router.get("/{company_id}/metrics")
def company_metrics(company_id: str, as_of: date | None = None, db: Session = Depends(get_db)):
    """财务分析指标（方案第六章）：逐年 + 汇总。"""
    if da.get_company(db, company_id) is None:
        raise HTTPException(404, "公司不存在")
    rows = da.build_metric_rows(db, company_id, _asof(as_of))
    annual = metrics_svc.compute_annual_metrics(rows)
    summary = metrics_svc.compute_summary(rows, annual)
    return {"company_id": company_id, "annual": annual, "summary": summary}


@router.get("/{company_id}/filings")
def company_filings(company_id: str, db: Session = Depends(get_db)):
    """披露清单（MVP：年报期与版本；阶段 2 接入公告原文，方案 18）。"""
    if da.get_company(db, company_id) is None:
        raise HTTPException(404, "公司不存在")
    periods = (
        db.query(FinancialPeriod)
        .filter(FinancialPeriod.company_id == company_id)
        .order_by(FinancialPeriod.fiscal_year.desc(), FinancialPeriod.revision_version.desc())
        .all()
    )
    return {
        "company_id": company_id,
        "items": [
            {
                "fiscal_year": p.fiscal_year, "period_type": p.period_type,
                "period_end": p.period_end.isoformat(),
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "effective_at": p.effective_at.isoformat() if p.effective_at else None,
                "revision_version": p.revision_version,
                "accounting_standard": p.accounting_standard,
                "source": p.source, "quality_grade": p.quality_grade,
            }
            for p in periods
        ],
    }


@router.get("/{company_id}/peers")
def company_peers(company_id: str, as_of: date | None = None, db: Session = Depends(get_db)):
    """同行对比（方案 8.5：展示可比公司质量与增长，不只给行业中位数）。"""
    if da.get_company(db, company_id) is None:
        raise HTTPException(404, "公司不存在")
    from app.services.valuation.engine import _peer_data

    peer = _peer_data(db, company_id, _asof(as_of))
    self_mult = da.current_multiples(db, company_id, _asof(as_of))
    return {"company_id": company_id, "self": self_mult, "peers": peer["detail"]}


@router.get("/{company_id}/prices")
def company_prices(company_id: str, db: Session = Depends(get_db)):
    """主上市地价格序列（原始收盘价）。"""
    listing = da.get_primary_listing(db, company_id)
    if listing is None:
        raise HTTPException(404, "无上市信息")
    series = da.price_series(db, listing.listing_id)
    return {
        "listing_id": listing.listing_id,
        "currency": listing.trading_currency,
        "items": [{"date": p.trade_date.isoformat(), "close": p.close} for p in series],
    }


@router.get("/{company_id}/multiple-history")
def multiple_history(company_id: str, as_of: date | None = None, db: Session = Depends(get_db)):
    """历史 PE/PB/EV-EBITDA 序列与分位（方案 12.1 历史估值分位）。"""
    if da.get_company(db, company_id) is None:
        raise HTTPException(404, "公司不存在")
    return da.historical_multiple_series(db, company_id, _asof(as_of))
