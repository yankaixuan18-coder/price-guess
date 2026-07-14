"""CSV 数据导入（方案阶段 1：手工或 CSV 导入）。

两种用法：
1. 单文件（仅财务报表，公司需已存在）：
       python -m app.seed.csv_import path/to/financials.csv
2. 数据包目录（可新增整家公司：主数据+财务+股本+行情+分红+同行）：
       python -m app.seed.csv_import --dir path/to/package_dir

数据包目录可包含以下文件（financials.csv 与 companies.csv 必备，其余可选）：
    companies.csv      公司主数据与上市信息
    financials.csv     年报（统一科目，金额=报告币种百万）
    share_counts.csv   股本（单位：百万股）
    prices.csv         收盘价（交易币种）
    dividends.csv      每股分红（报告币种）
    peers.csv          可比公司关系
模板见 app/seed/templates/。重复导入按主键覆盖（幂等），导入后自动执行质量检查。
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    Company,
    DailyPrice,
    Dividend,
    FinancialFactsCanonical,
    FinancialPeriod,
    Listing,
    PeerLink,
    Security,
    ShareCount,
)

META_COLS = {
    "company_id", "fiscal_year", "period_end", "published_at", "effective_at",
    "accounting_standard", "currency", "revision_version", "period_type",
    "source", "quality_grade",
}
FACT_COLS = {c.name for c in FinancialFactsCanonical.__table__.columns} - {"id", "period_id"}


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _f(row: dict, key: str) -> float | None:
    v = row.get(key)
    if v in (None, ""):
        return None
    return float(v)


def _d(row: dict, key: str) -> date | None:
    v = row.get(key)
    return date.fromisoformat(v) if v else None


# ---------------------------------------------------------------------------
# 财务报表
# ---------------------------------------------------------------------------

def import_financials_csv(db: Session, path: str | Path) -> int:
    n = 0
    path = Path(path)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        unknown = set(reader.fieldnames or []) - META_COLS - FACT_COLS
        if unknown:
            raise ValueError(f"无法识别的列（请对照统一科目表）: {sorted(unknown)}")
        for row in reader:
            cid = row["company_id"].strip()
            if db.get(Company, cid) is None:
                raise ValueError(f"公司 {cid} 不存在：请先在 companies.csv 中定义（或使用 --dir 数据包导入）")
            fy = int(row["fiscal_year"])
            rev = int(row.get("revision_version") or 1)
            published = _d(row, "published_at")
            effective = _d(row, "effective_at") or published
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
                period_end=_d(row, "period_end"), published_at=published, effective_at=effective,
                revision_version=rev,
                accounting_standard=row.get("accounting_standard") or "CAS",
                currency=row.get("currency") or "CNY",
                source=row.get("source") or f"CSV 导入 {path.name}",
                quality_grade=row.get("quality_grade") or "C",
            )
            db.add(period)
            db.flush()
            facts = {col: float(row[col]) for col in FACT_COLS if row.get(col) not in (None, "")}
            db.add(FinancialFactsCanonical(period_id=period.id, **facts))
            n += 1
    db.commit()
    return n


# ---------------------------------------------------------------------------
# 主数据 / 股本 / 行情 / 分红 / 同行
# ---------------------------------------------------------------------------

def import_companies_csv(db: Session, path: Path) -> int:
    from app.services.valuation.industry_config import get_industry_config

    n = 0
    for row in _rows(path):
        cid = row["company_id"].strip()
        cfg = get_industry_config(row["industry_code"])
        c = db.get(Company, cid)
        fields = dict(
            name_zh=row["name_zh"], name_en=row.get("name_en") or None,
            industry_code=row["industry_code"], industry_name=cfg.industry_name,
            hq_country=row.get("hq_country") or None,
            fiscal_year_end_month=int(row.get("fiscal_year_end_month") or 12),
            report_currency=row.get("report_currency") or "CNY",
            beta=float(row.get("beta") or 1.0),
            description=row.get("description") or None,
        )
        if c is None:
            db.add(Company(company_id=cid, **fields))
        else:
            for k, v in fields.items():
                setattr(c, k, v)
        sec_id = f"sec_{cid}"
        if db.get(Security, sec_id) is None:
            db.add(Security(security_id=sec_id, company_id=cid, security_type="common",
                            name=row["name_zh"]))
        lst_id = f"lst_{cid}"
        listing = db.get(Listing, lst_id)
        lfields = dict(
            security_id=sec_id, exchange=row.get("exchange") or "",
            market=row["market"], ticker=row.get("ticker") or cid,
            trading_currency=row.get("trading_currency") or row.get("report_currency") or "CNY",
            is_primary=1,
        )
        if listing is None:
            db.add(Listing(listing_id=lst_id, **lfields))
        else:
            for k, v in lfields.items():
                setattr(listing, k, v)
        n += 1
    db.commit()
    return n


def import_share_counts_csv(db: Session, path: Path) -> int:
    n = 0
    for row in _rows(path):
        cid = row["company_id"].strip()
        as_of = _d(row, "as_of")
        db.query(ShareCount).filter_by(company_id=cid, as_of=as_of).delete()
        db.add(ShareCount(
            company_id=cid, as_of=as_of,
            total_shares=float(row["total_shares"]),
            diluted_weighted_shares=_f(row, "diluted_weighted_shares") or float(row["total_shares"]),
        ))
        n += 1
    db.commit()
    return n


def import_prices_csv(db: Session, path: Path) -> int:
    n = 0
    listing_cache: dict[str, Listing] = {}
    for row in _rows(path):
        cid = row["company_id"].strip()
        if cid not in listing_cache:
            lst = db.get(Listing, f"lst_{cid}")
            if lst is None:
                lst = (
                    db.query(Listing).join(Security, Listing.security_id == Security.security_id)
                    .filter(Security.company_id == cid).first()
                )
            if lst is None:
                raise ValueError(f"公司 {cid} 无上市信息，请先导入 companies.csv")
            listing_cache[cid] = lst
        lst = listing_cache[cid]
        trade_date = _d(row, "trade_date")
        db.query(DailyPrice).filter_by(listing_id=lst.listing_id, trade_date=trade_date).delete()
        db.add(DailyPrice(listing_id=lst.listing_id, trade_date=trade_date,
                          close=float(row["close"]), currency=lst.trading_currency))
        n += 1
    db.commit()
    return n


def import_dividends_csv(db: Session, path: Path) -> int:
    n = 0
    for row in _rows(path):
        cid = row["company_id"].strip()
        fy = int(row["fiscal_year"])
        c = db.get(Company, cid)
        db.query(Dividend).filter_by(company_id=cid, fiscal_year=fy).delete()
        dps = float(row["dps"])
        if dps > 0:
            db.add(Dividend(company_id=cid, fiscal_year=fy, dps=dps,
                            currency=row.get("currency") or (c.report_currency if c else "CNY"),
                            ex_date=_d(row, "ex_date")))
        n += 1
    db.commit()
    return n


def import_peers_csv(db: Session, path: Path) -> int:
    n = 0
    for row in _rows(path):
        cid = row["company_id"].strip()
        pid = row["peer_company_id"].strip()
        exists = db.query(PeerLink).filter_by(company_id=cid, peer_company_id=pid).first()
        if exists:
            exists.rule = row.get("rule") or exists.rule
        else:
            db.add(PeerLink(company_id=cid, peer_company_id=pid, rule=row.get("rule") or None))
        n += 1
    db.commit()
    return n


PACKAGE_FILES = [
    ("companies.csv", import_companies_csv),
    ("financials.csv", import_financials_csv),
    ("share_counts.csv", import_share_counts_csv),
    ("prices.csv", import_prices_csv),
    ("dividends.csv", import_dividends_csv),
    ("peers.csv", import_peers_csv),
]


def import_package(db: Session, dir_path: str | Path) -> dict[str, int]:
    """导入数据包目录。返回 {文件名: 行数}。导入后自动执行质量检查（方案 15）。"""
    dir_path = Path(dir_path)
    if not dir_path.is_dir():
        raise ValueError(f"目录不存在: {dir_path}")
    result: dict[str, int] = {}
    touched_companies: set[str] = set()
    for fname, fn in PACKAGE_FILES:
        fpath = dir_path / fname
        if not fpath.exists():
            continue
        result[fname] = fn(db, fpath)
        touched_companies.update(r["company_id"].strip() for r in _rows(fpath) if r.get("company_id"))
    from app.services.quality import run_quality_checks

    for cid in sorted(touched_companies):
        if db.get(Company, cid) is not None:
            run_quality_checks(db, cid)
    return result


if __name__ == "__main__":
    from app.database import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--dir":
            summary = import_package(session, sys.argv[2])
            for fname, count in summary.items():
                print(f"  {fname}: {count} 行")
            print("数据包导入完成，质量检查已执行。可运行估值：POST /valuations/run")
        elif len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
            count = import_financials_csv(session, sys.argv[1])
            from app.services.quality import run_quality_checks

            for (cid,) in session.query(FinancialPeriod.company_id).distinct():
                run_quality_checks(session, cid)
            print(f"导入 {count} 条报告期数据，质量检查已执行")
        else:
            print(__doc__)
            sys.exit(1)
    finally:
        session.close()
