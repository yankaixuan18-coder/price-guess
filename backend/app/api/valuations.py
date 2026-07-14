"""估值执行与查询接口（方案第十七章）。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScenarioTemplate, ValuationRun
from app.schemas import ScenarioSaveRequest, ValuationRunRequest
from app.services import data_access as da
from app.services.valuation.engine import ValuationError, run_valuation

router = APIRouter(tags=["valuations"])


@router.post("/valuations/run")
def run_valuation_api(req: ValuationRunRequest, db: Session = Depends(get_db)):
    """执行估值。输出包含估值结果、输入参数、财务数据版本、股本、汇率、

    模型版本、风险提示、敏感性与完整计算日志（方案 17 输出要求）。
    """
    overrides = req.normalized_overrides()
    if req.scenario_template_id:
        tpl = db.get(ScenarioTemplate, req.scenario_template_id)
        if tpl is None:
            raise HTTPException(404, "假设版本不存在")
        merged = {k: dict(v) for k, v in tpl.assumptions.items()}
        for k, v in (overrides or {}).items():
            merged.setdefault(k, {}).update(v)
        overrides = merged
    try:
        return run_valuation(
            db,
            company_id=req.company_id,
            valuation_date=req.valuation_date or date.today(),
            overrides=overrides,
            models=req.models,
            save=req.save,
        )
    except ValuationError as e:
        raise HTTPException(422, str(e))


@router.post("/valuations/scenarios")
def save_scenario(req: ScenarioSaveRequest, db: Session = Depends(get_db)):
    """保存一套假设版本，供复用与版本比较（方案 7.2）。"""
    if da.get_company(db, req.company_id) is None:
        raise HTTPException(404, "公司不存在")
    tpl = ScenarioTemplate(
        company_id=req.company_id, name=req.name,
        assumptions=req.assumptions, note=req.note,
    )
    db.add(tpl)
    db.commit()
    return {"id": tpl.id, "company_id": tpl.company_id, "name": tpl.name}


@router.get("/valuations/scenarios/{company_id}")
def list_scenarios(company_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(ScenarioTemplate)
        .filter(ScenarioTemplate.company_id == company_id)
        .order_by(ScenarioTemplate.created_at.desc())
        .all()
    )
    return {
        "items": [
            {"id": r.id, "name": r.name, "assumptions": r.assumptions,
             "note": r.note, "created_at": r.created_at.isoformat()}
            for r in rows
        ]
    }


@router.get("/valuations/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    """按 run_id 取完整估值记录（可复现审计，方案 13.5）。"""
    run = db.get(ValuationRun, run_id)
    if run is None:
        raise HTTPException(404, "估值记录不存在")
    return {
        "run_id": run.run_id,
        "company_id": run.company_id,
        "valuation_date": run.valuation_date,
        "model_version": run.model_version,
        "price_used": run.price_used,
        "price_currency": run.price_currency,
        "shares_diluted_used": run.shares_diluted_used,
        "data_snapshot": run.data_snapshot,
        "summary": run.summary,
        "inputs": [
            {"scenario": i.scenario, "param": i.param_name, "value": i.param_value, "source": i.source}
            for i in run.inputs
        ],
        "outputs": [
            {"model": o.model_name, "scenario": o.scenario,
             "value_per_share": o.value_per_share,
             "value_per_share_trading_ccy": o.value_per_share_trading_ccy,
             "detail": o.detail, "warnings": o.warnings}
            for o in run.outputs
        ],
        "sensitivity": [s.matrix for s in run.sensitivities],
        "calculation_log": [
            {"seq": entry.seq, "step": entry.step, "message": entry.message, "data": entry.data}
            for entry in sorted(run.logs, key=lambda x: x.seq)
        ],
        "created_at": run.created_at.isoformat(),
    }


@router.get("/companies/{company_id}/valuation/latest")
def latest_valuation(company_id: str, db: Session = Depends(get_db)):
    run = (
        db.query(ValuationRun)
        .filter(ValuationRun.company_id == company_id)
        .order_by(ValuationRun.created_at.desc())
        .first()
    )
    if run is None:
        raise HTTPException(404, "尚无估值记录，请先 POST /valuations/run")
    return get_run(run.run_id, db)


@router.get("/companies/{company_id}/valuation/history")
def valuation_history(company_id: str, db: Session = Depends(get_db)):
    """估值档案：追踪估值变化及其原因（方案 1.1 第 8 条）。"""
    runs = (
        db.query(ValuationRun)
        .filter(ValuationRun.company_id == company_id)
        .order_by(ValuationRun.created_at.desc())
        .all()
    )
    return {
        "company_id": company_id,
        "items": [
            {
                "run_id": r.run_id, "valuation_date": r.valuation_date,
                "created_at": r.created_at.isoformat(),
                "price_used": r.price_used, "price_currency": r.price_currency,
                "fair_value_trading_ccy": (r.summary or {}).get("fusion", {}).get("weighted_fair_value_trading_ccy"),
                "upside": (r.summary or {}).get("fusion", {}).get("upside"),
                "confidence": (r.summary or {}).get("confidence", {}).get("score"),
                "model_version": r.model_version,
            }
            for r in runs
        ],
    }


@router.get("/companies/{company_id}/reverse-dcf")
def reverse_dcf(company_id: str, as_of: date | None = None, db: Session = Depends(get_db)):
    """反向 DCF（方案 8.7/12.4）：不落库的即时计算。"""
    try:
        report = run_valuation(db, company_id, as_of or date.today(), save=False)
    except ValuationError as e:
        raise HTTPException(422, str(e))
    if report.get("reverse_dcf") is None:
        raise HTTPException(422, "该公司行业不适用 FCFF/反向 DCF")
    return {
        "company_id": company_id,
        "company_name": report["company_name"],
        "market_snapshot": report["market_snapshot"],
        "reverse_dcf": report["reverse_dcf"],
        "base_assumptions": report["assumptions"]["base"],
    }
