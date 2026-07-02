import os
import sys
import argparse

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import DB_PATH
from data.storage.db import init_db, get_db
from service.data_service import DataService


def _progress_cb(idx, total, name, code, start_date, result):
    if result is None:
        print(f"[{idx}/{total}] 正在更新 {name} ({code})，起始日期: {start_date}")
    elif isinstance(result, int):
        print(f"  完成，新增 {result} 条记录")
    else:
        print(f"  更新失败: {result}")


def update_data(full: bool = False, codes: list = None, db_path: str = str(DB_PATH)):
    print(f"数据库路径: {db_path}")
    print(f"更新模式: {'全量' if full else '增量'}")
    if codes:
        print(f"指定代码: {','.join(codes)}")

    init_db(db_path)
    db = get_db(db_path)

    try:
        svc = DataService(db)

        print("\n=== 更新 ETF 基础信息 ===")
        count = svc.update_etf_info()
        print(f"ETF 信息更新完成，共 {count} 只 ETF")

        print("\n=== 更新 ETF 价格数据 ===")
        total = svc.update_prices(codes=codes, full=full, on_progress=_progress_cb)
        print(f"\n价格更新完成，共新增 {total} 条记录")
    finally:
        db.close()

    print("\n全部更新完成！")


def main():
    parser = argparse.ArgumentParser(description="ETF 数据更新脚本")
    parser.add_argument("--full", action="store_true", help="全量更新（默认增量）")
    parser.add_argument("--code", type=str, default=None, help="只更新指定 ETF 代码，多个用逗号分隔")
    parser.add_argument("--db", type=str, default=None, help="数据库路径（默认从配置文件）")

    args = parser.parse_args()
    db_path = args.db if args.db else str(DB_PATH)
    codes = args.code.split(",") if args.code else None

    update_data(full=args.full, codes=codes, db_path=db_path)


if __name__ == "__main__":
    main()
