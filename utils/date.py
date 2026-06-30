from datetime import date, timedelta


def parse_date(date_str):
    if isinstance(date_str, date):
        return date_str
    return date.fromisoformat(date_str)


def format_date(d):
    return d.isoformat()


def is_trade_day(d):
    return d.weekday() < 5


def prev_trade_day(d):
    d = parse_date(d)
    delta = 1
    while True:
        candidate = d - timedelta(days=delta)
        if is_trade_day(candidate):
            return candidate
        delta += 1


def next_trade_day(d):
    d = parse_date(d)
    delta = 1
    while True:
        candidate = d + timedelta(days=delta)
        if is_trade_day(candidate):
            return candidate
        delta += 1


def shift_trade_days(d, n):
    d = parse_date(d)
    result = d
    if n > 0:
        for _ in range(n):
            result = next_trade_day(result)
    elif n < 0:
        for _ in range(-n):
            result = prev_trade_day(result)
    return result


def get_weekly_rebalance_date(d):
    d = parse_date(d)
    days_until_friday = 4 - d.weekday()
    if days_until_friday < 0:
        days_until_friday += 7
    return d + timedelta(days=days_until_friday)
