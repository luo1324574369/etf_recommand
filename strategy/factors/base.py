class FactorBase:
    name = ""
    description = ""

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        raise NotImplementedError
