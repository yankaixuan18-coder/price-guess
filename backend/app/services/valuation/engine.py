"""估值编排引擎：一次估值运行的全流程。

流程（方案第四章估值模型层 + 第十/十一章）：
  加载时点数据 → 生成/合并三情景假设 → 逐模型逐情景计算
  → 敏感性矩阵 → 反向 DCF → 行业权重融合 → 可信度评分
  → 以唯一 valuation_run_id 落库全部输入/输出/日志（可完整复现）。
"""
from __future__ import annotations

import statistics
import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    CalculationLog,
    Restatement,
    SensitivityResult,
    ValuationInput,
    ValuationOutput,
    ValuationRun,
)
from app.services import data_access as da
from app.services import forecast as fc
from app.services import metrics as metrics_svc
from app.services import standardize as std
from app.services.valuation import confidence as conf
from app.services.valuation import fusion as fusion_svc
from app.services.valuation import relative as rel
from app.services.valuation.fcff import FcffAssumptions, FcffBase, result_to_dict, run_fcff
from app.services.valuation.industry_config import (
    FCFF_EXCLUDED_INDUSTRIES,
    get_industry_config,
)
from app.services.valuation.reverse_dcf import reverse_dcf_report
from app.services.valuation.sensitivity import wacc_growth_matrix

SCENARIOS = ("pessimistic", "base", "optimistic")
DEFAULT_MODELS = ("fcff", "relative_pe", "relative_ev_ebitda", "relative_pb")


class ValuationError(Exception):
    pass


def _reinvestment_ratios(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """近三年 折旧摊销/收入、资本开支/收入、营运资本/收入。"""
    recent = rows[-3:]
    da_list, capex_list, wc_list = [], [], []
    for r in recent:
        f = r["facts"]
        if f.revenue:
            if f.depreciation_amortization is not None:
                da_list.append(f.depreciation_amortization / f.revenue)
            if f.capital_expenditure is not None:
                capex_list.append(f.capital_expenditure / f.revenue)
            if f.total_current_assets is not None and f.total_current_liabilities is not None:
                wc = (
                    f.total_current_assets
                    - (f.cash_and_equivalents or 0)
                    - (f.short_term_investments or 0)
                ) - (f.total_current_liabilities - (f.short_term_debt or 0))
                wc_list.append(wc / f.revenue)
    return {
        "da_pct": statistics.fmean(da_list) if da_list else None,
        "capex_pct": statistics.fmean(capex_list) if capex_list else None,
        "wc_pct": statistics.fmean(wc_list) if wc_list else None,
    }


def _peer_data(db: Session, company_id: str, as_of: date) -> dict[str, Any]:
    """同行当前倍数与质量指标（用于目标倍数与增长对照）。"""
    peers = da.peer_company_ids(db, company_id)
    data: dict[str, list] = {"pe": [], "pb": [], "ev_ebitda": [], "roe": [], "rev_growth": [], "detail": []}
    for pid, rule in peers:
        mult = da.current_multiples(db, pid, as_of)
        if mult is None:
            continue
        rows = da.build_metric_rows(db, pid, as_of)
        annual = metrics_svc.compute_annual_metrics(rows)
        summary = metrics_svc.compute_summary(rows, annual)
        latest = summary.get("latest") or {}
        pc = da.get_company(db, pid)
        data["pe"].append(mult.get("pe"))
        data["pb"].append(mult.get("pb"))
        data["ev_ebitda"].append(mult.get("ev_ebitda"))
        data["roe"].append(latest.get("roe"))
        data["rev_growth"].append(summary.get("revenue_cagr_3y"))
        data["detail"].append({
            "company_id": pid,
            "name": pc.name_zh if pc else pid,
            "rule": rule,
            "pe": mult.get("pe"), "pb": mult.get("pb"), "ev_ebitda": mult.get("ev_ebitda"),
            "roe": latest.get("roe"), "revenue_cagr_3y": summary.get("revenue_cagr_3y"),
        })
    return data


def run_valuation(
    db: Session,
    company_id: str,
    valuation_date: date,
    overrides: dict[str, dict[str, float]] | None = None,
    models: list[str] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """执行一次完整估值。返回完整报告 dict（与落库内容一致）。"""
    logs: list[tuple[str, str, dict | None]] = []

    def log(step: str, message: str, data: dict | None = None) -> None:
        logs.append((step, message, data))

    company = da.get_company(db, company_id)
    if company is None:
        raise ValuationError(f"公司不存在: {company_id}")
    industry = get_industry_config(company.industry_code)
    models = list(models or DEFAULT_MODELS)

    # ---- 1. 时点数据 ----
    snap = da.market_snapshot(db, company_id, valuation_date)
    if snap is None:
        raise ValuationError("缺少行情/股本/财务数据，无法估值")
    rows = da.build_metric_rows(db, company_id, valuation_date)
    if len(rows) < 2:
        raise ValuationError("历史年报不足 2 年，无法生成假设")
    annual = metrics_svc.compute_annual_metrics(rows)
    summary = metrics_svc.compute_summary(rows, annual)
    latest_annual = dict(summary["latest"])
    latest_facts = rows[-1]["facts"]
    ratios = _reinvestment_ratios(rows)
    latest_annual["da_pct"] = ratios["da_pct"]
    latest_annual["wc_pct"] = ratios["wc_pct"]
    if ratios["capex_pct"] is not None:
        latest_annual["capex_to_revenue"] = ratios["capex_pct"]
    log("load_data", f"载入 {len(rows)} 年年报，最新 FY{latest_annual['fiscal_year']}，"
        f"价格 {snap['price']} {snap['trading_currency']}（{snap['price_date']}）",
        {"period_id": snap["latest_period"]["period_id"]})

    # ---- 2. 三情景假设 ----
    rf = da.risk_free_rate(db, snap["market"], valuation_date)
    defaults = fc.default_assumptions(
        summary=summary, latest_annual=latest_annual, market=snap["market"],
        risk_free=rf, beta=company.beta, market_cap=snap["market_cap"],
        total_debt=std.total_debt(latest_facts), industry=industry,
    )
    wacc_detail = defaults.pop("_wacc_detail")
    assumptions, sources = fc.merge_overrides(defaults, overrides)
    log("assumptions", f"生成三情景假设（无风险利率 {rf:.2%}，CAPM WACC {wacc_detail['wacc']:.2%}）",
        {"wacc_detail": wacc_detail})

    # ---- 3. 模型基础输入 ----
    fcff_base = FcffBase(
        revenue=latest_facts.revenue,
        ebit_margin=latest_annual.get("ebit_margin") or 0.0,
        net_debt=snap["net_debt"],
        minority_interest=latest_facts.minority_interest or 0.0,
        preferred_equity=latest_facts.preferred_equity or 0.0,
        non_operating_assets=0.0,
        diluted_shares=snap["diluted_shares"],
    )
    peer = _peer_data(db, company_id, valuation_date)
    hist = da.historical_multiple_series(db, company_id, valuation_date)
    hist_pe = [p["value"] for p in hist["pe"]]
    hist_pb = [p["value"] for p in hist["pb"]]
    hist_ev = [p["value"] for p in hist["ev_ebitda"]]

    fcff_applicable = (
        "fcff" in models
        and company.industry_code not in FCFF_EXCLUDED_INDUSTRIES
        and latest_facts.revenue is not None
        and latest_annual.get("ebit_margin") is not None
    )
    if "fcff" in models and not fcff_applicable:
        log("model_skip", "FCFF 对该行业不适用，跳过（方案二十一风险 4：金融公司不套用普通 DCF）")

    # ---- 4. 逐模型逐情景 ----
    model_results: dict[str, dict[str, Any]] = {}
    model_values: dict[str, dict[str, float | None]] = {}
    all_warnings: list[str] = []
    base_fcff_assumptions: FcffAssumptions | None = None
    terminal_share: float | None = None

    for sc in SCENARIOS:
        a = assumptions[sc]
        if fcff_applicable:
            fa = FcffAssumptions(
                revenue_growth=[a["revenue_growth_5y"]] * int(a["forecast_years"]),
                terminal_ebit_margin=a["terminal_ebit_margin"],
                wacc=a["wacc"],
                terminal_growth=a["terminal_growth"],
                tax_rate=a["tax_rate"],
                da_pct_revenue=a["da_pct_revenue"],
                capex_pct_revenue=a["capex_pct_revenue"],
                wc_pct_revenue=a["wc_pct_revenue"],
                exit_ev_ebitda=industry.exit_ev_ebitda_hint,
            )
            try:
                r = run_fcff(fcff_base, fa)
                model_results.setdefault("fcff", {})[sc] = result_to_dict(r)
                model_values.setdefault("fcff", {})[sc] = r.value_per_share
                all_warnings.extend(f"[FCFF/{sc}] {w}" for w in r.warnings)
                if sc == "base":
                    base_fcff_assumptions = fa
                    terminal_share = r.terminal_value_share
            except ValueError as e:
                model_results.setdefault("fcff", {})[sc] = {"error": str(e)}
                model_values.setdefault("fcff", {})[sc] = None
                all_warnings.append(f"[FCFF/{sc}] {e}")

        shift = a.get("multiple_shift", 0.0)
        if "relative_pe" in models:
            eps = latest_annual.get("eps_normalized")
            r = rel.relative_pe(eps or -1.0, peer["pe"], hist_pe, shift)
            model_results.setdefault("relative_pe", {})[sc] = r
            model_values.setdefault("relative_pe", {})[sc] = r.get("value_per_share") if r.get("applicable") else None
        if "relative_ev_ebitda" in models:
            ebitda_v = latest_annual.get("ebitda")
            r = rel.relative_ev_ebitda(
                ebitda_v or -1.0, snap["net_debt"],
                latest_facts.minority_interest or 0.0, latest_facts.preferred_equity or 0.0,
                snap["diluted_shares"], peer["ev_ebitda"], hist_ev, shift,
            )
            model_results.setdefault("relative_ev_ebitda", {})[sc] = r
            model_values.setdefault("relative_ev_ebitda", {})[sc] = r.get("value_per_share") if r.get("applicable") else None
        if "relative_pb" in models:
            r = rel.relative_pb(
                latest_annual.get("bvps") or -1.0, latest_annual.get("roe"),
                peer["pb"], peer["roe"], hist_pb, shift,
            )
            model_results.setdefault("relative_pb", {})[sc] = r
            model_values.setdefault("relative_pb", {})[sc] = r.get("value_per_share") if r.get("applicable") else None
    log("models", f"完成模型计算: {sorted(model_results.keys())}")

    # ---- 5. 敏感性矩阵与反向 DCF（基准情景）----
    sensitivity = None
    reverse = None
    if fcff_applicable and base_fcff_assumptions is not None:
        sensitivity = wacc_growth_matrix(
            fcff_base, base_fcff_assumptions,
            settings.sensitivity_wacc_step, settings.sensitivity_growth_step,
        )
        peer_growth = [g for g in peer["rev_growth"] if g is not None]
        reverse = reverse_dcf_report(
            fcff_base, base_fcff_assumptions, snap["price_report_ccy"],
            summary.get("revenue_cagr_3y"), summary.get("revenue_cagr_5y"),
            statistics.median(peer_growth) if peer_growth else None,
        )
        log("reverse_dcf", "完成反向 DCF：由现价反推隐含收入增速与隐含永续增长率")

    # ---- 6. 融合与可信度 ----
    fusion = fusion_svc.fuse_models(model_values, industry, snap["price_report_ccy"])
    restatement_count = db.query(Restatement).filter(Restatement.company_id == company_id).count()
    confidence = conf.confidence_score(
        completeness=std.data_completeness(latest_facts),
        summary=summary, latest=latest_annual,
        divergence=fusion.get("model_divergence"),
        terminal_value_share=terminal_share,
        industry_caveat=industry.caveat,
        fcff_applicable=fcff_applicable,
        restatement_count=restatement_count,
    )
    # 每股口径换算为交易币种（展示对照现价）
    fx = snap["fx_trading_to_report"]
    for key in ("value_pessimistic", "value_base", "value_optimistic", "weighted_fair_value"):
        v = fusion.get(key)
        fusion[f"{key}_trading_ccy"] = (v / fx) if v is not None else None
    log("fusion", f"融合完成：合理价值 {fusion.get('weighted_fair_value_trading_ccy') or 0:.2f} "
        f"{snap['trading_currency']}/股，可信度 {confidence['score']}")

    run_id = str(uuid.uuid4())
    report: dict[str, Any] = {
        "run_id": run_id,
        "company_id": company_id,
        "company_name": company.name_zh,
        "industry": {"code": industry.industry_code, "name": industry.industry_name,
                     "caveat": industry.caveat},
        "valuation_date": valuation_date.isoformat(),
        "model_version": settings.model_version,
        "market_snapshot": snap,
        "wacc_detail": wacc_detail,
        "assumptions": assumptions,
        "assumption_sources": sources,
        "models": model_results,
        "model_values_per_share": model_values,
        "fusion": fusion,
        "confidence": confidence,
        "sensitivity": sensitivity,
        "reverse_dcf": reverse,
        "peers": peer["detail"],
        "warnings": all_warnings,
        "calculation_log": [
            {"seq": i + 1, "step": s, "message": m, "data": d} for i, (s, m, d) in enumerate(logs)
        ],
    }

    if save:
        _persist_run(db, report, snap, assumptions, sources, model_results, sensitivity, fusion, confidence)
    return report


def _persist_run(
    db: Session,
    report: dict[str, Any],
    snap: dict[str, Any],
    assumptions: dict[str, dict[str, float]],
    sources: dict[str, dict[str, str]],
    model_results: dict[str, dict[str, Any]],
    sensitivity: dict[str, Any] | None,
    fusion: dict[str, Any],
    confidence: dict[str, Any],
) -> None:
    """落库：run + inputs + outputs + sensitivity + logs（方案 13.4/13.5）。"""
    run = ValuationRun(
        run_id=report["run_id"],
        company_id=report["company_id"],
        valuation_date=report["valuation_date"],
        model_version=report["model_version"],
        price_used=snap["price"],
        price_currency=snap["trading_currency"],
        shares_diluted_used=snap["diluted_shares"],
        data_snapshot={
            "period_id": snap["latest_period"]["period_id"],
            "fiscal_year": snap["latest_period"]["fiscal_year"],
            "fx_trading_to_report": snap["fx_trading_to_report"],
            "price_date": snap["price_date"],
        },
        summary={"fusion": fusion, "confidence": confidence},
    )
    db.add(run)
    for sc, params in assumptions.items():
        for k, v in params.items():
            db.add(ValuationInput(
                run_id=run.run_id, scenario=sc, param_name=k,
                param_value=float(v) if v is not None else None,
                source=sources.get(sc, {}).get(k, "default"),
            ))
    fx = snap["fx_trading_to_report"]
    for model_name, by_sc in model_results.items():
        for sc, detail in by_sc.items():
            vps = detail.get("value_per_share") if isinstance(detail, dict) else None
            db.add(ValuationOutput(
                run_id=run.run_id, model_name=model_name, scenario=sc,
                value_per_share=vps,
                value_per_share_trading_ccy=(vps / fx) if vps else None,
                equity_value=detail.get("equity_value") if isinstance(detail, dict) else None,
                enterprise_value=detail.get("enterprise_value") if isinstance(detail, dict) else None,
                detail=detail,
                warnings=detail.get("warnings") if isinstance(detail, dict) else None,
            ))
    if sensitivity:
        db.add(SensitivityResult(
            run_id=run.run_id, model_name="fcff",
            axis_x=sensitivity["axis_x"], axis_y=sensitivity["axis_y"], matrix=sensitivity,
        ))
    for entry in report["calculation_log"]:
        db.add(CalculationLog(
            run_id=run.run_id, seq=entry["seq"], step=entry["step"],
            message=entry["message"], data=entry["data"],
        ))
    db.commit()
