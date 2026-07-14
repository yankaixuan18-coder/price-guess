"""全局配置。

默认使用 SQLite（零配置演示），生产可通过环境变量 DATABASE_URL 切换 PostgreSQL，
例如：DATABASE_URL=postgresql+psycopg://user:pass@host:5432/valuation
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "股票估值系统 Stock Valuation System"
    model_version: str = "0.1.0"
    database_url: str = f"sqlite:///{BASE_DIR / 'valuation.db'}"
    # 各市场默认股权风险溢价（方案 4.1 第五类：宏观和估值参数；CN/HK 含国家风险调整）
    equity_risk_premium: dict[str, float] = {"CN": 0.060, "US": 0.045, "HK": 0.065}
    # 各市场默认信用利差（Kd = 无风险利率 + 信用利差）
    credit_spread: dict[str, float] = {"CN": 0.015, "US": 0.012, "HK": 0.015}
    # 敏感性矩阵默认步长
    sensitivity_wacc_step: float = 0.005
    sensitivity_growth_step: float = 0.0025

    model_config = SettingsConfigDict(env_prefix="", env_file=".env")


settings = Settings()
