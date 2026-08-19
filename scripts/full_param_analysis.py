#!/usr/bin/env python
"""运行多因子策略的全量参数分析。"""

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DB_PATH, ETF_UNIVERSE
from data.storage.db import get_db, init_db
from data.storage.price_repo import PriceRepository
from strategy import multi_factor
from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES, optimize_parameters


def load_data(db_path, codes):
    init_db(db_path)
    db = get_db(db_path)
    try:
        repo = PriceRepository(db)
        return {
            code: pd.DataFrame(prices)
            for code in codes
            if (prices := repo.get_daily_price(code))
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="运行多因子策略全量参数分析")
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--max-combinations", type=int, default=144)
    parser.add_argument("--codes", nargs="*", default=None)
    args = parser.parse_args()

    codes = args.codes or [item["code"] for item in ETF_UNIVERSE]
    data_dict = load_data(args.db, codes)
    if not data_dict:
        parser.error("数据库中没有可用行情数据")

    result = optimize_parameters(
        multi_factor,
        data_dict,
        MULTI_FACTOR_PARAM_RANGES,
        start_date=args.start,
        end_date=args.end,
        target_metric="sharpe_ratio",
        max_combinations=args.max_combinations,
    )
    print(f"有效ETF: {len(data_dict)}")
    print(f"参数组合: {result.get('total_combinations', 0)}")
    print(f"最优参数: {result.get('best_params', {})}")


if __name__ == "__main__":
    main()
