import sqlite3

from data.storage.db import init_db, get_db
from data.storage.valuation_repo import ValuationRepo


def test_missing_pe_percentile_is_none(tmp_path):
    db_path = tmp_path / "valuation.db"
    init_db(db_path)
    repo = ValuationRepo(db_path)

    assert repo.get_pe_percentile("510300") is None


def test_missing_valuation_percentile_is_none(tmp_path):
    db_path = tmp_path / "valuation.db"
    init_db(db_path)
    repo = ValuationRepo(db_path)

    assert repo.get_valuation_percentile("510300") is None


def test_valuation_percentile_latest_value_respects_end_date(tmp_path):
    """估值百分位的当前值也必须限制在 end_date 之前。"""
    db_path = tmp_path / "valuation.db"
    init_db(db_path)
    db = get_db(db_path)
    db.execute(
        "INSERT INTO etf_valuation (code, trade_date, pe) VALUES (?, ?, ?)",
        ("510300", "2025-01-01", 10.0),
    )
    db.execute(
        "INSERT INTO etf_valuation (code, trade_date, pe) VALUES (?, ?, ?)",
        ("510300", "2025-02-01", 1.0),
    )
    db.commit()
    db.close()

    repo = ValuationRepo(db_path)
    assert repo.get_valuation_percentile("510300", end_date="2025-01-15") == 100.0
