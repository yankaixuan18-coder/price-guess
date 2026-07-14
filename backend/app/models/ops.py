"""运营类：自选股、估值提醒、数据质量检查结果（方案 12.6 / 13.5 / 15）。"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), unique=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 提醒阈值：安全边际超过该值时触发（方案 12.6）
    target_margin_of_safety: Mapped[float] = mapped_column(Float, default=0.2)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    rule: Mapped[str] = mapped_column(String(64))  # price_in_range/mos_above/valuation_change...
    severity: Mapped[str] = mapped_column(String(8), default="info")  # info/warn/risk
    message: Mapped[str] = mapped_column(String(512))
    payload: Mapped[dict | None] = mapped_column(JSON)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/dismissed


class QualityCheckResult(Base):
    """数据质量检查结果（方案 15）。异常数据不自动删除，进入审核队列。"""

    __tablename__ = "quality_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    period_id: Mapped[int | None] = mapped_column(ForeignKey("financial_statement_periods.id"))
    check_name: Mapped[str] = mapped_column(String(64))
    passed: Mapped[int] = mapped_column(Integer)  # 1/0
    severity: Mapped[str] = mapped_column(String(8), default="warn")
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
