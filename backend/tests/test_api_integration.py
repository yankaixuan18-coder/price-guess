"""API 集成测试：使用独立临时数据库跑通种子导入 + 核心接口 + 可复现性验收。"""
import os
import tempfile

import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test_valuation.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # lifespan 内自动建表 + 种子导入
        yield c


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_search_and_overview(client):
    r = client.get("/companies/search", params={"q": "600519"})
    assert r.status_code == 200 and r.json()["count"] == 1
    o = client.get("/companies/moutai").json()
    assert o["company"]["name_zh"] == "贵州茅台"
    assert o["current_multiples"]["pe"] > 0
    assert o["market_snapshot"]["price_report_ccy"] > 0


def test_point_in_time_financials(client):
    """时点原则：2020 年 3 月只能看到 2018 年及以前……本库从 2019 年起，

    故 2020-03-31 时点 2019 年报（4 月发布）尚不可用。"""
    r = client.get("/companies/moutai/financials", params={"as_of": "2020-03-31"})
    assert r.json()["items"] == []  # 2019 年报 2020-04-02 才发布
    r2 = client.get("/companies/moutai/financials", params={"as_of": "2020-04-30"})
    years = [i["fiscal_year"] for i in r2.json()["items"]]
    assert years == [2019]


def test_restatement_versioning(client):
    """长江电力 2022 年报存在 v1/v2 两版：重述生效前后取数不同（方案 2.4/15.3）。"""
    fil = client.get("/companies/cypc/filings").json()["items"]
    v = {(i["fiscal_year"], i["revision_version"]) for i in fil}
    assert (2022, 1) in v and (2022, 2) in v
    before = client.get("/companies/cypc/financials", params={"as_of": "2024-01-01"}).json()
    after = client.get("/companies/cypc/financials", params={"as_of": "2024-12-31"}).json()
    rev_before = {i["fiscal_year"]: i["facts"]["revenue"] for i in before["items"]}
    rev_after = {i["fiscal_year"]: i["facts"]["revenue"] for i in after["items"]}
    assert rev_before[2022] == 52060  # 重述公告前用原始版
    assert rev_after[2022] == 73500   # 重述公告后用追溯调整版


def test_run_valuation_and_reproducibility(client):
    """估值落库后可按 run_id 完整取回输入/输出/日志（验收：完整复现）。"""
    r = client.post("/valuations/run", json={"company_id": "ko", "valuation_date": "2025-07-11"})
    assert r.status_code == 200
    body = r.json()
    run_id = body["run_id"]
    assert body["fusion"]["weighted_fair_value"] is not None
    assert 0 <= body["confidence"]["score"] <= 100
    assert body["calculation_log"]

    stored = client.get(f"/valuations/runs/{run_id}").json()
    assert stored["run_id"] == run_id
    assert stored["inputs"] and stored["outputs"] and stored["calculation_log"]
    assert stored["price_used"] == body["market_snapshot"]["price"]
    # 同参数重跑，融合结果一致（确定性）
    r2 = client.post("/valuations/run",
                     json={"company_id": "ko", "valuation_date": "2025-07-11", "save": False})
    assert r2.json()["fusion"]["weighted_fair_value"] == body["fusion"]["weighted_fair_value"]


def test_assumption_override_and_sources(client):
    r = client.post("/valuations/run", json={
        "company_id": "aapl", "save": False,
        "assumptions": {"base": {"wacc": 0.095}, "all": {"terminal_growth": 0.02}},
    }).json()
    assert r["assumptions"]["base"]["wacc"] == 0.095
    assert r["assumption_sources"]["base"]["wacc"] == "user_override"
    assert r["assumptions"]["pessimistic"]["terminal_growth"] == 0.02


def test_currency_conversion_tencent(client):
    """腾讯：CNY 报告 / HKD 交易，估值必须完成币种换算。"""
    r = client.post("/valuations/run", json={"company_id": "tencent", "save": False}).json()
    snap = r["market_snapshot"]
    assert snap["report_currency"] == "CNY" and snap["trading_currency"] == "HKD"
    fusion = r["fusion"]
    ratio = fusion["weighted_fair_value"] / fusion["weighted_fair_value_trading_ccy"]
    assert abs(ratio - snap["fx_trading_to_report"]) < 1e-6


def test_reverse_dcf_endpoint(client):
    r = client.get("/companies/xiaomi/reverse-dcf")
    assert r.status_code == 200
    body = r.json()
    ig = body["reverse_dcf"]["implied_revenue_growth_5y"]
    assert "implied_growth" in ig or ig.get("solved") is False


def test_screener_compare_watchlist_alerts(client):
    client.post("/valuations/run", json={"company_id": "moutai", "valuation_date": "2025-07-11"})
    s = client.get("/screeners").json()
    assert s["count"] >= 1
    cmp_ = client.get("/compare", params={"ids": "moutai,ko"}).json()
    assert cmp_["count"] == 2
    assert client.post("/watchlist", json={"company_id": "moutai"}).status_code == 200
    alerts = client.get("/alerts", params={"refresh": True}).json()
    assert isinstance(alerts["items"], list)
    assert client.delete("/watchlist/moutai").status_code == 200


def test_quality_checks_recorded(client):
    """种子导入后勾稽检查应有记录且茅台全部通过（数据标准验收）。"""
    o = client.get("/companies/moutai").json()
    identity_fails = [f for f in o["risk_flags"] if f["check"] == "balance_sheet_identity"]
    assert identity_fails == []
