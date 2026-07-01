import os
import sys
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DEFAULT_STRATEGY, DB_PATH, STRATEGY_CONFIG
from data.storage.db import init_db, get_db
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


def build_strategy(config: dict) -> StrategyEngine:
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


def run_strategy(strategy_name: str, signal_date: str = None, db_path: str = str(DB_PATH)) -> list[dict]:
    if strategy_name not in STRATEGY_CONFIG:
        raise ValueError(f"Strategy '{strategy_name}' not found in STRATEGY_CONFIG")

    config = STRATEGY_CONFIG[strategy_name]

    if signal_date is None:
        signal_date = date.today().isoformat()

    init_db(db_path)
    db = get_db(db_path)

    try:
        etf_repo = ETFRepository(db)
        price_repo = PriceRepository(db)
        signal_repo = SignalRepository(db)

        etfs = etf_repo.list_etfs(active_only=True)
        codes = [etf["code"] for etf in etfs]
        etf_name_map = {etf["code"]: etf.get("name", "") for etf in etfs}

        engine = build_strategy(config)
        results = engine.run(codes, signal_date, price_repo)

        # 使用命令行界面展示结果
        from presentation.cli.signal import render_signals
        render_signals(results, strategy_name, signal_date, etf_name_map)

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
            signal_repo.delete_signals_by_date(strategy_name, signal_date)
            signal_repo.batch_save_signals(signals)
            from presentation.cli import console
            console.success(f"已保存 {len(signals)} 条信号到数据库")

        # 每次跑策略都自动更新策略说明文档
        from generate_strategy_doc import generate_strategy_doc
        doc_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs",
            "strategy_doc.md",
        )
        os.makedirs(os.path.dirname(doc_path), exist_ok=True)
        generate_strategy_doc(config, doc_path)

        return results
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="ETF 策略运行脚本")
    parser.add_argument("--strategy", type=str, default=DEFAULT_STRATEGY, help=f"策略名，默认: {DEFAULT_STRATEGY}")
    parser.add_argument("--date", type=str, default=None, help="信号日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help=f"数据库路径，默认: {DB_PATH}")

    args = parser.parse_args()

    run_strategy(
        strategy_name=args.strategy,
        signal_date=args.date,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
