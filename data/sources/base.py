class DataSourceBase:
    def get_etf_list(self) -> list[dict]:
        raise NotImplementedError

    def get_daily_price(self, code: str, start_date: str, end_date: str) -> list[dict]:
        raise NotImplementedError

    def get_daily_price_batch(
        self, codes: list[str], start_date: str, end_date: str
    ) -> dict[str, list[dict]]:
        result = {}
        for code in codes:
            try:
                result[code] = self.get_daily_price(code, start_date, end_date)
            except Exception:
                result[code] = []
        return result
