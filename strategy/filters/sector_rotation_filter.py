from strategy.filters.base import FilterBase


class SectorRotationFilter(FilterBase):
    """行业轮动过滤器：每个板块只保留动量最高的 ETF，避免同板块重复持仓"""
    name = "sector_rotation_filter"

    def __init__(self, top_per_sector: int = 1, sector_map: dict[str, str] = None):
        self.top_per_sector = top_per_sector
        self.sector_map = sector_map or {}
        self._passing_codes: set[str] = set()

    def set_universe(self, all_factor_values: dict[str, dict]) -> None:
        # 按板块分组
        sectors: dict[str, list[tuple[str, float]]] = {}

        for code, factors in all_factor_values.items():
            momentum = factors.get("momentum")
            if momentum is None:
                continue
            sector = self.sector_map.get(code, "其他")
            sectors.setdefault(sector, []).append((code, momentum))

        self._passing_codes = set()
        for sector, items in sectors.items():
            items.sort(key=lambda x: x[1], reverse=True)
            for code, _ in items[:self.top_per_sector]:
                self._passing_codes.add(code)

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        if code in self._passing_codes:
            return (True, 1.0)
        return (False, 0.0)
