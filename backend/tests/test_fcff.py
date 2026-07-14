"""FCFF 模型单元测试（方案第二十章模型标准）。"""
import math

import pytest

from app.services.valuation.fcff import FcffAssumptions, FcffBase, run_fcff


def _base(**kw) -> FcffBase:
    defaults = dict(revenue=1000.0, ebit_margin=0.20, net_debt=200.0,
                    minority_interest=50.0, preferred_equity=0.0,
                    non_operating_assets=0.0, diluted_shares=100.0)
    defaults.update(kw)
    return FcffBase(**defaults)


def _assump(**kw) -> FcffAssumptions:
    defaults = dict(revenue_growth=[0.08] * 5, terminal_ebit_margin=0.20,
                    wacc=0.10, terminal_growth=0.025, tax_rate=0.25,
                    da_pct_revenue=0.05, capex_pct_revenue=0.06, wc_pct_revenue=0.10,
                    exit_ev_ebitda=10.0)
    defaults.update(kw)
    return FcffAssumptions(**defaults)


def test_fcff_hand_calculation_zero_growth():
    """零增长、利润率不变时可手工核对：FCFF 恒定，EV = FCFF×年金 + 终值。"""
    base = _base(net_debt=0.0, minority_interest=0.0)
    a = _assump(revenue_growth=[0.0] * 5, wc_pct_revenue=0.0, exit_ev_ebitda=None)
    r = run_fcff(base, a)
    # FCFF = 1000×0.2×0.75 + 50 - 60 - 0 = 140（每年相同）
    expected_fcff = 1000 * 0.2 * 0.75 + 50 - 60
    for row in r.forecast_table:
        assert math.isclose(row["fcff"], expected_fcff, rel_tol=1e-9)
    pv_explicit = sum(expected_fcff / 1.1 ** t for t in range(1, 6))
    tv = expected_fcff * 1.025 / (0.10 - 0.025)
    expected_ev = pv_explicit + tv / 1.1 ** 5
    assert math.isclose(r.enterprise_value, expected_ev, rel_tol=1e-9)
    assert math.isclose(r.value_per_share, expected_ev / 100.0, rel_tol=1e-9)


def test_equity_bridge_deducts_debt_minority_preferred():
    """股权价值 = EV - 净债务 - 优先股 - 少数股东权益 + 非经营资产（方案 8.1）。"""
    a = _assump()
    r1 = run_fcff(_base(net_debt=0, minority_interest=0), a)
    r2 = run_fcff(_base(net_debt=300, minority_interest=100, preferred_equity=50,
                        non_operating_assets=80), a)
    assert math.isclose(r1.equity_value - r2.equity_value, 300 + 100 + 50 - 80, rel_tol=1e-9)


def test_wacc_below_terminal_growth_forbidden():
    """WACC <= 永续增长率时禁止计算（验收标准）。"""
    with pytest.raises(ValueError, match="WACC"):
        run_fcff(_base(), _assump(wacc=0.02, terminal_growth=0.025))
    with pytest.raises(ValueError):
        run_fcff(_base(), _assump(wacc=0.025, terminal_growth=0.025))


def test_terminal_share_warning():
    """终值占比 > 70% 时必须告警（方案二十一风险 3）。"""
    r = run_fcff(_base(), _assump(wacc=0.06, terminal_growth=0.035))
    assert r.terminal_value_share > 0.70
    assert any("终值" in w for w in r.warnings)


def test_terminal_method_divergence_warning():
    """永续增长法与退出倍数法差异过大时提示（方案 8.1）。"""
    r = run_fcff(_base(), _assump(exit_ev_ebitda=3.0, wacc=0.08))
    assert any("退出倍数" in w for w in r.warnings)


def test_diluted_shares_used_for_per_share_value():
    """每股价值必须使用稀释后股本（验收标准）。"""
    a = _assump()
    r1 = run_fcff(_base(diluted_shares=100.0), a)
    r2 = run_fcff(_base(diluted_shares=110.0), a)
    assert math.isclose(r1.value_per_share / r2.value_per_share, 1.1, rel_tol=1e-9)
    with pytest.raises(ValueError, match="股本"):
        run_fcff(_base(diluted_shares=0.0), a)


def test_deterministic_same_input_same_output():
    """同样输入必须产生相同输出（可复现，验收标准）。"""
    base, a = _base(), _assump()
    r1, r2 = run_fcff(base, a), run_fcff(base, a)
    assert r1.enterprise_value == r2.enterprise_value
    assert r1.forecast_table == r2.forecast_table


def test_negative_equity_warning():
    """企业价值不足覆盖净债务时输出警告而非隐藏。"""
    r = run_fcff(_base(net_debt=100000.0), _assump())
    assert r.equity_value < 0
    assert any("股权价值为负" in w for w in r.warnings)
