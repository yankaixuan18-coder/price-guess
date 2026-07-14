"""CSV 财务数据导入（方案阶段 1：手工或 CSV 导入财务数据）。

用法：
    python -m app.seed.csv_import path/to/financials.csv

CSV 列（模板见 app/seed/templates/financials_template.csv）：
    company_id, fiscal_year, period_end, published_at, accounting_standard,
    currency, revision_version, 以及任意 FinancialFactsCanonical 科目列。
金额单位：报告币种百万。同一 (company_id, fiscal_year, revision_version) 重复导入时覆盖。
"""
from __future__ import annotations

import csv
import sys
from datetime import date

from sqlalchemy.orm import Session

from app.models import FinancialFactsCanonical, FinancialPeriod

META_COLS = {
    "company_id", "fiscal_year", "period_end", "published_at", "effective_at",
    "accounting_standard", "currency", "revision_version", "period_type",
    "source", "quality_grade",
}
FACT_COLS = {c.name for c in FinancialFactsCanonical.__table__.columns} - {"id", "period_id"}


def import_financials_csv(db: Session, path: str) -> int:
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        unknown = set(reader.fieldnames or []) - META_COLS - FACT_COLS
        if unknown:
            raise ValueError(f"无法识别的列（请对照统一科目表）: {sorted(unknown)}")
        for row in reader:
            cid = row["company_id"].strip()
            fy = int(row["fiscal_year"])
            rev = int(row.get("revision_version") or 1)
            period_end = date.fromisoformat(row["period_end"])
            published = date.fromisoformat(row["published_at"]) if row.get("published_at") else None
            effective = (
                date.fromisoformat(row["effective_at"]) if row.get("effective_at") else published
            )
            existing = (
                db.query(FinancialPeriod)
                .filter_by(company_id=cid, fiscal_year=fy,
                           period_type=row.get("period_type") or "FY", revision_version=rev)
                .first()
            )
            if existing:
                db.query(FinancialFactsCanonical).filter_by(period_id=existing.id).delete()
                db.delete(existing)
                db.flush()
            period = FinancialPeriod(
                company_id=cid, fiscal_year=fy,
                period_type=row.get("period_type") or "FY",
                period_end=period_end, published_at=published, effective_at=effective,
                revision_version=rev,
                accounting_standard=row.get("accounting_standard") or "CAS",
                currency=row.get("currency") or "CNY",
                source=row.get("source") or f"CSV 导入 {path}",
                quality_grade=row.get("quality_grade") or "C",
            )
            db.add(period)
            db.flush()
            facts = {}
            for col in FACT_COLS:
                val = row.get(col)
                if val not in (None, ""):
                    facts[col] = float(val)
            db.add(FinancialFactsCanonical(period_id=period.id, **facts))
            n += 1
    db.commit()
    # 导入后自动质量检查（方案 15）
    from app.services.quality import run_quality_checks

    for cid in {r.company_id for r in db.query(FinancialPeriod).all()}:
        run_quality_checks(db, cid)
    return n


if __name__ == "__main__":
    from app.database import SessionLocal, init_db

    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    init_db()
    session = SessionLocal()
    try:
        count = import_financials_csv(session, sys.argv[1])
        print(f"导入 {count} 条报告期数据，并已执行质量检查")
    finally:
        session.close()
