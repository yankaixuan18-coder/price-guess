"""FastAPI 应用入口。

模块化单体架构（方案第十四章）：数据、指标、估值、监控在同一服务内分层，
数据量与团队扩大后再拆分。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import companies, tools, valuations
from app.config import settings
from app.database import SessionLocal, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 空库时自动导入样例数据，便于一键启动演示
    from app.models import Company
    from app.seed.run_seed import seed_all

    db = SessionLocal()
    try:
        if db.query(Company).count() == 0:
            seed_all(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.model_version,
    description=(
        "A股、美股、港股上市公司估值分析系统（MVP）。"
        "输出合理价值区间而非单一目标价；估值结果可解释、可追溯、可复现。"
        "样例数据仅供演示，不构成投资建议。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(valuations.router)
app.include_router(tools.router)


@app.get("/health")
def health():
    return {"status": "ok", "model_version": settings.model_version}
