from strategy.filters.base import FilterBase


class VolumeFilter(FilterBase):
    name = "volume_filter"

    def __init__(self, min_ratio: float = 1.2):
        self.min_ratio = min_ratio

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        volume = factor_values.get("volume")
        if volume is None:
            return (False, 0.0)
        if volume >= self.min_ratio:
            return (True, volume)
        return (False, volume)
