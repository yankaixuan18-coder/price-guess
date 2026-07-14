"""筛选器、公司对比、自选股、提醒（方案 12.5/12.6/17）。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, Company, ValuationRun, WatchlistItem
from app.schemas import WatchlistAddRequest
from app.services import data_access as da
from app.services import metrics as metrics_svc
from app.services.alerts import evaluate_alerts

router = APIRouter(tags=["tools"])


def _latest_run(db: Session, company_id: str) -> ValuationRun | None:
    return (
        db.query(ValuationRun)
        .filter(ValuationRun.company_id == company_id)
        .order_by(ValuationRun.created_at.desc())
        .first()
    )


def _screen_row(db: Session, c: Company, asof: date) -> dict | None:
    mult = da.current_multiples(db, c.company_id, asof)
    listing = da.get_primary_listing(db, c.company_id)
    run = _latest_run(db, c.company_id)
    fusion = (run.summary or {}).get("fusion", {}) if run else {}
    confidence = (run.summary or {}).get("confidence", {}) if run else {}
    rows = da.build_metric_rows(db, c.company_id, asof)
    annual = metrics_svc.compute_annual_metrics(rows)
    summary = metrics_svc.compute_summary(rows, annual)
    latest = summary.get("latest") or {}
    return {
        "company_id": c.company_id,
        "name_zh": c.name_zh,
        "industry_code": c.industry_code,
        "industry_name": c.industry_name,
        "market": listing.market if listing else None,
        "ticker": listing.ticker if listing else None,
        "pe": (mult or {}).get("pe"),
        "pb": (mult or {}).get("pb"),
        "ev_ebitda": (mult or {}).get("ev_ebitda"),
        "dividend_yield": (mult or {}).get("dividend_yield"),
        "fcf_yield": (mult or {}).get("fcf_yield"),
        "roe": latest.get("roe"),
        "roic": latest.get("roic"),
        "revenue_cagr_3y": summary.get("revenue_cagr_3y"),
        "upside": fusion.get("upside"),
        "safety_margin": fusion.get("safety_margin"),
        "fair_value_trading_ccy": fusion.get("weighted_fair_value_trading_ccy"),
        "price_used": run.price_used if run else None,
        "confidence": confidence.get("score"),
        "valuation_date": run.valuation_date if run else None,
    }


@router.get("/screeners")
def screener(
    market: str | None = None,
    industry: str | None = None,
    min_upside: float | None = Query(default=None, description="最低上行空间，如 0.2"),
    max_pe: float | None = None,
    min_roe: float | None = None,
    min_confidence: float | None = None,
    as_of: date | None = None,
    db: Session = Depends(get_db),
):
    """估值筛选器。注意：低估 ≠ 买入信号，结果与质量/风险维度分列（方案 2.3）。"""
    asof = as_of or date.today()
    out = []
    for c in db.query(Company).all():
        row = _screen_row(db, c, asof)
        if row is None:
            continue
        if market and row["market"] != market:
            continue
        if industry and row["industry_code"] != industry:
            continue
        if min_upside is not None and (row["upside"] is None or row["upside"] < min_upside):
            continue
        if max_pe is not None and (row["pe"] is None or row["pe"] > max_pe):
            continue
        if min_roe is not None and (row["roe"] is None or row["roe"] < min_roe):
            continue
        if min_confidence is not None and (row["confidence"] is None or row["confidence"] < min_confidence):
            continue
        out.append(row)
    out.sort(key=lambda r: (r["upside"] is None, -(r["upside"] or 0)))
    return {"count": len(out), "items": out,
            "note": "估值吸引力与公司质量/风险为独立维度，低估不等于买入信号（方案 2.3）"}


@router.get("/compare")
def compare_companies(
    ids: str = Query(description="逗号分隔的 company_id，最多 10 家"),
    as_of: date | None = None,
    db: Session = Depends(get_db),
):
    """公司对比（方案 12.5）：财务质量/增长/估值/资本回报/杠杆/现金流/股东回报。"""
    company_ids = [x.strip() for x in ids.split(",") if x.strip()][:10]
    asof = as_of or date.today()
    items = []
    for cid in company_ids:
        c = da.get_company(db, cid)
        if c is None:
            continue
        row = _screen_row(db, c, asof)
        rows = da.build_metric_rows(db, cid, asof)
        annual = metrics_svc.compute_annual_metrics(rows)
        summary = metrics_svc.compute_summary(rows, annual)
        latest = summary.get("latest") or {}
        row.update({
            "gross_margin": latest.get("gross_margin"),
            "net_margin": latest.get("net_margin"),
            "ocf_to_net_income": latest.get("ocf_to_net_income"),
            "net_debt_to_ebitda": latest.get("net_debt_to_ebitda"),
            "payout_ratio": latest.get("payout_ratio"),
            "share_dilution_cagr": summary.get("share_dilution_cagr"),
            "net_income_cagr_3y": summary.get("net_income_cagr_3y"),
        })
        items.append(row)
    return {"count": len(items), "items": items}


# ---------------------------- 自选股 ----------------------------

@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).order_by(WatchlistItem.added_at).all()
    out = []
    for w in items:
        c = da.get_company(db, w.company_id)
        row = _screen_row(db, c, date.today()) if c else None
        out.append({
            "company_id": w.company_id,
            "note": w.note,
            "target_margin_of_safety": w.target_margin_of_safety,
            "added_at": w.added_at.isoformat(),
            "snapshot": row,
        })
    return {"count": len(out), "items": out}


@router.post("/watchlist")
def add_watchlist(req: WatchlistAddRequest, db: Session = Depends(get_db)):
    if da.get_company(db, req.company_id) is None:
        raise HTTPException(404, "公司不存在")
    exists = db.query(WatchlistItem).filter(WatchlistItem.company_id == req.company_id).first()
    if exists:
        exists.note = req.note or exists.note
        exists.target_margin_of_safety = req.target_margin_of_safety
    else:
        db.add(WatchlistItem(
            company_id=req.company_id, note=req.note,
            target_margin_of_safety=req.target_margin_of_safety,
        ))
    db.commit()
    return {"ok": True}


@router.delete("/watchlist/{company_id}")
def remove_watchlist(company_id: str, db: Session = Depends(get_db)):
    n = db.query(WatchlistItem).filter(WatchlistItem.company_id == company_id).delete()
    db.commit()
    if n == 0:
        raise HTTPException(404, "不在自选股中")
    return {"ok": True}


# ---------------------------- 提醒 ----------------------------

@router.get("/alerts")
def get_alerts(refresh: bool = False, db: Session = Depends(get_db)):
    """估值提醒（方案 12.6）。refresh=true 时重新评估全部规则。"""
    if refresh:
        evaluate_alerts(db)
    rows = (
        db.query(Alert)
        .filter(Alert.status == "active")
        .order_by(Alert.triggered_at.desc())
        .all()
    )
    out = []
    for a in rows:
        c = da.get_company(db, a.company_id)
        out.append({
            "id": a.id, "company_id": a.company_id,
            "company_name": c.name_zh if c else a.company_id,
            "rule": a.rule, "severity": a.severity, "message": a.message,
            "payload": a.payload, "triggered_at": a.triggered_at.isoformat(),
        })
    return {"count": len(out), "items": out}


@router.get("/industries")
def list_industries():
    """行业估值模板配置（方案第九章 industry_model_config）。"""
    from app.services.valuation.industry_config import INDUSTRY_CONFIGS

    return {
        "items": [
            {
                "industry_code": cfg.industry_code,
                "industry_name": cfg.industry_name,
                "primary_models": cfg.primary_models,
                "model_weight": cfg.model_weight,
                "terminal_growth_limit": cfg.terminal_growth_limit,
                "wacc_range": list(cfg.wacc_range),
                "exit_ev_ebitda_hint": cfg.exit_ev_ebitda_hint,
                "caveat": cfg.caveat,
            }
            for cfg in INDUSTRY_CONFIGS.values()
        ]
    }
