class FilterBase:
    name = ""

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        raise NotImplementedError
