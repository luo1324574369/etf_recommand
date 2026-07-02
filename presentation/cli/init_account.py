import os
import sys

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import DB_PATH
from data.storage.db import init_db, get_db
from service.portfolio_service import PortfolioService
from presentation.cli import console


def init_account():
    init_db(str(DB_PATH))
    conn = get_db(str(DB_PATH))
    try:
        svc = PortfolioService(conn)

        existing = svc.get_account()
        if existing:
            console.warn(f"账户已存在，初始资金: {existing['initial_capital']} 元")
            return

        print("\n=== 初始化账户 ===\n")
        while True:
            try:
                input_str = input("请输入初始投入资金（元）: ").strip()
                initial = float(input_str)
                if initial <= 0:
                    print("  ✗ 请输入大于 0 的金额")
                    continue
                break
            except ValueError:
                print("  ✗ 请输入有效的数字")

        account = svc.create_account(initial_capital=initial)
        console.success(f"账户已创建，初始资金: {initial} 元，当前现金: {initial} 元")
    finally:
        conn.close()


def main():
    init_account()


if __name__ == "__main__":
    main()
