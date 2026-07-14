"""融合、可信度与情景默认假设的单元测试（方案第 7/10/11 章）。"""
import math

from app.services import forecast as fc
from app.services.valuation.confidence import confidence_score
from app.services.valuation.fusion import fuse_models
from app.services.valuation.industry_config import get_industry_config


def test_fusion_uses_industry_weights_not_simple_average():
    industry = get_industry_config("consumer")  # fcff .5 / pe .3 / ev .1 / pb .1
    values = {
        "fcff": {"pessimistic": 80.0, "base": 100.0, "optimistic": 120.0},
        "relative_pe": {"pessimistic": 60.0, "base": 80.0, "optimistic": 100.0},
        "relative_ev_ebitda": {"pessimistic": 70.0, "base": 90.0, "optimistic": 110.0},
        "relative_pb": {"pessimistic": 50.0, "base": 70.0, "optimistic": 90.0},
    }
    r = fuse_models(values, industry, current_price=70.0)
    expected = 100 * 0.5 + 80 * 0.3 + 90 * 0.1 + 70 * 0.1
    assert math.isclose(r["value_base"], expected, rel_tol=1e-9)
    assert r["value_pessimistic"] < r["value_base"] < r["value_optimistic"]
    assert math.isclose(r["upside"], expected / 70.0 - 1.0, rel_tol=1e-9)
    assert math.isclose(r["safety_margin"], 1.0 - 70.0 / expected, rel_tol=1e-9)


def test_fusion_renormalizes_when_model_unavailable():
    """模型不可用时权重重新归一（方案第十章）。"""
    industry = get_industry_config("consumer")
    values = {
        "fcff": {"base": None},                  # 不可用
        "relative_pe": {"base": 100.0},
        "relative_pb": {"base": 100.0},
    }
    r = fuse_models(values, industry, current_price=None)
    assert math.isclose(r["value_base"], 100.0, rel_tol=1e-9)
    w = r["weights_used"]["base"]
    assert math.isclose(sum(w.values()), 1.0, abs_tol=1e-6)
    assert "fcff" not in w


def test_model_divergence_computed():
    industry = get_industry_config("consumer")
    r = fuse_models({"fcff": {"base": 100.0}, "relative_pe": {"base": 50.0}},
                    industry, current_price=60.0)
    assert r["model_divergence"] > 0.3


def test_confidence_score_range_and_reasons():
    summary = {
        "net_margin_stat": {"mean": 0.2, "std": 0.02},
        "ocf_to_net_income_stat": {"mean": 1.05, "std": 0.1},
        "loss_years": 0, "negative_fcf_years": 0, "total_years": 6,
        "share_dilution_cagr": -0.01,
    }
    latest = {"goodwill_to_equity": 0.05}
    r = confidence_score(completeness=1.0, summary=summary, latest=latest,
                         divergence=0.1, terminal_value_share=0.6,
                         industry_caveat=None, fcff_applicable=True)
    assert 0 <= r["score"] <= 100
    assert r["score"] > 70  # 优质稳定公司应得高分

    bad = confidence_score(
        completeness=0.5,
        summary={"net_margin_stat": {"mean": -0.05, "std": 0.2},
                 "ocf_to_net_income_stat": {"mean": 0.3, "std": 0.5},
                 "loss_years": 3, "negative_fcf_years": 4, "total_years": 6,
                 "share_dilution_cagr": 0.05},
        latest={"goodwill_to_equity": 0.6},
        divergence=0.5, terminal_value_share=0.85,
        industry_caveat="银行应使用剩余收益模型", fcff_applicable=False,
        restatement_count=2,
    )
    assert bad["score"] < r["score"]
    joined = "。".join(bad["reasons"])
    for key in ("亏损", "终值", "分歧", "稀释", "重述"):
        assert key in joined


def test_default_assumptions_scenarios_ordered():
    """悲观/基准/乐观参数方向正确（方案 7.2：增速低中高、WACC 高中低）。"""
    summary = {"revenue_cagr_3y": 0.10, "revenue_cagr_5y": 0.08,
               "ebit_margin_stat": {"mean": 0.18, "std": 0.01}}
    latest = {"effective_tax_rate": 0.25, "ebit_margin": 0.20,
              "capex_to_revenue": 0.05, "da_pct": 0.04, "wc_pct": 0.06}
    d = fc.default_assumptions(summary, latest, "CN", risk_free=0.02, beta=1.0,
                               market_cap=10000, total_debt=2000,
                               industry=get_industry_config("consumer"))
    assert d["pessimistic"]["revenue_growth_5y"] < d["base"]["revenue_growth_5y"] < d["optimistic"]["revenue_growth_5y"]
    assert d["pessimistic"]["wacc"] > d["base"]["wacc"] > d["optimistic"]["wacc"]
    assert d["pessimistic"]["terminal_growth"] <= d["base"]["terminal_growth"] <= d["optimistic"]["terminal_growth"]
    # 永续增长率不超过行业上限
    assert d["optimistic"]["terminal_growth"] <= 0.03 + 1e-9


def test_merge_overrides_marks_source():
    """用户覆盖参数必须标记 user_override（可解释性，方案 2.1）。"""
    summary = {"revenue_cagr_3y": 0.05, "ebit_margin_stat": {"mean": 0.1}}
    latest = {"effective_tax_rate": 0.25, "ebit_margin": 0.1}
    d = fc.default_assumptions(summary, latest, "US", 0.04, 1.0, 5000, 1000,
                               get_industry_config("manufacturing"))
    d.pop("_wacc_detail")
    merged, sources = fc.merge_overrides(d, {"base": {"wacc": 0.123}, "all": {"tax_rate": 0.30}})
    assert merged["base"]["wacc"] == 0.123
    assert sources["base"]["wacc"] == "user_override"
    assert merged["pessimistic"]["tax_rate"] == 0.30
    assert sources["pessimistic"]["tax_rate"] == "user_override"
    assert sources["optimistic"]["wacc"] == "default"
