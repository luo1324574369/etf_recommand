import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_service(tmp_path, rows):
    from config.settings import ETF_UNIVERSE
    from data.storage.db import get_db, init_db
    from data.storage.etf_repo import ETFRepository
    from data.storage.price_repo import PriceRepository
    from service.application_service import ApplicationService

    db_path = tmp_path / "gate.db"
    init_db(db_path)
    connection = get_db(db_path)
    ETFRepository(connection).insert_etf("510300", "沪深300ETF", "宽基", "指数")
    PriceRepository(connection).insert_daily_price("510300", rows)
    connection.close()
    return ApplicationService(db_path, report_root=tmp_path / "reports")


def test_application_service_blocks_invalid_market_data(tmp_path):
    service = _make_service(tmp_path, [{
        "trade_date": "2025-01-02",
        "open": 5.0,
        "high": 4.0,
        "low": 3.0,
        "close": 4.0,
        "volume": 100,
        "amount": 400,
    }])

    report = service.validate_backtest_data(["510300"], "2025-01-02", "2025-01-02")

    assert report.status == "blocked"
    with pytest.raises(RuntimeError, match="数据质量阻断"):
        service.run_backtest(["510300"], "2025-01-02", "2025-01-02", {}, {})
    service.close()


def test_application_service_saves_passed_snapshot_even_when_end_date_has_no_bar(tmp_path):
    service = _make_service(tmp_path, [{
        "trade_date": "2025-01-02",
        "open": 3.9,
        "high": 4.1,
        "low": 3.8,
        "close": 4.0,
        "volume": 100,
        "amount": 400,
    }])

    report = service.validate_backtest_data(["510300"], "2025-01-02", "2025-01-03")
    snapshot = service.get_market_snapshot(report.snapshot_id)

    assert report.status == "blocked"
    assert snapshot["snapshot_id"] == report.snapshot_id
    assert snapshot["status"] == "blocked"
    service.close()


def test_application_service_archives_report(tmp_path):
    service = _make_service(tmp_path, [{
        "trade_date": "2025-01-02",
        "open": 3.9,
        "high": 4.1,
        "low": 3.8,
        "close": 4.0,
        "volume": 100,
        "amount": 400,
    }])

    report = service.validate_backtest_data(["510300"], "2025-01-02", "2025-01-02")
    paths = service.archive_backtest_report(
        {"final_value": 1_000_000, "trade_list": []},
        {"top_n": 3},
        report,
    )

    assert paths["html"].exists()
    assert paths["data"].exists()
    service.close()


def test_configured_tushare_data_is_used_for_quality_gate(tmp_path, monkeypatch):
    service = _make_service(tmp_path, [{
        "trade_date": "2025-01-02",
        "open": 3.9,
        "high": 4.1,
        "low": 3.8,
        "close": 4.0,
        "volume": 100,
        "amount": 400,
    }])
    source_rows = [{
        "trade_date": "2025-01-03",
        "open": 4.0,
        "high": 4.2,
        "low": 3.9,
        "close": 4.1,
        "adj_factor": 1.0,
        "adjustment_status": "provided",
        "volume": 110,
        "amount": 451,
    }, {
        "trade_date": "2025-01-06",
        "open": 4.1,
        "high": 4.3,
        "low": 4.0,
        "close": 4.2,
        "adj_factor": 1.0,
        "adjustment_status": "provided",
        "volume": 120,
        "amount": 504,
    }]
    service._data_source._tushare = object()
    monkeypatch.setattr(service._data_source, "get_daily_price", lambda *args: source_rows)

    report = service.validate_backtest_data(["510300"], "2025-01-03", "2025-01-03")

    assert report.status == "passed"
    assert service._validated_source_records["510300"] == source_rows
    assert service.get_market_snapshot(report.snapshot_id)["source"] == "tushare_primary_akshare_cross_checked"
    service.close()


def test_holiday_end_date_is_not_treated_as_missing_trade_date(tmp_path):
    service = _make_service(tmp_path, [{
        "trade_date": "2025-04-30",
        "open": 3.9,
        "high": 4.1,
        "low": 3.8,
        "close": 4.0,
        "adj_factor": 1.0,
        "adjustment_status": "provided",
        "volume": 100,
        "amount": 400,
    }, {
        "trade_date": "2025-05-06",
        "open": 4.0,
        "high": 4.2,
        "low": 3.9,
        "close": 4.1,
        "adj_factor": 1.0,
        "adjustment_status": "provided",
        "volume": 110,
        "amount": 451,
    }])

    report = service.validate_backtest_data(["510300"], "2025-04-30", "2025-05-01")

    assert not any(issue.rule == "missing_trade_date" for issue in report.issues)
    service.close()
