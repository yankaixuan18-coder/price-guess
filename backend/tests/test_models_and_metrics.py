"""相对估值、反向 DCF、敏感性、指标与勾稽检查的单元测试。"""
import math

from app.models import FinancialFactsCanonical
from app.services import metrics as metrics_svc
from app.services import standardize as std
from app.services.quality import check_balance_sheet, check_cash_flow, check_yoy_anomalies
from app.services.valuation import relative as rel
from app.services.valuation.fcff import FcffAssumptions, FcffBase
from app.services.valuation.reverse_dcf import implied_revenue_growth, implied_terminal_growth
from app.services.valuation.sensitivity import wacc_growth_matrix


def _facts(**kw) -> FinancialFactsCanonical:
    return FinancialFactsCanonical(**kw)


# ---------------------------------------------------------------- 相对估值

def test_relative_pe_not_applicable_when_loss():
    r = rel.relative_pe(-1.5, [15, 20], [10, 12, 14] * 4)
    assert r["applicable"] is False


def test_relative_pe_target_is_mean_of_peer_and_history():
    hist = [10.0] * 12
    r = rel.relative_pe(2.0, [20.0], hist)
    assert math.isclose(r["target_multiple"], 15.0, rel_tol=1e-9)
    assert math.isclose(r["value_per_share"], 30.0, rel_tol=1e-9)


def test_relative_pb_roe_quality_adjustment():
    """PB 目标倍数按 ROE 相对同行水平调整（方案 8.5 质量调整）。"""
    hist: list[float] = []
    high = rel.relative_pb(10.0, 0.30, [2.0], [0.15], hist)
    low = rel.relative_pb(10.0, 0.075, [2.0], [0.15], hist)
    assert math.isclose(high["target_multiple"], 4.0, rel_tol=1e-9)  # 2.0 × min(2, .3/.15)
    assert math.isclose(low["target_multiple"], 1.0, rel_tol=1e-9)   # 2.0 × 0.5 下限
    assert high["value_per_share"] > low["value_per_share"]


def test_relative_ev_ebitda_bridge():
    r = rel.relative_ev_ebitda(100.0, net_debt=200.0, minority_interest=50.0,
                               preferred_equity=0.0, diluted_shares=10.0,
                               peer_multiples=[8.0], hist_multiples=[])
    assert math.isclose(r["enterprise_value"], 800.0, rel_tol=1e-9)
    assert math.isclose(r["equity_value"], 550.0, rel_tol=1e-9)
    assert math.isclose(r["value_per_share"], 55.0, rel_tol=1e-9)


def test_scenario_multiple_shift():
    hist = [10.0] * 12
    base = rel.relative_pe(1.0, [], hist, 0.0)
    pess = rel.relative_pe(1.0, [], hist, -0.2)
    assert math.isclose(pess["value_per_share"], base["value_per_share"] * 0.8, rel_tol=1e-9)


def test_percentile_rank():
    hist = list(range(1, 101))
    assert rel.percentile_rank([float(x) for x in hist], 50.5) == 0.5
    assert rel.percentile_rank([float(x) for x in hist], 200.0) == 1.0


# ---------------------------------------------------------------- 反向 DCF

_BASE = FcffBase(revenue=1000, ebit_margin=0.2, net_debt=0, diluted_shares=100)
_A = FcffAssumptions(revenue_growth=[0.05] * 5, terminal_ebit_margin=0.2, wacc=0.10,
                     terminal_growth=0.02, tax_rate=0.25, da_pct_revenue=0.05,
                     capex_pct_revenue=0.06, wc_pct_revenue=0.05)


def test_reverse_dcf_recovers_known_growth():
    """把 g=7% 算出的价值作为"现价"，反解应还原 7%。"""
    from app.services.valuation.fcff import run_fcff

    known = FcffAssumptions(revenue_growth=[0.07] * 5, terminal_ebit_margin=0.2, wacc=0.10,
                            terminal_growth=0.02, tax_rate=0.25, da_pct_revenue=0.05,
                            capex_pct_revenue=0.06, wc_pct_revenue=0.05)
    price = run_fcff(_BASE, known).value_per_share
    sol = implied_revenue_growth(_BASE, _A, price)
    assert sol["solved"] and math.isclose(sol["implied_growth"], 0.07, abs_tol=0.002)


def test_reverse_dcf_boundary_report():
    sol = implied_revenue_growth(_BASE, _A, 1e9)
    assert sol["solved"] is False and sol["boundary"] == "above"


def test_implied_terminal_growth_below_wacc():
    from app.services.valuation.fcff import run_fcff

    price = run_fcff(_BASE, _A).value_per_share * 1.3
    sol = implied_terminal_growth(_BASE, _A, price)
    assert sol["solved"] is True
    assert sol["implied_terminal_growth"] < _A.wacc


# ---------------------------------------------------------------- 敏感性

def test_sensitivity_matrix_blocks_invalid_cells():
    """矩阵中 WACC <= g 的格子必须为 None（禁止计算）。"""
    m = wacc_growth_matrix(_BASE, FcffAssumptions(
        revenue_growth=[0.05] * 5, terminal_ebit_margin=0.2, wacc=0.05,
        terminal_growth=0.045, tax_rate=0.25, da_pct_revenue=0.05,
        capex_pct_revenue=0.06, wc_pct_revenue=0.05), 0.005, 0.0025, 2)
    # 最低 WACC 行 (0.04) 对最高 g 列 (0.05) 必然无效
    assert m["values"][0][-1] is None
    # 基准格子有效
    assert m["values"][2][2] is not None
    # 同一 g 下 WACC 越高价值越低
    col = [row[0] for row in m["values"] if row[0] is not None]
    assert col == sorted(col, reverse=True)


# ---------------------------------------------------------------- 三利润口径与指标

def test_profit_calibers():
    f = _facts(net_income_attributable_parent=100.0, non_recurring_gains=30.0,
               discontinued_operations_income=10.0)
    c = std.profit_calibers(f)
    assert c.reported == 100.0 and c.normalized == 70.0 and c.sustainable == 60.0


def test_roic_and_invested_capital():
    f = _facts(operating_profit=200.0, pre_tax_income=190.0, income_tax=47.5,
               short_term_debt=100.0, long_term_debt=300.0,
               shareholders_equity=600.0, minority_interest=0.0,
               cash_and_equivalents=200.0, revenue=1000.0,
               net_income=142.5, net_income_attributable_parent=142.5,
               total_assets=1500.0)
    rows = [metrics_svc.year_row(2024, f, diluted_shares=100.0)]
    m = metrics_svc.compute_annual_metrics(rows)[0]
    # 有效税率 = 47.5/190 = 0.25；NOPAT = 200×0.75 = 150；IC = 400+600-200 = 800
    assert math.isclose(m["nopat"], 150.0, rel_tol=1e-9)
    assert math.isclose(m["roic"], 150.0 / 800.0, rel_tol=1e-9)
    assert math.isclose(m["eps_diluted"], 1.425, rel_tol=1e-9)


def test_growth_and_dilution_summary():
    def yf(y, rev, ni, shares):
        return metrics_svc.year_row(y, _facts(revenue=rev, net_income=ni,
                                              net_income_attributable_parent=ni), shares)
    rows = [yf(2021, 1000, 100, 100), yf(2022, 1100, 110, 102),
            yf(2023, 1210, 121, 104), yf(2024, 1331, 133, 106)]
    annual = metrics_svc.compute_annual_metrics(rows)
    summary = metrics_svc.compute_summary(rows, annual)
    assert math.isclose(summary["revenue_cagr_3y"], 0.10, abs_tol=1e-6)
    assert summary["share_dilution_cagr"] > 0.019


# ---------------------------------------------------------------- 勾稽与异常

def test_balance_sheet_identity():
    ok, _ = check_balance_sheet(_facts(total_assets=1000.0, total_liabilities=600.0,
                                       shareholders_equity=380.0, minority_interest=20.0))
    assert ok
    bad, _ = check_balance_sheet(_facts(total_assets=1000.0, total_liabilities=600.0,
                                        shareholders_equity=300.0, minority_interest=20.0))
    assert not bad


def test_cash_flow_identity():
    prev = _facts(cash_and_equivalents=100.0)
    cur = _facts(cash_and_equivalents=130.0, cash_flow_from_operations=50.0,
                 cash_flow_from_investing=-30.0, cash_flow_from_financing=10.0)
    ok, _ = check_cash_flow(prev, cur)
    assert ok
    cur_bad = _facts(cash_and_equivalents=300.0, cash_flow_from_operations=50.0,
                     cash_flow_from_investing=-30.0, cash_flow_from_financing=10.0)
    ok2, _ = check_cash_flow(prev, cur_bad)
    assert not ok2


def test_yoy_anomaly_revenue_spike():
    prev = _facts(revenue=100.0)
    cur = _facts(revenue=400.0)
    issues = check_yoy_anomalies(prev, cur)
    assert any(i["check"] == "revenue_yoy_gt_200pct" for i in issues)
