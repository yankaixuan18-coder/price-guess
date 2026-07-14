"""数据接入测试：CSV 数据包导入（新增整家公司→估值跑通）+ EDGAR 解析逻辑。"""
import os
import tempfile
from pathlib import Path

import pytest

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmpdir}/test_import.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed.fetch_us import (  # noqa: E402
    build_canonical_years,
    extract_annual_series,
    parse_stooq_csv,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# CSV 数据包：新增一家公司并完成估值
# ---------------------------------------------------------------------------

PKG = {
    "companies.csv": (
        "company_id,name_zh,name_en,industry_code,market,exchange,ticker,"
        "report_currency,trading_currency,beta,description\n"
        "newco,新增测试公司,NewCo,consumer,CN,SSE,601234.SH,CNY,CNY,0.9,CSV数据包导入测试\n"
    ),
    "financials.csv": (
        "company_id,fiscal_year,period_end,published_at,accounting_standard,currency,"
        "revenue,cost_of_revenue,operating_profit,pre_tax_income,income_tax,net_income,"
        "net_income_attributable_parent,cash_and_equivalents,accounts_receivable,inventory,"
        "total_current_assets,total_assets,short_term_debt,long_term_debt,"
        "total_current_liabilities,total_liabilities,shareholders_equity,"
        "cash_flow_from_operations,cash_flow_from_investing,cash_flow_from_financing,"
        "capital_expenditure,depreciation_amortization,dividends_paid\n"
        "newco,2022,2022-12-31,2023-04-20,CAS,CNY,10000,6000,1800,1800,360,1440,1440,"
        "3000,1200,900,6000,15000,500,2000,3200,6060,8940,1700,-800,-600,500,350,400\n"
        "newco,2023,2023-12-31,2024-04-20,CAS,CNY,11500,6800,2100,2100,420,1680,1680,"
        "3600,1350,980,6800,16800,500,2100,3500,6720,10080,1950,-850,-500,550,380,500\n"
        "newco,2024,2024-12-31,2025-04-20,CAS,CNY,13200,7700,2450,2450,490,1960,1960,"
        "4300,1500,1050,7700,18800,500,2200,3900,7420,11380,2280,-900,-680,600,420,600\n"
    ),
    "share_counts.csv": (
        "company_id,as_of,total_shares,diluted_weighted_shares\n"
        "newco,2022-12-31,1000,1000\n"
        "newco,2023-12-31,1000,1000\n"
        "newco,2024-12-31,1000,1000\n"
    ),
    "prices.csv": (
        "company_id,trade_date,close\n"
        "newco,2023-04-28,20.0\nnewco,2023-12-29,22.0\n"
        "newco,2024-06-28,24.0\nnewco,2024-12-31,25.0\nnewco,2025-06-30,26.5\n"
    ),
    "dividends.csv": "company_id,fiscal_year,dps,ex_date\nnewco,2024,0.6,2025-06-30\n",
    "peers.csv": "company_id,peer_company_id,rule\nnewco,moutai,测试可比\n",
}


def test_csv_package_end_to_end(client):
    """数据包导入 → 搜索可见 → 指标正确 → 估值可运行（新增公司完整链路）。"""
    from app.database import SessionLocal
    from app.seed.csv_import import import_package

    pkg_dir = Path(_tmpdir) / "pkg"
    pkg_dir.mkdir(exist_ok=True)
    for name, content in PKG.items():
        (pkg_dir / name).write_text(content, encoding="utf-8")

    db = SessionLocal()
    try:
        summary = import_package(db, pkg_dir)
    finally:
        db.close()
    assert summary["financials.csv"] == 3
    assert summary["companies.csv"] == 1

    r = client.get("/companies/search", params={"q": "601234"})
    assert r.json()["count"] == 1

    m = client.get("/companies/newco/metrics").json()
    latest = m["summary"]["latest"]
    assert latest["fiscal_year"] == 2024
    assert abs(latest["net_margin"] - 1960 / 13200) < 1e-6

    v = client.post("/valuations/run", json={"company_id": "newco", "save": True})
    assert v.status_code == 200
    body = v.json()
    assert body["fusion"]["weighted_fair_value"] is not None
    assert body["market_snapshot"]["price"] == 26.5

    # 幂等：重复导入不报错、不重复建公司
    db = SessionLocal()
    try:
        import_package(db, pkg_dir)
        from app.models import Company
        assert db.query(Company).filter_by(company_id="newco").count() == 1
    finally:
        db.close()


def test_financials_csv_rejects_unknown_company(client):
    from app.database import SessionLocal
    from app.seed.csv_import import import_financials_csv

    bad = Path(_tmpdir) / "bad.csv"
    bad.write_text(
        "company_id,fiscal_year,period_end,published_at,revenue\n"
        "ghost,2024,2024-12-31,2025-04-01,100\n", encoding="utf-8")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError, match="不存在"):
            import_financials_csv(db, bad)
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# EDGAR companyfacts 解析（离线 fixture，不发网络请求）
# ---------------------------------------------------------------------------

def _dur(start, end, val, filed, form="10-K"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "fp": "FY"}


def _inst(end, val, filed, form="10-K"):
    return {"end": end, "val": val, "filed": filed, "form": form, "fp": "FY"}


FIXTURE = {
    "entityName": "TestCorp Inc",
    "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            _dur("2022-10-01", "2023-09-30", 100_000_000_000, "2023-11-01"),
            _dur("2023-10-01", "2024-09-28", 110_000_000_000, "2024-11-01"),
            # 季度数据应被剔除（跨度 ~90 天）
            _dur("2024-07-01", "2024-09-28", 30_000_000_000, "2024-11-01", form="10-Q"),
            # 更正报告（同一财年 filed 更晚）应覆盖原值
            _dur("2023-10-01", "2024-09-28", 111_000_000_000, "2025-01-15", form="10-K/A"),
        ]}},
        "Assets": {"units": {"USD": [
            _inst("2023-09-30", 350_000_000_000, "2023-11-01"),
            _inst("2024-09-28", 365_000_000_000, "2024-11-01"),
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            _dur("2022-10-01", "2023-09-30", 25_000_000_000, "2023-11-01"),
            _dur("2023-10-01", "2024-09-28", 28_000_000_000, "2024-11-01"),
        ]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            _dur("2023-10-01", "2024-09-28", 9_000_000_000, "2024-11-01"),
        ]}},
        "CommonStockDividendsPerShareDeclared": {"units": {"USD/shares": [
            _dur("2023-10-01", "2024-09-28", 0.98, "2024-11-01"),
        ]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            _dur("2023-10-01", "2024-09-28", 15_400_000_000, "2024-11-01"),
        ]}},
    }},
}


def test_extract_annual_series_filters_and_restatement():
    units = FIXTURE["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    series = extract_annual_series(units, instant=False)
    # 9 月末财年 → fy = end.year；10-Q 季度值被剔除；10-K/A 更正覆盖
    assert set(series) == {2023, 2024}
    assert series[2024]["val"] == 111_000_000_000
    assert series[2023]["val"] == 100_000_000_000


def test_build_canonical_years_units_and_flows():
    years = build_canonical_years(FIXTURE)
    assert set(years) == {2023, 2024}
    y24 = years[2024]
    assert y24["revenue"] == 111_000.0          # 美元 → 百万
    assert y24["total_assets"] == 365_000.0
    assert y24["capital_expenditure"] == 9_000.0  # 正数口径
    assert y24["_dps"] == 0.98
    assert abs(y24["_diluted_shares"] - 15_400.0) < 1e-6
    assert y24["_end"].isoformat() == "2024-09-28"


def test_fiscal_year_label_for_jan_enders():
    """1 月底结束的财年（零售商常见）归属上一自然年。"""
    units = [_dur("2024-02-01", "2025-01-31", 5_000_000_000, "2025-03-20")]
    series = extract_annual_series(units, instant=False)
    assert set(series) == {2024}


def test_parse_stooq_csv():
    text = "Date,Open,High,Low,Close,Volume\n2024-11-29,230,240,225,237.33,1000\nbad,row,,,\n2024-12-31,240,255,238,250.42,1200\n"
    prices = parse_stooq_csv(text)
    assert prices == [(__import__("datetime").date(2024, 11, 29), 237.33),
                      (__import__("datetime").date(2024, 12, 31), 250.42)]
