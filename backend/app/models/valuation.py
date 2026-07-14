"""预测与估值存储（方案 13.4 / 13.5）。

每次估值生成唯一 valuation_run_id，保存全部输入、输出、敏感性与计算日志，
确保任何一次估值结果可以完整复现（方案第二十章模型标准）。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ValuationRun(Base):
    __tablename__ = "valuation_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    valuation_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(16), default="completed")
    model_version: Mapped[str] = mapped_column(String(16))
    # 估值时点使用的市场快照（价格、股本、汇率、财务期 id），保证可复现
    price_used: Mapped[float | None] = mapped_column(Float)
    price_currency: Mapped[str | None] = mapped_column(String(8))
    shares_diluted_used: Mapped[float | None] = mapped_column(Float)
    data_snapshot: Mapped[dict | None] = mapped_column(JSON)
    # 融合结果摘要（悲观/基准/乐观/加权合理价值/安全边际/分歧度/可信度）
    summary: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    inputs: Mapped[list["ValuationInput"]] = relationship(back_populates="run")
    outputs: Mapped[list["ValuationOutput"]] = relationship(back_populates="run")
    sensitivities: Mapped[list["SensitivityResult"]] = relationship(back_populates="run")
    logs: Mapped[list["CalculationLog"]] = relationship(back_populates="run")


class ValuationInput(Base):
    """每个情景使用的全部假设参数（方案 13.4 forecast_assumptions / valuation_inputs）。"""

    __tablename__ = "valuation_inputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("valuation_runs.run_id"), index=True)
    scenario: Mapped[str] = mapped_column(String(16))  # pessimistic/base/optimistic
    param_name: Mapped[str] = mapped_column(String(64))
    param_value: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="default")  # default/user_override

    run: Mapped[ValuationRun] = relationship(back_populates="inputs")


class ValuationOutput(Base):
    """每个模型×情景的估值输出与完整计算明细。"""

    __tablename__ = "valuation_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("valuation_runs.run_id"), index=True)
    model_name: Mapped[str] = mapped_column(String(32))  # fcff/relative_pe/...
    scenario: Mapped[str] = mapped_column(String(16))
    value_per_share: Mapped[float | None] = mapped_column(Float)  # 报告币种
    value_per_share_trading_ccy: Mapped[float | None] = mapped_column(Float)
    equity_value: Mapped[float | None] = mapped_column(Float)  # 百万，报告币种
    enterprise_value: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict | None] = mapped_column(JSON)  # 预测表、终值、警告等全过程
    warnings: Mapped[list | None] = mapped_column(JSON)

    run: Mapped[ValuationRun] = relationship(back_populates="outputs")


class SensitivityResult(Base):
    __tablename__ = "sensitivity_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("valuation_runs.run_id"), index=True)
    model_name: Mapped[str] = mapped_column(String(32))
    axis_x: Mapped[str] = mapped_column(String(32))  # 如 terminal_growth
    axis_y: Mapped[str] = mapped_column(String(32))  # 如 wacc
    matrix: Mapped[dict] = mapped_column(JSON)  # {x_values, y_values, values[][]}

    run: Mapped[ValuationRun] = relationship(back_populates="sensitivities")


class CalculationLog(Base):
    """计算日志（方案 13.5 calculation_logs）：估值全过程可追溯。"""

    __tablename__ = "calculation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("valuation_runs.run_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    step: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(512))
    data: Mapped[dict | None] = mapped_column(JSON)

    run: Mapped[ValuationRun] = relationship(back_populates="logs")


class ScenarioTemplate(Base):
    """用户保存的估值假设版本（方案 7.2：保存不同估值版本、比较差异）。"""

    __tablename__ = "forecast_scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    assumptions: Mapped[dict] = mapped_column(JSON)  # {scenario: {param: value}}
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
