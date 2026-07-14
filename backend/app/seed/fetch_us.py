"""美股数据自动抓取适配器（方案阶段 2 第一个官方数据源适配器）。

数据源：
- 财务/股本/分红：SEC EDGAR Company Facts API（官方结构化 XBRL，免费）
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
- 月度收盘价：stooq.com 免费 CSV 接口

用法（需要能访问 sec.gov 的网络环境；金额自动转换为百万美元）：
    python -m app.seed.fetch_us AAPL --company-id aapl --industry consumer
    python -m app.seed.fetch_us NVDA --company-id nvda --industry manufacturing --name-zh 英伟达

说明：
- 遵守 SEC 公平访问规则：自动化访问需声明 User-Agent（--contact 参数，默认占位邮箱），
  请求频率远低于每秒 10 次上限（方案第三章）。
- US GAAP 标签 → 统一科目映射见 TAG_MAP（方案 5.2 科目映射，映射方式=规则映射，
  公司自定义标签暂不覆盖，缺失科目留空并降低数据完整性得分）。
- 同一财年取最新披露（filed 最大）的数值，自动吸收 10-K/A 更正（方案 15.3 来源优先级）。
- 导入数据质量等级标记为 B（官方结构化数据 + 自动勾稽检查）。
"""
from __future__ import annotations

import argparse
import csv
import io
from datetime import date
from typing import Any

import httpx

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}.us&i=m"

# US GAAP 标签 → 统一科目（按顺序取第一个存在的标签；金额类自动 /1e6 转百万）
TAG_MAP: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cost_of_revenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "operating_profit": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating",
                         "InterestExpenseDebt", "InterestAndDebtExpense"],
    "interest_income": ["InvestmentIncomeInterest"],
    "pre_tax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["ProfitLoss", "NetIncomeLoss"],
    "net_income_attributable_parent": ["NetIncomeLoss"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "accounts_receivable": ["AccountsReceivableNetCurrent"],
    "inventory": ["InventoryNet"],
    "total_current_assets": ["AssetsCurrent"],
    "goodwill": ["Goodwill"],
    "intangible_assets": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "total_assets": ["Assets"],
    "short_term_debt": ["DebtCurrent", "LongTermDebtCurrent", "ShortTermBorrowings"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "total_current_liabilities": ["LiabilitiesCurrent"],
    "total_liabilities": ["Liabilities"],
    "minority_interest": ["MinorityInterest"],
    "shareholders_equity": ["StockholdersEquity"],
    "cash_flow_from_operations": ["NetCashProvidedByUsedInOperatingActivities",
                                  "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "cash_flow_from_investing": ["NetCashProvidedByUsedInInvestingActivities"],
    "cash_flow_from_financing": ["NetCashProvidedByUsedInFinancingActivities"],
    "capital_expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment",
                            "PaymentsToAcquireProductiveAssets"],
    "depreciation_amortization": ["DepreciationDepletionAndAmortization",
                                  "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "share_repurchases": ["PaymentsForRepurchaseOfCommonStock"],
    "share_issuance": ["ProceedsFromIssuanceOfCommonStock"],
    "share_based_compensation": ["ShareBasedCompensation"],
}
# 每股/股数类标签（不做 /1e6 金额换算；股数单独 /1e6 转百万股）
DPS_TAGS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"]
DILUTED_SHARES_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding"]

# 现金流量表科目取正数口径（canonical 中 capex/分红/回购为正数）
POSITIVE_FLOW_FIELDS = {"capital_expenditure", "dividends_paid", "share_repurchases",
                        "share_issuance", "interest_expense"}


def _fiscal_year_of(end: date) -> int:
    """财年标签：1-3 月结束的财年记为上一自然年（如 2025-01 结束 → FY2024）。"""
    return end.year - 1 if end.month <= 3 else end.year


def extract_annual_series(units: list[dict[str, Any]], instant: bool) -> dict[int, dict[str, Any]]:
    """从 companyfacts 一个标签的 units 列表提取年度值。

    仅取 10-K/10-K/A 来源；期间型科目要求跨度 340-390 天（排除季度数）；
    同一财年取 filed 最新的一条（自动吸收更正报告）。
    返回 {fiscal_year: {"val", "end", "filed"}}。
    """
    out: dict[int, dict[str, Any]] = {}
    for e in units:
        form = (e.get("form") or "")
        if not form.startswith("10-K"):
            continue
        end_s = e.get("end")
        if not end_s:
            continue
        end = date.fromisoformat(end_s)
        if not instant:
            start_s = e.get("start")
            if not start_s:
                continue
            span = (end - date.fromisoformat(start_s)).days
            if not (340 <= span <= 390):
                continue
        fy = _fiscal_year_of(end)
        filed = e.get("filed") or "1900-01-01"
        cur = out.get(fy)
        if cur is None or filed > cur["filed"] or (filed == cur["filed"] and end > cur["end"]):
            out[fy] = {"val": e.get("val"), "end": end, "filed": filed}
    return out


def pick_tag_series(facts: dict[str, Any], tags: list[str], instant: bool,
                    unit_names: tuple[str, ...] = ("USD",)) -> dict[int, dict[str, Any]]:
    """按优先级从多个候选标签中取第一个非空年度序列。"""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        node = gaap.get(tag)
        if not node:
            continue
        for unit_name in unit_names:
            units = node.get("units", {}).get(unit_name)
            if units:
                series = extract_annual_series(units, instant)
                if series:
                    return series
    return {}


INSTANT_FIELDS = {
    "cash_and_equivalents", "short_term_investments", "accounts_receivable", "inventory",
    "total_current_assets", "goodwill", "intangible_assets", "total_assets",
    "short_term_debt", "long_term_debt", "total_current_liabilities", "total_liabilities",
    "minority_interest", "shareholders_equity",
}


def build_canonical_years(facts_json: dict[str, Any], max_years: int = 8) -> dict[int, dict[str, Any]]:
    """companyfacts → {fiscal_year: {canonical字段: 百万美元, _end, _filed}}。"""
    per_year: dict[int, dict[str, Any]] = {}
    for field, tags in TAG_MAP.items():
        series = pick_tag_series(facts_json, tags, instant=(field in INSTANT_FIELDS))
        for fy, rec in series.items():
            row = per_year.setdefault(fy, {})
            val = rec["val"]
            if val is None:
                continue
            val = val / 1e6  # → 百万
            if field in POSITIVE_FLOW_FIELDS:
                val = abs(val)
            row[field] = round(val, 3)
            # 用总资产/净利润记录期末与披露日
            if field in ("total_assets", "net_income_attributable_parent"):
                row.setdefault("_end", rec["end"])
                row["_end"] = max(row["_end"], rec["end"]) if field == "total_assets" else row["_end"]
                row.setdefault("_filed", rec["filed"])
                row["_filed"] = max(row["_filed"], rec["filed"])
    # 每股分红（单位 USD/shares）
    dps = pick_tag_series(facts_json, DPS_TAGS, instant=False, unit_names=("USD/shares",))
    for fy, rec in dps.items():
        if fy in per_year and rec["val"]:
            per_year[fy]["_dps"] = float(rec["val"])
    # 稀释加权股数（单位 shares → 百万股）
    sh = pick_tag_series(facts_json, DILUTED_SHARES_TAGS, instant=False, unit_names=("shares",))
    for fy, rec in sh.items():
        if fy in per_year and rec["val"]:
            per_year[fy]["_diluted_shares"] = float(rec["val"]) / 1e6
    # 只保留信息充分的年份，取最近 max_years 年
    complete = {
        fy: row for fy, row in per_year.items()
        if row.get("revenue") and row.get("total_assets") and row.get("_end")
    }
    keep = sorted(complete)[-max_years:]
    return {fy: complete[fy] for fy in keep}


def parse_stooq_csv(text: str) -> list[tuple[date, float]]:
    """stooq 月度 CSV（Date,Open,High,Low,Close,Volume）→ [(date, close)]。"""
    out: list[tuple[date, float]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            d = date.fromisoformat(row["Date"])
            close = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
        out.append((d, close))
    return sorted(out)


# ---------------------------------------------------------------------------
# 网络抓取与入库
# ---------------------------------------------------------------------------

def _client(contact: str) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": f"valuation-system-mvp {contact}"},
        timeout=30.0, follow_redirects=True,
    )


def lookup_cik(client: httpx.Client, ticker: str) -> tuple[int, str]:
    data = client.get(SEC_TICKERS_URL).raise_for_status().json()
    t = ticker.upper()
    for item in data.values():
        if item["ticker"].upper() == t:
            return int(item["cik_str"]), item["title"]
    raise SystemExit(f"未在 SEC 找到 ticker {ticker}")


def fetch_company(ticker: str, company_id: str, industry: str, name_zh: str | None,
                  beta: float, contact: str, years: int) -> None:
    from app.database import SessionLocal, init_db
    from app.models import (
        Company, DailyPrice, Dividend, FinancialFactsCanonical, FinancialPeriod,
        Listing, Security, ShareCount,
    )
    from app.services.quality import run_quality_checks
    from app.services.valuation.industry_config import get_industry_config

    with _client(contact) as client:
        print(f"[1/4] 查询 CIK：{ticker} ...")
        cik, title = lookup_cik(client, ticker)
        print(f"      {title}（CIK {cik}）")
        print("[2/4] 拉取 SEC Company Facts（XBRL 年报数据）...")
        facts_json = client.get(SEC_FACTS_URL.format(cik=cik)).raise_for_status().json()
        years_data = build_canonical_years(facts_json, max_years=years)
        if len(years_data) < 2:
            raise SystemExit("可用年报不足 2 年，无法估值（可能为新上市/外国发行人 20-F，暂不支持）")
        print(f"      取得 FY{min(years_data)}–FY{max(years_data)} 共 {len(years_data)} 年")
        print("[3/4] 拉取 stooq 月度收盘价 ...")
        px_text = client.get(STOOQ_URL.format(symbol=ticker.lower())).raise_for_status().text
        prices = parse_stooq_csv(px_text)
        first_fy_end = min(r["_end"] for r in years_data.values())
        prices = [(d, c) for d, c in prices if d >= first_fy_end]
        if not prices:
            raise SystemExit("stooq 未返回价格数据，请稍后重试或手工提供 prices.csv")
        print(f"      取得 {len(prices)} 个月度价格点（{prices[0][0]} ~ {prices[-1][0]}）")

    init_db()
    db = SessionLocal()
    try:
        print("[4/4] 写入数据库 ...")
        cfg = get_industry_config(industry)
        c = db.get(Company, company_id)
        fields = dict(
            name_zh=name_zh or title, name_en=title, industry_code=industry,
            industry_name=cfg.industry_name, hq_country="US",
            fiscal_year_end_month=max(years_data.values(), key=lambda r: r["_end"])["_end"].month,
            report_currency="USD", beta=beta,
            description=f"SEC EDGAR 自动导入（CIK {cik}）",
        )
        if c is None:
            db.add(Company(company_id=company_id, **fields))
        else:
            for k, v in fields.items():
                setattr(c, k, v)
        sec_id = f"sec_{company_id}"
        if db.get(Security, sec_id) is None:
            db.add(Security(security_id=sec_id, company_id=company_id, name=title))
        lst_id = f"lst_{company_id}"
        if db.get(Listing, lst_id) is None:
            db.add(Listing(listing_id=lst_id, security_id=sec_id, exchange="US",
                           market="US", ticker=ticker.upper(), trading_currency="USD",
                           is_primary=1))
        db.flush()

        # 清理旧数据后重建（幂等）
        old_periods = db.query(FinancialPeriod).filter_by(company_id=company_id).all()
        for p in old_periods:
            db.query(FinancialFactsCanonical).filter_by(period_id=p.id).delete()
            db.delete(p)
        db.query(ShareCount).filter_by(company_id=company_id).delete()
        db.query(Dividend).filter_by(company_id=company_id).delete()
        db.query(DailyPrice).filter_by(listing_id=lst_id).delete()
        db.flush()

        fact_cols = {col.name for col in FinancialFactsCanonical.__table__.columns}
        for fy in sorted(years_data):
            row = years_data[fy]
            end: date = row["_end"]
            filed = date.fromisoformat(row["_filed"]) if row.get("_filed") else None
            period = FinancialPeriod(
                company_id=company_id, fiscal_year=fy, period_type="FY",
                period_end=end, published_at=filed, effective_at=filed,
                revision_version=1, accounting_standard="US_GAAP", currency="USD",
                source=f"SEC EDGAR companyfacts CIK{cik}", quality_grade="B",
            )
            db.add(period)
            db.flush()
            facts = {k: v for k, v in row.items() if not k.startswith("_") and k in fact_cols}
            db.add(FinancialFactsCanonical(period_id=period.id, **facts))
            diluted = row.get("_diluted_shares")
            if diluted:
                db.add(ShareCount(company_id=company_id, as_of=end,
                                  total_shares=diluted, diluted_weighted_shares=diluted))
            if row.get("_dps"):
                db.add(Dividend(company_id=company_id, fiscal_year=fy, dps=row["_dps"],
                                currency="USD", ex_date=None))
        for d, close in prices:
            db.add(DailyPrice(listing_id=lst_id, trade_date=d, close=close, currency="USD"))
        db.commit()
        run_quality_checks(db, company_id)
        print(f"完成：{name_zh or title}（{company_id}）已可在系统中搜索并估值。")
        print("提示：如需同行相对估值，请在 peers.csv 中配置可比公司后用 csv_import --dir 导入。")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="从 SEC EDGAR + stooq 抓取美股数据入库")
    parser.add_argument("ticker", help="美股代码，如 AAPL / NVDA / PG")
    parser.add_argument("--company-id", required=True, help="系统内部公司 ID（小写字母）")
    parser.add_argument("--industry", default="general",
                        help="行业代码：consumer/manufacturing/software/internet/utilities/bank/insurance")
    parser.add_argument("--name-zh", default=None, help="中文名称（缺省用英文名）")
    parser.add_argument("--beta", type=float, default=1.0, help="CAPM 贝塔（默认 1.0）")
    parser.add_argument("--years", type=int, default=8, help="最多导入的年报年数（默认 8）")
    parser.add_argument("--contact", default="demo@example.com",
                        help="SEC 公平访问要求的联系邮箱（请填写真实邮箱）")
    args = parser.parse_args()
    fetch_company(args.ticker, args.company_id, args.industry, args.name_zh,
                  args.beta, args.contact, args.years)


if __name__ == "__main__":
    main()
