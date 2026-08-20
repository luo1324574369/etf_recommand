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
