from config.settings import STRATEGY_CONFIG, DEFAULT_STRATEGY
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.storage.signal_repo import SignalRepository
from strategy.engine import StrategyEngine
from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor
from strategy.filters.trend_filter import TrendFilter
from strategy.filters.momentum_filter import MomentumFilter
from strategy.filters.volume_filter import VolumeFilter

FACTOR_MAP = {
    "MomentumFactor": MomentumFactor,
    "TrendFactor": TrendFactor,
    "VolumeFactor": VolumeFactor,
}

FILTER_MAP = {
    "TrendFilter": TrendFilter,
    "MomentumFilter": MomentumFilter,
    "VolumeFilter": VolumeFilter,
}


def _build_engine(config: dict) -> StrategyEngine:
    factors = []
    for factor_cfg in config.get("factors", []):
        class_name = factor_cfg.get("class") or factor_cfg.get("name")
        if class_name not in FACTOR_MAP:
            continue
        params = {k: v for k, v in factor_cfg.items() if k not in ("class", "name", "weight")}
        factor_cls = FACTOR_MAP[class_name]
        factors.append(factor_cls(**params))

    filters = []
    for filter_cfg in config.get("filters", []):
        class_name = filter_cfg.get("class") or filter_cfg.get("name")
        if class_name not in FILTER_MAP:
            continue
        if filter_cfg.get("enabled") is False:
            continue
        params = {k: v for k, v in filter_cfg.items() if k not in ("class", "name", "enabled")}
        filter_cls = FILTER_MAP[class_name]
        filters.append(filter_cls(**params))

    top_n = config.get("top_n", config.get("position", {}).get("max_positions", 5))
    score_weights = config.get("score_weights", {})

    return StrategyEngine(
        factors=factors,
        filters=filters,
        top_n=top_n,
        score_weights=score_weights,
    )


class StrategyService:
    def __init__(self, db):
        self.db = db
        self.etf_repo = ETFRepository(db)
        self.price_repo = PriceRepository(db)
        self.signal_repo = SignalRepository(db)

    def get_latest_signals(self, strategy_name: str = DEFAULT_STRATEGY):
        signals = self.signal_repo.get_latest_signals(strategy_name)
        signal_date = signals[0]["signal_date"] if signals else None
        return signals, signal_date, strategy_name

    def get_signals_by_date(self, strategy_name: str, signal_date: str, limit: int = None):
        return self.signal_repo.get_signals_by_date(strategy_name, signal_date, limit)

    def list_signal_dates(self, strategy_name: str = DEFAULT_STRATEGY, limit: int = 20):
        return self.signal_repo.list_signal_dates(strategy_name, limit)

    def run_strategy(self, strategy_name: str = DEFAULT_STRATEGY, signal_date: str = None):
        if strategy_name not in STRATEGY_CONFIG:
            raise ValueError(f"Strategy '{strategy_name}' not found in STRATEGY_CONFIG")

        config = STRATEGY_CONFIG[strategy_name]

        etfs = self.etf_repo.list_etfs(active_only=True)
        codes = [etf["code"] for etf in etfs]
        etf_name_map = {etf["code"]: etf.get("name", "") for etf in etfs}

        engine = _build_engine(config)
        results = engine.run(codes, signal_date, self.price_repo)

        signals = []
        for result in results:
            code = result["code"]
            name = etf_name_map.get(code, "")
            rank = result["rank"]
            score = result.get("score", 0)
            factor_values = result.get("factor_values", {})

            reason = {}
            for k, v in factor_values.items():
                if isinstance(v, (int, float, str, bool)):
                    reason[k] = v
                elif isinstance(v, dict):
                    for dk, dv in v.items():
                        if isinstance(dv, (int, float, str, bool)):
                            reason[f"{k}.{dk}"] = dv

            signals.append({
                "signal_date": signal_date,
                "strategy_name": strategy_name,
                "code": code,
                "name": name,
                "rank": rank,
                "score": score,
                "reason": reason,
                "action": "buy",
            })

        if signals:
            self.signal_repo.delete_signals_by_date(strategy_name, signal_date)
            self.signal_repo.batch_save_signals(signals)

        return results, etf_name_map, config
