"""行情快照的结构、价格和跨数据源质量校验。"""

from __future__ import annotations

from collections import Counter
import math
from typing import Any

from data.contracts import DataQualityReport, MarketDataSnapshot, ValidationIssue


PRICE_FIELDS = ("open", "high", "low", "close")


def _relative_difference(first: float, second: float) -> float:
    denominator = max(abs(first), abs(second), 1e-12)
    return abs(first - second) / denominator


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_price_records(
    records_by_code: dict[str, list[dict[str, Any]]],
    expected_dates: list[str] | tuple[str, ...] | None,
    source_name: str,
    as_of_date: str | None = None,
) -> DataQualityReport:
    expected_dates = expected_dates or []
    observed_dates = [
        str(row.get("trade_date", ""))
        for rows in records_by_code.values()
        for row in rows
        if row.get("trade_date")
    ]
    snapshot = MarketDataSnapshot.from_records(
        records_by_code,
        source=source_name,
        as_of_date=as_of_date or max(expected_dates or observed_dates or ["unknown"]),
    )
    expected_date_set = set(expected_dates)
    issues: list[ValidationIssue] = []

    for code, rows in records_by_code.items():
        if not rows:
            issues.append(ValidationIssue(
                rule="missing_price_data",
                code=code,
                message=f"{code} 没有可用行情数据",
                actual=0,
                expected="至少一条有效行情记录",
            ))
            continue
        dates = [str(row.get("trade_date", "")) for row in rows]
        duplicate_dates = sorted(date for date, count in Counter(dates).items() if count > 1)
        if duplicate_dates:
            issues.append(ValidationIssue(
                rule="duplicate_trade_date",
                code=code,
                message=f"{code} 存在重复交易日",
                actual=duplicate_dates,
                expected="每个标的每个交易日最多一条记录",
            ))

        missing_dates = sorted(expected_date_set - set(dates))
        if missing_dates:
            issues.append(ValidationIssue(
                rule="missing_trade_date",
                code=code,
                message=f"{code} 缺少交易日数据",
                actual=missing_dates,
                expected=sorted(expected_date_set),
            ))

        for row in rows:
            trade_date = str(row.get("trade_date", ""))
            values = {field: _number(row.get(field)) for field in PRICE_FIELDS}
            if values["close"] is None:
                issues.append(ValidationIssue(
                    rule="missing_close",
                    code=code,
                    message=f"{code} {trade_date} 缺少收盘价",
                    actual=row.get("close"),
                    expected="有限数值",
                ))
                continue

            if any(value is None for value in values.values()):
                issues.append(ValidationIssue(
                    rule="invalid_price_value",
                    code=code,
                    message=f"{code} {trade_date} 价格字段不是有限数值",
                    actual=values,
                    expected="有限数值",
                ))
                continue

            non_negative_fields = [field for field, value in values.items() if value is not None and value < 0]
            volume = _number(row.get("volume"))
            if non_negative_fields or (volume is not None and volume < 0):
                issues.append(ValidationIssue(
                    rule="negative_market_value",
                    code=code,
                    message=f"{code} {trade_date} 存在负价格或负成交量",
                    actual={"prices": values, "volume": volume},
                    expected="价格和成交量均不小于 0",
                ))

            if all(value is not None for value in values.values()):
                if not (
                    values["low"] <= values["open"] <= values["high"]
                    and values["low"] <= values["close"] <= values["high"]
                ):
                    issues.append(ValidationIssue(
                        rule="ohlc_relation",
                        code=code,
                        message=f"{code} {trade_date} 的 OHLC 关系不成立",
                        actual=values,
                        expected="low <= open/close <= high",
                    ))

    return (
        DataQualityReport.passed(snapshot.snapshot_id)
        if not issues
        else DataQualityReport.blocked(snapshot.snapshot_id, issues)
    )


def compare_price_sources(
    primary: dict[str, list[dict[str, Any]]],
    secondary: dict[str, list[dict[str, Any]]],
    price_tolerance: float = 0.01,
    volume_tolerance: float = 0.10,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    secondary_by_key = {
        (code, str(row.get("trade_date", ""))): row
        for code, rows in secondary.items()
        for row in rows
    }
    for code, rows in primary.items():
        for row in rows:
            trade_date = str(row.get("trade_date", ""))
            other = secondary_by_key.get((code, trade_date))
            if other is None:
                issues.append(ValidationIssue(
                    rule="cross_source_missing",
                    code=code,
                    message=f"{code} {trade_date} 缺少交叉校验数据",
                    actual=None,
                    expected="secondary source row",
                ))
                continue
            primary_close = _number(row.get("close"))
            secondary_close = _number(other.get("close"))
            if primary_close is not None and secondary_close is not None:
                price_difference = _relative_difference(primary_close, secondary_close)
                if price_difference > price_tolerance:
                    issues.append(ValidationIssue(
                        rule="cross_source_price",
                        code=code,
                        message=f"{code} {trade_date} 两源价格差异超过阈值",
                        actual=price_difference,
                        expected=price_tolerance,
                    ))

            primary_volume = _number(row.get("volume"))
            secondary_volume = _number(other.get("volume"))
            if primary_volume is not None and secondary_volume is not None:
                volume_difference = _relative_difference(primary_volume, secondary_volume)
                if volume_difference > volume_tolerance:
                    issues.append(ValidationIssue(
                        rule="cross_source_volume",
                        code=code,
                        message=f"{code} {trade_date} 两源成交量差异超过阈值",
                        actual=volume_difference,
                        expected=volume_tolerance,
                    ))
    return issues
