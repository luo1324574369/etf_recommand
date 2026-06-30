import os
import sys
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_PATH, ETF_UNIVERSE
from data.storage.db import init_db, get_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.sources.akshare_source import AkshareDataSource


def update_etf_info(db):
    repo = ETFRepository(db)
    repo.batch_insert(ETF_UNIVERSE)
    print(f"ETF 信息更新完成，共 {len(ETF_UNIVERSE)} 只 ETF")


def update_prices(db, codes=None, full=False):
    etf_repo = ETFRepository(db)
    price_repo = PriceRepository(db)
    data_source = AkshareDataSource()

    if codes:
        etf_list = [etf_repo.get_etf(code) for code in codes]
        etf_list = [etf for etf in etf_list if etf]
    else:
        etf_list = etf_repo.list_etfs(active_only=True)

    end_date = date.today().isoformat()
    total_inserted = 0

    for idx, etf in enumerate(etf_list, 1):
        code = etf["code"]
        name = etf.get("name", code)

        if full:
            start_date = "2018-01-01"
        else:
            latest = price_repo.get_latest_date(code)
            start_date = latest if latest else "2018-01-01"

        print(f"[{idx}/{len(etf_list)} 正在更新 {name} ({code})，起始日期: {start_date}")

        try:
            price_data = data_source.get_daily_price(code, start_date, end_date)
            inserted = price_repo.insert_daily_price(code, price_data)
            total_inserted += inserted
            print(f"  完成，新增 {inserted} 条记录")
        except Exception as e:
            print(f"  更新失败: {e}")

    print(f"\n价格更新完成，共新增 {total_inserted} 条记录")


def main():
    parser = argparse.ArgumentParser(description="ETF 数据更新脚本")
    parser.add_argument("--full", action="store_true", help="全量更新（默认增量）")
    parser.add_argument("--code", type=str, default=None, help="只更新指定 ETF 代码，多个用逗号分隔")
    parser.add_argument("--db", type=str, default=None, help="数据库路径（默认从配置文件）")

    args = parser.parse_args()

    db_path = args.db if args.db else str(DB_PATH)

    print(f"数据库路径: {db_path}")
    print(f"更新模式: {'全量' if args.full else '增量'}")
    if args.code:
        print(f"指定代码: {args.code}")

    init_db(db_path)
    db = get_db(db_path)

    try:
        print("\n=== 更新 ETF 基础信息 ===")
        update_etf_info(db)

        print("\n=== 更新 ETF 价格数据 ===")
        codes = args.code.split(",") if args.code else None
        update_prices(db, codes=codes, full=args.full)
    finally:
        db.close()

    print("\n全部更新完成！")


if __name__ == "__main__":
    main()
