"""财务标准化：三个利润口径（方案 5.3）与统一科目工具。

输出三个利润口径：
1. 报告净利润（归母）reported
2. 标准化净利润 normalized = 报告净利润 - 非经常性损益（税后归母）
3. 可持续经营利润 sustainable = 标准化净利润 - 终止经营业务损益
"""
from dataclasses import dataclass

from app.models import FinancialFactsCanonical

# Canonical Financial Schema 关键科目（用于数据完整性评估，方案 11 因素一）
KEY_FIELDS = [
    "revenue", "operating_profit", "net_income", "net_income_attributable_parent",
    "total_assets", "total_liabilities", "shareholders_equity",
    "cash_and_equivalents", "short_term_debt", "long_term_debt",
    "cash_flow_from_operations", "capital_expenditure", "depreciation_amortization",
]


@dataclass
class ProfitCalibers:
    reported: float | None      # 报告净利润（归母）
    normalized: float | None    # 标准化净利润（扣非）
    sustainable: float | None   # 可持续经营利润


def profit_calibers(f: FinancialFactsCanonical) -> ProfitCalibers:
    reported = f.net_income_attributable_parent
    if reported is None:
        return ProfitCalibers(None, None, None)
    normalized = reported - (f.non_recurring_gains or 0.0)
    sustainable = normalized - (f.discontinued_operations_income or 0.0)
    return ProfitCalibers(reported, normalized, sustainable)


def total_debt(f: FinancialFactsCanonical) -> float:
    """有息负债 = 短期借款 + 长期借款 + 租赁负债。"""
    return (f.short_term_debt or 0.0) + (f.long_term_debt or 0.0) + (f.lease_liabilities or 0.0)


def net_debt(f: FinancialFactsCanonical) -> float:
    """净债务 = 有息负债 - 现金及等价物 - 短期投资。"""
    return total_debt(f) - (f.cash_and_equivalents or 0.0) - (f.short_term_investments or 0.0)


def ebitda(f: FinancialFactsCanonical) -> float | None:
    if f.operating_profit is None:
        return None
    return f.operating_profit + (f.depreciation_amortization or 0.0)


def effective_tax_rate(f: FinancialFactsCanonical, default: float = 0.25) -> float:
    """有效税率，限制在 [0, 45%] 内，异常时回退默认值。"""
    if f.pre_tax_income and f.income_tax is not None and f.pre_tax_income > 0:
        rate = f.income_tax / f.pre_tax_income
        if 0.0 <= rate <= 0.45:
            return rate
    return default


def invested_capital(f: FinancialFactsCanonical) -> float | None:
    """投入资本（融资法近似）：有息负债 + 归母权益 + 少数股东权益 - 现金 - 短期投资。

    对应方案 6.1：Invested Capital = 经营性资产 - 无息经营负债。
    """
    if f.shareholders_equity is None:
        return None
    ic = (
        total_debt(f)
        + f.shareholders_equity
        + (f.minority_interest or 0.0)
        - (f.cash_and_equivalents or 0.0)
        - (f.short_term_investments or 0.0)
    )
    return ic


def data_completeness(f: FinancialFactsCanonical) -> float:
    """关键科目完整率（0-1）。"""
    present = sum(1 for k in KEY_FIELDS if getattr(f, k) is not None)
    return present / len(KEY_FIELDS)
