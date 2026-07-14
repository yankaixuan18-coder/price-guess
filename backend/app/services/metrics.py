"""财务分析指标体系（方案第六章）。

输入：按财年升序的年度数据行（facts + 股本 + 每股分红），
输出：逐年指标 annual[] 与汇总 summary{}（增长、稳定性、股东回报）。
所有比率为小数（0.15 = 15%）。
"""
from __future__ import annotations

import statistics
from typing import Any

from app.models import FinancialFactsCanonical
from app.services import standardize as std


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def _yoy(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0) or prev is None or prev <= 0:
        return None
    return cur / prev - 1.0


def cagr(begin: float | None, end: float | None, years: int) -> float | None:
    if begin is None or end is None or begin <= 0 or end <= 0 or years <= 0:
        return None
    return (end / begin) ** (1.0 / years) - 1.0


def year_row(
    fiscal_year: int,
    facts: FinancialFactsCanonical,
    diluted_shares: float | None = None,
    total_shares: float | None = None,
    dps: float | None = None,
) -> dict[str, Any]:
    """构造一行年度原始数据。金额单位：报告币种百万；股本单位：百万股。"""
    return {
        "fiscal_year": fiscal_year,
        "facts": facts,
        "diluted_shares": diluted_shares,
        "total_shares": total_shares,
        "dps": dps,
    }


def compute_annual_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """逐年计算指标（方案 6.1-6.5）。rows 按财年升序。"""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        f: FinancialFactsCanonical = row["facts"]
        prev_f: FinancialFactsCanonical | None = rows[i - 1]["facts"] if i > 0 else None
        calibers = std.profit_calibers(f)
        ebitda = std.ebitda(f)
        tax = std.effective_tax_rate(f)
        nopat = f.operating_profit * (1 - tax) if f.operating_profit is not None else None

        # 平均值口径（期初期末平均），首年退化为期末值
        def _avg(attr: str) -> float | None:
            cur = getattr(f, attr)
            if cur is None:
                return None
            if prev_f is not None and getattr(prev_f, attr) is not None:
                return (cur + getattr(prev_f, attr)) / 2.0
            return cur

        ic_cur = std.invested_capital(f)
        ic_prev = std.invested_capital(prev_f) if prev_f is not None else None
        ic_avg = (ic_cur + ic_prev) / 2.0 if (ic_cur is not None and ic_prev is not None) else ic_cur

        fcf = None
        if f.cash_flow_from_operations is not None:
            fcf = f.cash_flow_from_operations - (f.capital_expenditure or 0.0)

        gross = f.gross_profit
        if gross is None and f.revenue is not None and f.cost_of_revenue is not None:
            gross = f.revenue - f.cost_of_revenue

        shares = row.get("diluted_shares") or row.get("total_shares")
        ni_parent = f.net_income_attributable_parent

        m: dict[str, Any] = {
            "fiscal_year": row["fiscal_year"],
            # ---- 规模 ----
            "revenue": f.revenue,
            "gross_profit": gross,
            "operating_profit": f.operating_profit,
            "ebitda": ebitda,
            "net_income_parent": ni_parent,
            "net_income_normalized": calibers.normalized,
            "net_income_sustainable": calibers.sustainable,
            "ocf": f.cash_flow_from_operations,
            "capex": f.capital_expenditure,
            "fcf": fcf,
            # ---- 盈利能力（6.1）----
            "gross_margin": _safe_div(gross, f.revenue),
            "ebit_margin": _safe_div(f.operating_profit, f.revenue),
            "ebitda_margin": _safe_div(ebitda, f.revenue),
            "net_margin": _safe_div(ni_parent, f.revenue),
            "effective_tax_rate": tax,
            "nopat": nopat,
            "roe": _safe_div(ni_parent, _avg("shareholders_equity")),
            "roa": _safe_div(f.net_income, _avg("total_assets")),
            "roic": _safe_div(nopat, ic_avg),
            # ---- 增长（6.2，同比）----
            "revenue_yoy": _yoy(f.revenue, prev_f.revenue if prev_f else None),
            "gross_profit_yoy": _yoy(gross, (prev_f.gross_profit if prev_f else None)),
            "ebit_yoy": _yoy(f.operating_profit, prev_f.operating_profit if prev_f else None),
            "net_income_yoy": _yoy(ni_parent, prev_f.net_income_attributable_parent if prev_f else None),
            # ---- 现金流质量（6.3）----
            "ocf_to_net_income": _safe_div(f.cash_flow_from_operations, f.net_income),
            "fcf_to_net_income": _safe_div(fcf, f.net_income),
            "capex_to_revenue": _safe_div(f.capital_expenditure, f.revenue),
            # ---- 资产负债风险（6.4）----
            "net_debt": std.net_debt(f),
            "total_debt": std.total_debt(f),
            "net_debt_to_ebitda": _safe_div(std.net_debt(f), ebitda) if ebitda and ebitda > 0 else None,
            "interest_coverage": _safe_div(f.operating_profit, f.interest_expense),
            "short_debt_to_cash": _safe_div(f.short_term_debt, f.cash_and_equivalents),
            "debt_to_assets": _safe_div(std.total_debt(f), f.total_assets),
            "goodwill_to_equity": _safe_div(f.goodwill, f.shareholders_equity),
            "current_ratio": _safe_div(f.total_current_assets, f.total_current_liabilities),
            # ---- 股东回报（6.5，每股与支付率）----
            "eps_diluted": _safe_div(ni_parent, shares),
            "eps_normalized": _safe_div(calibers.normalized, shares),
            "bvps": _safe_div(f.shareholders_equity, shares),
            "dps": row.get("dps"),
            "payout_ratio": _safe_div((row.get("dps") or 0) * shares if shares else None, ni_parent),
            "buyback": f.share_repurchases,
            "dilution_shares": shares,
            # ---- 应收/存货 与营收增速差（6.3）----
            "ar_growth_minus_revenue_growth": _diff_growth(f, prev_f, "accounts_receivable"),
            "inventory_growth_minus_revenue_growth": _diff_growth(f, prev_f, "inventory"),
        }
        out.append(m)
    return out


def _diff_growth(f: FinancialFactsCanonical, prev: FinancialFactsCanonical | None, attr: str) -> float | None:
    if prev is None:
        return None
    g_attr = _yoy(getattr(f, attr), getattr(prev, attr))
    g_rev = _yoy(f.revenue, prev.revenue)
    if g_attr is None or g_rev is None:
        return None
    return g_attr - g_rev


def _stat(values: list[float | None]) -> dict[str, float | None]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"mean": None, "std": None}
    return {
        "mean": statistics.fmean(vals),
        "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
    }


def compute_summary(rows: list[dict[str, Any]], annual: list[dict[str, Any]]) -> dict[str, Any]:
    """跨年汇总：复合增速、稳定性、稀释率（方案 6.2 / 11 评分因素）。"""
    if not annual:
        return {}
    by_year = {m["fiscal_year"]: m for m in annual}
    years = sorted(by_year)
    last = by_year[years[-1]]

    def _cagr_of(key: str, span: int) -> float | None:
        if len(years) <= span:
            return None
        return cagr(by_year[years[-1 - span]].get(key), last.get(key), span)

    margins = [m.get("net_margin") for m in annual]
    ebit_margins = [m.get("ebit_margin") for m in annual]
    ocf_ni = [m.get("ocf_to_net_income") for m in annual]
    fcf_list = [m.get("fcf") for m in annual]
    profit_list = [m.get("net_income_parent") for m in annual]

    shares_series = [m.get("dilution_shares") for m in annual if m.get("dilution_shares")]
    dilution = None
    if len(shares_series) >= 2:
        dilution = cagr(shares_series[0], shares_series[-1], len(shares_series) - 1)

    return {
        "years_covered": years,
        "revenue_cagr_3y": _cagr_of("revenue", 3),
        "revenue_cagr_5y": _cagr_of("revenue", 5),
        "net_income_cagr_3y": _cagr_of("net_income_parent", 3),
        "net_income_cagr_5y": _cagr_of("net_income_parent", 5),
        "fcf_cagr_3y": _cagr_of("fcf", 3),
        "net_margin_stat": _stat(margins),
        "ebit_margin_stat": _stat(ebit_margins),
        "ocf_to_net_income_stat": _stat(ocf_ni),
        "negative_fcf_years": sum(1 for v in fcf_list if v is not None and v < 0),
        "loss_years": sum(1 for v in profit_list if v is not None and v < 0),
        "total_years": len(annual),
        "share_dilution_cagr": dilution,
        "latest": last,
    }
