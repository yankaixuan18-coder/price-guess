"""财务数据模型（方案 5.1 统一财务科目体系 / 13.2 / 2.4 时点数据）。

- FinancialPeriod：报告期元数据，含时点（point-in-time）五要素：
  period_end / published_at / effective_at / ingested_at / revision_version。
- FinancialFactsCanonical：统一口径宽表，一期一行，科目即列（Canonical Financial Schema）。
- 原始报表科目 → 统一科目的映射记录保存在 FactMapping（方案 5.2）。
"""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FinancialPeriod(Base):
    __tablename__ = "financial_statement_periods"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", "period_type", "revision_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    period_type: Mapped[str] = mapped_column(String(8), default="FY")  # FY/H1/Q1/Q3
    # ---- 时点数据五要素（方案 2.4）----
    period_end: Mapped[date] = mapped_column(Date)          # 财务报告期末
    published_at: Mapped[date | None] = mapped_column(Date)  # 首次披露时间
    effective_at: Mapped[date | None] = mapped_column(Date)  # 系统可使用时间
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revision_version: Mapped[int] = mapped_column(Integer, default=1)  # 修订/重述版本
    # ---- 准则与口径（方案 5.4）----
    accounting_standard: Mapped[str] = mapped_column(String(16), default="CAS")  # CAS/US_GAAP/IFRS/HKFRS
    accounting_standard_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")  # 报告币种
    unit: Mapped[float] = mapped_column(Float, default=1.0)  # 数值单位（1=原币元）
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 来源说明
    quality_grade: Mapped[str] = mapped_column(String(2), default="D")  # A-E（方案 15.4）

    facts: Mapped["FinancialFactsCanonical"] = relationship(back_populates="period", uselist=False)


class FinancialFactsCanonical(Base):
    """统一财务口径宽表。字段清单即方案 5.1 的 Canonical Financial Schema，

    另补充估值必需科目（折旧摊销、股权激励、非经常损益等）。
    金额单位：报告币种（百万）。
    """

    __tablename__ = "financial_facts_canonical"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("financial_statement_periods.id"), unique=True)

    # ---------- 利润表 ----------
    revenue: Mapped[float | None] = mapped_column(Float)
    cost_of_revenue: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    selling_expense: Mapped[float | None] = mapped_column(Float)
    general_admin_expense: Mapped[float | None] = mapped_column(Float)
    research_development_expense: Mapped[float | None] = mapped_column(Float)
    operating_profit: Mapped[float | None] = mapped_column(Float)  # EBIT
    interest_income: Mapped[float | None] = mapped_column(Float)
    interest_expense: Mapped[float | None] = mapped_column(Float)
    investment_income: Mapped[float | None] = mapped_column(Float)
    fair_value_change: Mapped[float | None] = mapped_column(Float)
    pre_tax_income: Mapped[float | None] = mapped_column(Float)
    income_tax: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    net_income_attributable_parent: Mapped[float | None] = mapped_column(Float)
    minority_interest_income: Mapped[float | None] = mapped_column(Float)

    # ---------- 资产负债表 ----------
    cash_and_equivalents: Mapped[float | None] = mapped_column(Float)
    restricted_cash: Mapped[float | None] = mapped_column(Float)
    short_term_investments: Mapped[float | None] = mapped_column(Float)
    accounts_receivable: Mapped[float | None] = mapped_column(Float)
    inventory: Mapped[float | None] = mapped_column(Float)
    total_current_assets: Mapped[float | None] = mapped_column(Float)
    property_plant_equipment: Mapped[float | None] = mapped_column(Float)
    right_of_use_assets: Mapped[float | None] = mapped_column(Float)
    goodwill: Mapped[float | None] = mapped_column(Float)
    intangible_assets: Mapped[float | None] = mapped_column(Float)
    total_assets: Mapped[float | None] = mapped_column(Float)
    short_term_debt: Mapped[float | None] = mapped_column(Float)
    total_current_liabilities: Mapped[float | None] = mapped_column(Float)
    long_term_debt: Mapped[float | None] = mapped_column(Float)
    lease_liabilities: Mapped[float | None] = mapped_column(Float)
    total_liabilities: Mapped[float | None] = mapped_column(Float)
    preferred_equity: Mapped[float | None] = mapped_column(Float)
    minority_interest: Mapped[float | None] = mapped_column(Float)
    shareholders_equity: Mapped[float | None] = mapped_column(Float)  # 归母股东权益

    # ---------- 现金流量表 ----------
    cash_flow_from_operations: Mapped[float | None] = mapped_column(Float)
    cash_flow_from_investing: Mapped[float | None] = mapped_column(Float)
    cash_flow_from_financing: Mapped[float | None] = mapped_column(Float)
    fx_effect_on_cash: Mapped[float | None] = mapped_column(Float)
    capital_expenditure: Mapped[float | None] = mapped_column(Float)  # 取正数
    acquisitions: Mapped[float | None] = mapped_column(Float)
    asset_disposals: Mapped[float | None] = mapped_column(Float)
    dividends_paid: Mapped[float | None] = mapped_column(Float)
    share_repurchases: Mapped[float | None] = mapped_column(Float)
    share_issuance: Mapped[float | None] = mapped_column(Float)
    debt_issuance: Mapped[float | None] = mapped_column(Float)
    debt_repayment: Mapped[float | None] = mapped_column(Float)

    # ---------- 估值必需补充科目（方案 5.3 会计口径调整）----------
    depreciation_amortization: Mapped[float | None] = mapped_column(Float)
    share_based_compensation: Mapped[float | None] = mapped_column(Float)
    non_recurring_gains: Mapped[float | None] = mapped_column(Float)  # 非经常性损益（税后、归母）
    impairment: Mapped[float | None] = mapped_column(Float)  # 资产/商誉减值
    government_grants: Mapped[float | None] = mapped_column(Float)
    discontinued_operations_income: Mapped[float | None] = mapped_column(Float)

    period: Mapped[FinancialPeriod] = relationship(back_populates="facts")


class FactMapping(Base):
    """原始科目 → 统一科目映射表（方案 5.2）。"""

    __tablename__ = "fact_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_standard: Mapped[str] = mapped_column(String(16))     # CAS/US_GAAP/IFRS/HKFRS
    source_taxonomy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_tag: Mapped[str] = mapped_column(String(256))
    source_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    canonical_metric: Mapped[str] = mapped_column(String(64), index=True)
    mapping_method: Mapped[str] = mapped_column(String(16), default="exact")
    # exact/rule/company_specific/manual/unmapped（方案 5.2 五种映射方式）
    company_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 公司特定映射
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    effective_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapping_version: Mapped[str] = mapped_column(String(16), default="v1")


class Restatement(Base):
    """报告重述/更正记录（方案 13.2 restatements）。"""

    __tablename__ = "restatements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    announced_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
