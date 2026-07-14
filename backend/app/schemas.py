"""API 请求/响应模型（方案第十七章接口设计）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ValuationRunRequest(BaseModel):
    """POST /valuations/run 请求体。

    assumptions 支持两种写法：
    - 扁平（作用于全部情景基础上偏移前的 base）：{"wacc": 0.09, ...}
    - 按情景：{"base": {"wacc": 0.09}, "pessimistic": {...}, "all": {...}}
    """

    company_id: str
    valuation_date: date | None = None
    models: list[str] | None = Field(
        default=None, description="可选：fcff / relative_pe / relative_ev_ebitda / relative_pb"
    )
    assumptions: dict[str, float | dict[str, float]] | None = None
    scenario_template_id: int | None = Field(default=None, description="套用已保存的假设版本")
    save: bool = True

    def normalized_overrides(self) -> dict[str, dict[str, float]] | None:
        if not self.assumptions:
            return None
        flat: dict[str, float] = {}
        nested: dict[str, dict[str, float]] = {}
        for k, v in self.assumptions.items():
            if isinstance(v, dict):
                nested[k] = {kk: float(vv) for kk, vv in v.items()}
            else:
                flat[k] = float(v)
        if flat:
            nested.setdefault("all", {}).update(flat)
        return nested or None


class ScenarioSaveRequest(BaseModel):
    """POST /valuations/scenarios：保存一套假设版本（方案 7.2）。"""

    company_id: str
    name: str
    assumptions: dict[str, dict[str, float]]
    note: str | None = None


class WatchlistAddRequest(BaseModel):
    company_id: str
    note: str | None = None
    target_margin_of_safety: float = 0.2
