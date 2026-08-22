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
    start_date: str | None = None,
    end_date: str | None = None,
    data_version: str = "unknown",
    require_adjustment: bool = False,
    require_next_open: bool = False,
    max_daily_jump: float = 0.30,
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
        start_date=start_date,
        end_date=end_date,
        expected_dates=expected_dates,
        data_version=data_version,
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

        previous_close = None
        previous_date = None

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

            adjustment_status = str(row.get("adjustment_status", "provided" if row.get("adj_factor") is not None else "unavailable"))
            if require_adjustment and adjustment_status != "provided":
                issues.append(ValidationIssue(
                    rule="missing_adjustment_factor",
                    code=code,
                    message=f"{code} {trade_date} 缺少可信复权因子",
                    actual={
                        "adjustment_status": adjustment_status,
                        "adjustment_source": row.get("adjustment_source"),
                    },
                    expected="adjustment_status=provided",
                ))

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
            if volume is None:
                issues.append(ValidationIssue(
                    rule="missing_volume",
                    code=code,
                    message=f"{code} {trade_date} 缺少成交量",
                    actual=row.get("volume"),
                    expected="有限且大于 0 的成交量",
                ))
            elif volume == 0:
                issues.append(ValidationIssue(
                    rule="zero_volume",
                    code=code,
                    message=f"{code} {trade_date} 无成交，疑似停牌或行情不完整",
                    actual=volume,
                    expected="> 0",
                ))
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

            jump_close = values["close"]
            if adjustment_status == "provided":
                adjustment_factor = _number(row.get("adj_factor"))
                if adjustment_factor is not None and adjustment_factor > 0:
                    jump_close *= adjustment_factor
            if previous_close is not None and previous_close > 0:
                jump = abs(jump_close / previous_close - 1)
                if jump > max_daily_jump:
                    issues.append(ValidationIssue(
                        rule="abnormal_price_jump",
                        code=code,
                        message=f"{code} {trade_date} 相对前一交易日价格跳变异常",
                        actual={"from_date": previous_date, "jump": jump},
                        expected={"max_daily_jump": max_daily_jump},
                    ))
            previous_close = jump_close
            previous_date = trade_date

        if require_next_open and end_date:
            future_rows = [
                row for row in rows
                if str(row.get("trade_date", "")) > str(end_date)
            ]
            next_row = min(future_rows, key=lambda row: str(row.get("trade_date", "")), default=None)
            next_open = _number(next_row.get("open")) if next_row else None
            if next_open is None or next_open <= 0:
                observed_dates_for_code = sorted(
                    date for date in dates if date and date != "None"
                )
                latest_available_date = (
                    observed_dates_for_code[-1]
                    if observed_dates_for_code
                    else None
                )
                issues.append(ValidationIssue(
                    rule="missing_next_open",
                    code=code,
                    message=(
                        f"{code} 回测结束日 {end_date} 之后没有有效次日开盘价"
                        f"（最新行情日期：{latest_available_date or '未知'}）"
                    ),
                    actual={
                        "requested_end_date": end_date,
                        "latest_available_date": latest_available_date,
                        "next_open": next_row.get("open") if next_row else None,
                    },
                    expected="end_date 之后第一条记录的 open > 0",
                ))

    return (
        DataQualityReport.passed(snapshot.snapshot_id, snapshot)
        if not issues
        else DataQualityReport.blocked(snapshot.snapshot_id, issues, snapshot)
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
                if (primary_volume == 0) != (secondary_volume == 0):
                    issues.append(ValidationIssue(
                        rule="cross_source_volume_missing",
                        code=code,
                        message=f"{code} {trade_date} 次数据源缺少成交量，未用于差异阻断",
                        actual={"primary": primary_volume, "secondary": secondary_volume},
                        expected="次数据源成交量应为有效正数",
                        severity="warning",
                    ))
                    continue
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
