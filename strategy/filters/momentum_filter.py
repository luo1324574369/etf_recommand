from strategy.filters.base import FilterBase


class MomentumFilter(FilterBase):
    name = "momentum_filter"

    def __init__(self, top_pct: float = 0.3, factor_name: str = "momentum"):
        self.top_pct = top_pct
        self.factor_name = factor_name
        self._passing_codes: set[str] = set()

    def set_universe(self, all_factor_values: dict[str, dict]) -> None:
        momentum_list = []
        for code, factors in all_factor_values.items():
            momentum = factors.get(self.factor_name)
            if momentum is not None:
                momentum_list.append((code, momentum))

        momentum_list.sort(key=lambda x: x[1], reverse=True)

        n = max(1, int(len(momentum_list) * self.top_pct))
        self._passing_codes = {code for code, _ in momentum_list[:n]}

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        momentum = factor_values.get(self.factor_name)
        if momentum is None:
            return (False, 0.0)
        if code in self._passing_codes:
            return (True, momentum)
        return (False, momentum)
