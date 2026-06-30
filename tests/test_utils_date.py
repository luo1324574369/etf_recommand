import unittest
from datetime import date

from utils.date import (
    parse_date,
    format_date,
    is_trade_day,
    prev_trade_day,
    next_trade_day,
    shift_trade_days,
    get_weekly_rebalance_date,
)


class TestDateUtils(unittest.TestCase):

    def test_is_trade_day_weekday(self):
        d = date(2026, 6, 30)
        self.assertTrue(is_trade_day(d))

    def test_is_trade_day_weekend(self):
        saturday = date(2026, 6, 27)
        sunday = date(2026, 6, 28)
        self.assertFalse(is_trade_day(saturday))
        self.assertFalse(is_trade_day(sunday))

    def test_prev_trade_day_friday_from_monday(self):
        monday = date(2026, 6, 29)
        friday = date(2026, 6, 26)
        self.assertEqual(prev_trade_day(monday), friday)

    def test_prev_trade_day_midweek(self):
        wednesday = date(2026, 7, 1)
        tuesday = date(2026, 6, 30)
        self.assertEqual(prev_trade_day(wednesday), tuesday)

    def test_next_trade_day_friday(self):
        friday = date(2026, 6, 26)
        monday = date(2026, 6, 29)
        self.assertEqual(next_trade_day(friday), monday)

    def test_next_trade_day_midweek(self):
        monday = date(2026, 6, 29)
        tuesday = date(2026, 6, 30)
        self.assertEqual(next_trade_day(monday), tuesday)

    def test_shift_trade_days_positive(self):
        friday = date(2026, 6, 26)
        wednesday = date(2026, 7, 1)
        self.assertEqual(shift_trade_days(friday, 3), wednesday)

    def test_shift_trade_days_negative(self):
        monday = date(2026, 6, 29)
        last_wednesday = date(2026, 6, 24)
        self.assertEqual(shift_trade_days(monday, -3), last_wednesday)

    def test_get_weekly_rebalance_date(self):
        tuesday = date(2026, 6, 30)
        friday = date(2026, 7, 3)
        self.assertEqual(get_weekly_rebalance_date(tuesday), friday)

    def test_get_weekly_rebalance_date_already_friday(self):
        friday = date(2026, 6, 26)
        self.assertEqual(get_weekly_rebalance_date(friday), friday)

    def test_parse_and_format(self):
        date_str = "2026-06-30"
        d = parse_date(date_str)
        self.assertEqual(format_date(d), date_str)
        self.assertEqual(parse_date(d), d)


if __name__ == "__main__":
    unittest.main()
