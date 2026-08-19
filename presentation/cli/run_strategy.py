"""运行并持久化策略信号的兼容 CLI 入口。"""

from pathlib import Path

from config.settings import DB_PATH
from service.application_service import ApplicationService


def run_strategy(strategy_name: str, signal_date: str = None, db_path=None):
    """通过 service 层运行策略并返回结果。"""
    path = Path(db_path) if db_path is not None else Path(DB_PATH)
    service = ApplicationService(path)
    try:
        results, _, _ = service.run_strategy(strategy_name, signal_date)
        return results
    finally:
        service.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="运行 ETF 策略并保存信号")
    parser.add_argument("strategy_name")
    parser.add_argument("--signal-date")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    results = run_strategy(args.strategy_name, args.signal_date, args.db)
    print(f"生成信号 {len(results)} 条")


if __name__ == "__main__":
    main()
