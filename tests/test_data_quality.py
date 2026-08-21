import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_price_difference_over_one_percent_blocks():
    from data.quality import compare_price_sources

    issues = compare_price_sources(
        {"510300": [{"trade_date": "2025-01-02", "close": 4.0, "volume": 100}]},
        {"510300": [{"trade_date": "2025-01-02", "close": 4.05, "volume": 100}]},
    )

    assert any(issue.rule == "cross_source_price" for issue in issues)


def test_invalid_ohlc_is_blocked():
    from data.quality import validate_price_records

    report = validate_price_records(
        {"510300": [{"trade_date": "2025-01-02", "open": 5, "high": 4,
                     "low": 3, "close": 4, "volume": 100}]},
        expected_dates=["2025-01-02"],
        source_name="tushare",
    )

    assert report.status == "blocked"
    assert any(issue.rule == "ohlc_relation" for issue in report.issues)


def test_missing_expected_date_is_blocked():
    from data.quality import validate_price_records

    report = validate_price_records(
        {"510300": [{"trade_date": "2025-01-02", "close": 4.0}]},
        expected_dates=["2025-01-02", "2025-01-03"],
        source_name="tushare",
    )

    assert report.status == "blocked"
    assert any(issue.rule == "missing_trade_date" for issue in report.issues)


def test_missing_or_zero_volume_is_blocked():
    from data.quality import validate_price_records

    report = validate_price_records(
        {"510300": [{
            "trade_date": "2025-01-02", "open": 4, "high": 4.1,
            "low": 3.9, "close": 4, "volume": 0,
        }]},
        expected_dates=["2025-01-02"],
        source_name="local_db",
    )

    assert report.status == "blocked"
    assert any(issue.rule == "zero_volume" for issue in report.issues)


def test_abnormal_price_jump_is_blocked():
    from data.quality import validate_price_records

    report = validate_price_records(
        {"510300": [
            {"trade_date": "2025-01-02", "open": 4, "high": 4.1,
             "low": 3.9, "close": 4, "volume": 100},
            {"trade_date": "2025-01-03", "open": 5.5, "high": 5.6,
             "low": 5.4, "close": 5.5, "volume": 100},
        ]},
        expected_dates=["2025-01-02", "2025-01-03"],
        source_name="local_db",
    )

    assert report.status == "blocked"
    assert any(issue.rule == "abnormal_price_jump" for issue in report.issues)


def test_adjustment_is_required_when_signal_prices_are_used():
    from data.quality import validate_price_records

    report = validate_price_records(
        {"510300": [{
            "trade_date": "2025-01-02", "open": 4, "high": 4.1,
            "low": 3.9, "close": 4, "volume": 100,
            "adjustment_status": "unavailable",
        }]},
        expected_dates=["2025-01-02"],
        source_name="local_db",
        require_adjustment=True,
    )

    assert report.status == "blocked"
    assert any(issue.rule == "missing_adjustment_factor" for issue in report.issues)
