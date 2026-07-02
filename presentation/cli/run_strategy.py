import os
import sys
import argparse
from datetime import date

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import DEFAULT_STRATEGY, DB_PATH
from data.storage.db import init_db, get_db
from service.strategy_service import StrategyService
from presentation.cli.signal_render import render_signals
from presentation.cli import console


def run_strategy(strategy_name: str = DEFAULT_STRATEGY, signal_date: str = None, db_path: str = str(DB_PATH)) -> list:
    if signal_date is None:
        signal_date = date.today().isoformat()

    init_db(db_path)
    db = get_db(db_path)

    try:
        svc = StrategyService(db)
        results, etf_name_map, config = svc.run_strategy(
            strategy_name=strategy_name,
            signal_date=signal_date,
        )

        render_signals(results, strategy_name, signal_date, etf_name_map)
        console.success(f"已保存 {len(results)} 条信号到数据库")

        doc_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "docs",
            "strategy_doc.md",
        )
        os.makedirs(os.path.dirname(doc_path), exist_ok=True)
        from utils.generate_strategy_doc import generate_strategy_doc
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
