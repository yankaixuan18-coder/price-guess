"""行情、股本、公司行动与宏观参数（方案 4.1 第三/四/五类 / 13.3）。"""
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyPrice(Base):
    """行情（MVP 采用月末+最新时点采样；生产应接入合规行情源，方案 4.1）。

    只保存原始收盘价，复权在计算层用公司行动重建（方案 4.1 第三类）。
    """

    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("listing_id", "trade_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(ForeignKey("listings.listing_id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Float)  # 原始收盘价（交易币种）
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_suspended: Mapped[int] = mapped_column(Integer, default=0)  # 停牌
    currency: Mapped[str] = mapped_column(String(8))


class ShareCount(Base):
    """股本时序（方案 4.1 第四类）。单位：百万股。"""

    __tablename__ = "share_counts"
    __table_args__ = (UniqueConstraint("company_id", "as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    total_shares: Mapped[float] = mapped_column(Float)
    float_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    basic_weighted_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    diluted_weighted_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    treasury_shares: Mapped[float | None] = mapped_column(Float, nullable=True)


class Dividend(Base):
    """分红记录（每股口径，报告币种）。"""

    __tablename__ = "dividends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    dps: Mapped[float] = mapped_column(Float)  # 每股股息
    currency: Mapped[str] = mapped_column(String(8))
    ex_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class CorporateAction(Base):
    """公司行动：送股/拆股/配股/回购注销等（方案 13.3 corporate_actions）。"""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    action_type: Mapped[str] = mapped_column(String(32))  # split/bonus/rights/buyback_cancel
    action_date: Mapped[date] = mapped_column(Date)
    ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class FxRate(Base):
    """汇率：统一保存兑人民币中间价，任意币种间转换用 CNY 交叉。"""

    __tablename__ = "foreign_exchange_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency: Mapped[str] = mapped_column(String(8), index=True)  # USD/HKD/CNY...
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    rate_to_cny: Mapped[float] = mapped_column(Float)  # 1 单位该币种 = ? CNY


class InterestRate(Base):
    """各市场无风险利率（10 年期国债收益率，方案 4.1 第五类）。"""

    __tablename__ = "market_interest_rates"
    __table_args__ = (UniqueConstraint("market", "tenor", "rate_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(8), index=True)  # CN/US/HK
    tenor: Mapped[str] = mapped_column(String(8), default="10Y")
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    rate: Mapped[float] = mapped_column(Float)  # 小数，如 0.023
