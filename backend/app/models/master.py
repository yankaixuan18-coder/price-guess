"""主数据模型（方案 4.1 第一类 / 13.1）。

核心原则：不以股票代码作为唯一标识。
company_id（公司主体）→ security_id（具体证券）→ listing_id（具体上市地点）。
一家同时在上海、香港、美国上市的公司只有一个 company_id，可以有多个 security/listing。
"""
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_zh: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 行业分类（MVP 使用内部行业代码，对应行业估值模板，见方案第九章）
    industry_code: Mapped[str] = mapped_column(String(32), index=True)
    industry_name: Mapped[str] = mapped_column(String(64))
    business_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hq_country: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, default=12)
    report_currency: Mapped[str] = mapped_column(String(8), default="CNY")
    # CAPM 用贝塔（MVP 存在公司层面，后续可按市场回归计算）
    beta: Mapped[float] = mapped_column(Float, default=1.0)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    securities: Mapped[list["Security"]] = relationship(back_populates="company")


class Security(Base):
    __tablename__ = "securities"

    security_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    security_type: Mapped[str] = mapped_column(String(16), default="common")  # common/adr/pref
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    company: Mapped[Company] = relationship(back_populates="securities")
    listings: Mapped[list["Listing"]] = relationship(back_populates="security")


class Listing(Base):
    __tablename__ = "listings"

    listing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.security_id"), index=True)
    exchange: Mapped[str] = mapped_column(String(16))  # SSE/SZSE/HKEX/NASDAQ/NYSE
    market: Mapped[str] = mapped_column(String(8), index=True)  # CN/US/HK
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    trading_currency: Mapped[str] = mapped_column(String(8))
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="listed")  # listed/delisted
    delist_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    adr_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # ADR 换算比例
    is_primary: Mapped[int] = mapped_column(Integer, default=1)  # 估值展示所用主上市地

    security: Mapped[Security] = relationship(back_populates="listings")


class SecurityIdentifier(Base):
    """外部标识映射：ISIN、CIK 等（方案 13.1 security_identifiers）。"""

    __tablename__ = "security_identifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.security_id"), index=True)
    id_type: Mapped[str] = mapped_column(String(16))  # isin/cik/lei/ticker_history
    id_value: Mapped[str] = mapped_column(String(64))
    effective_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_end: Mapped[date | None] = mapped_column(Date, nullable=True)


class PeerLink(Base):
    """可比公司关系（方案 13.4 peer_groups）。

    可比公司不能只按行业代码选择（方案 8.5），rule 字段记录入选理由。
    """

    __tablename__ = "peer_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    peer_company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"))
    rule: Mapped[str | None] = mapped_column(String(256), nullable=True)
