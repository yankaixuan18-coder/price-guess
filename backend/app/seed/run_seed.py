"""样例数据导入脚本。

保证会计一致性的派生规则：
- total_liabilities = total_assets - shareholders_equity - minority_interest（勾稽恒等）；
- gross_profit = revenue - cost_of_revenue；
- pre_tax_income 由 净利润/(1-税率) 反推，income_tax 取差额；
- cash_flow_from_financing = -分红 - 回购 + 增发 + 债务净变动；
- cash_flow_from_investing 取现金恒等式的平衡项（期末现金-期初现金-OCF-FCF融资）。
月度价格：在年末锚点间做几何插值并叠加确定性扰动（可复现）。
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

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
    Restatement,
    Security,
    ShareCount,
)
from app.seed.sample_data import COMPANIES, DATA_CUTOFF, FX_RATES, PUBLISH_RULES, RISK_FREE, YEARS


def _period_dates(company_id: str, fiscal_year: int) -> tuple[date, date]:
    """返回 (period_end, published_at)。publish 前缀 + 表示次年。"""
    rule = PUBLISH_RULES[company_id]
    pe_m, pe_d = (int(x) for x in rule["period_end"].split("-"))
    period_end = date(fiscal_year, pe_m, pe_d)
    pub = rule["publish"]
    if pub.startswith("+"):
        m, d = (int(x) for x in pub[1:].split("-"))
        published = date(fiscal_year + 1, m, d)
    else:
        m, d = (int(x) for x in pub.split("-"))
        published = date(fiscal_year, m, d)
    return period_end, published


def _facts_from_dict(fin: dict, i: int | None = None, override: dict | None = None) -> dict:
    """从平行数组（或重述覆盖 dict）取出一年的科目并做一致性派生。"""
    if override is not None:
        raw = dict(override)
    else:
        raw = {k: v[i] for k, v in fin.items() if k != "tax_rate"}
        raw["tax_rate"] = fin["tax_rate"][i]
    tax_rate = raw.pop("tax_rate", 0.25)

    rev = raw.get("revenue")
    cogs = raw.get("cost_of_revenue")
    ni_parent = raw.get("net_income_attributable_parent") or 0.0
    minority_inc = raw.get("minority_interest_income") or 0.0
    ni_total = ni_parent + minority_inc
    pre_tax = ni_total / (1 - tax_rate) if tax_rate < 1 else ni_total

    facts = dict(raw)
    facts["gross_profit"] = (rev - cogs) if (rev is not None and cogs is not None) else None
    facts["net_income"] = ni_total
    facts["pre_tax_income"] = round(pre_tax, 1)
    facts["income_tax"] = round(pre_tax - ni_total, 1)
    # 勾稽恒等：负债 = 资产 - 归母权益 - 少数股东权益
    ta = facts.get("total_assets")
    eq = facts.get("shareholders_equity")
    mi = facts.get("minority_interest") or 0.0
    if ta is not None and eq is not None:
        facts["total_liabilities"] = ta - eq - mi
    return facts


def _derive_cash_flows(years_facts: list[dict]) -> None:
    """派生融资/投资现金流，使现金恒等式成立（首年投资现金流留空）。"""
    for i, cur in enumerate(years_facts):
        div = cur.get("dividends_paid") or 0.0
        buyback = cur.get("share_repurchases") or 0.0
        issue = cur.get("share_issuance") or 0.0
        if i == 0:
            debt_delta = 0.0
        else:
            prev = years_facts[i - 1]
            debt_delta = (
                (cur.get("short_term_debt") or 0) + (cur.get("long_term_debt") or 0)
                - (prev.get("short_term_debt") or 0) - (prev.get("long_term_debt") or 0)
            )
        fin_cf = -div - buyback + issue + debt_delta
        cur["cash_flow_from_financing"] = round(fin_cf, 1)
        cur["debt_issuance"] = round(max(debt_delta, 0.0), 1)
        cur["debt_repayment"] = round(max(-debt_delta, 0.0), 1)
        if i > 0:
            prev_cash = years_facts[i - 1].get("cash_and_equivalents")
            cash = cur.get("cash_and_equivalents")
            ocf = cur.get("cash_flow_from_operations")
            if None not in (prev_cash, cash, ocf):
                cur["cash_flow_from_investing"] = round(cash - prev_cash - ocf - fin_cf, 1)


def _wiggle(key: str, pct: float = 0.05) -> float:
    """确定性伪随机扰动 [-pct, +pct]（哈希种子，保证同输入同输出）。"""
    h = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
    return (h / 0xFFFFFFFF - 0.5) * 2 * pct


def _month_ends(start: date, end: date) -> list[date]:
    out = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        month_end = nxt - timedelta(days=1)
        if start <= month_end <= end:
            out.append(month_end)
        cur = nxt
    return out


def _gen_monthly_prices(company_id: str, anchors: dict) -> list[tuple[date, float]]:
    """年末锚点几何插值 + 确定性扰动，尾部追加数据截止日价格。"""
    cutoff = date.fromisoformat(DATA_CUTOFF)
    points: list[tuple[date, float]] = []
    year_keys = sorted(k for k in anchors if isinstance(k, int))
    for y in year_keys:
        points.append((date(y, 12, 31), float(anchors[y])))
    points.append((cutoff, float(anchors["latest"])))

    prices: list[tuple[date, float]] = []
    for (d0, p0), (d1, p1) in zip(points, points[1:]):
        for m in _month_ends(d0 + timedelta(days=1), d1 - timedelta(days=1)):
            frac = (m - d0).days / max((d1 - d0).days, 1)
            base = p0 * (p1 / p0) ** frac
            price = base * (1 + _wiggle(f"{company_id}:{m.isoformat()}"))
            prices.append((m, round(price, 2)))
        prices.append((d1, round(p1, 2)))
    return prices


def seed_all(db: Session) -> None:
    print("[seed] 导入样例数据（演示用，质量等级 D）...")
    # ---- 汇率与无风险利率 ----
    cutoff = date.fromisoformat(DATA_CUTOFF)
    for ccy, series in FX_RATES.items():
        for k, v in series.items():
            d = cutoff if k == "latest" else date(int(k), 12, 31)
            db.add(FxRate(currency=ccy, rate_date=d, rate_to_cny=v))
    db.add(FxRate(currency="CNY", rate_date=date(2018, 1, 1), rate_to_cny=1.0))
    for market, series in RISK_FREE.items():
        for k, v in series.items():
            d = cutoff if k == "latest" else date(int(k), 12, 31)
            db.add(InterestRate(market=market, tenor="10Y", rate_date=d, rate=v))

    for spec in COMPANIES:
        c = spec["company"]
        cid = c["company_id"]
        db.add(Company(**c))
        sec_id = f"sec_{cid}"
        db.add(Security(security_id=sec_id, company_id=cid, security_type="common",
                        name=c["name_zh"]))
        db.add(Listing(security_id=sec_id, is_primary=1, **spec["listing"]))

        # ---- 年报（含派生一致性） ----
        years_facts = [_facts_from_dict(spec["fin"], i) for i in range(len(YEARS))]
        _derive_cash_flows(years_facts)
        for i, fy in enumerate(YEARS):
            period_end, published = _period_dates(cid, fy)
            period = FinancialPeriod(
                company_id=cid, fiscal_year=fy, period_type="FY",
                period_end=period_end, published_at=published, effective_at=published,
                revision_version=1, accounting_standard=spec["accounting_standard"],
                currency=c["report_currency"], quality_grade="D",
                source="样例数据（近似整理，仅供演示）",
            )
            db.add(period)
            db.flush()
            db.add(FinancialFactsCanonical(period_id=period.id, **years_facts[i]))

        # ---- 重述示例（同一控制下合并追溯调整） ----
        rst = spec.get("restatement")
        if rst:
            fy = rst["fiscal_year"]
            base_i = YEARS.index(fy)
            merged = {k: v[base_i] for k, v in spec["fin"].items() if k != "tax_rate"}
            merged["tax_rate"] = spec["fin"]["tax_rate"][base_i]
            merged.update(rst["revised"])
            revised_facts = _facts_from_dict({}, override=merged)
            period_end, _ = _period_dates(cid, fy)
            announced = date.fromisoformat(rst["announced"])
            period_v2 = FinancialPeriod(
                company_id=cid, fiscal_year=fy, period_type="FY",
                period_end=period_end, published_at=announced, effective_at=announced,
                revision_version=2, accounting_standard=spec["accounting_standard"],
                currency=c["report_currency"], quality_grade="D",
                source=f"追溯重述：{rst['reason']}",
            )
            db.add(period_v2)
            db.flush()
            db.add(FinancialFactsCanonical(period_id=period_v2.id, **revised_facts))
            db.add(Restatement(company_id=cid, fiscal_year=fy, announced_at=announced,
                               reason=rst["reason"]))

        # ---- 股本 / 分红 ----
        for i, fy in enumerate(YEARS):
            period_end, _ = _period_dates(cid, fy)
            db.add(ShareCount(
                company_id=cid, as_of=period_end,
                total_shares=spec["shares_total"][i],
                diluted_weighted_shares=spec["shares_diluted"][i],
            ))
            dps = spec["dps"][i]
            if dps:
                db.add(Dividend(company_id=cid, fiscal_year=fy, dps=dps,
                                currency=c["report_currency"],
                                ex_date=date(fy + 1, 6, 30)))

        # ---- 月度价格 ----
        for d, p in _gen_monthly_prices(cid, spec["price_anchors"]):
            db.add(DailyPrice(listing_id=spec["listing"]["listing_id"], trade_date=d,
                              close=p, currency=spec["listing"]["trading_currency"]))

    # ---- 可比公司关系 ----
    for spec in COMPANIES:
        for peer_id, rule in spec.get("peers", []):
            db.add(PeerLink(company_id=spec["company"]["company_id"],
                            peer_company_id=peer_id, rule=rule))
    db.commit()

    # ---- 导入后数据质量检查（方案 15：每次数据更新后自动执行）----
    from app.services.quality import run_quality_checks

    for spec in COMPANIES:
        run_quality_checks(db, spec["company"]["company_id"])
    print(f"[seed] 完成：{len(COMPANIES)} 家公司（数据截至 {DATA_CUTOFF}）")


if __name__ == "__main__":
    from app.database import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        seed_all(session)
    finally:
        session.close()
