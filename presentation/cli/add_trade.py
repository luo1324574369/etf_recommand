import os
import sys
from datetime import date

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import DB_PATH
from data.storage.db import init_db, get_db
from service.portfolio_service import PortfolioService
from service.data_service import DataService
from presentation.cli import console
from presentation.cli.render import blue, bold, green, red, gray


def prompt_choice(prompt: str, options: list) -> str:
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    print(f"  [q] 退出")
    while True:
        choice = input("请选择: ").strip().lower()
        if choice == "q":
            return "quit"
        if choice in [str(i) for i in range(1, len(options) + 1)]:
            return options[int(choice) - 1]
        print("  ✗ 无效选择")


def prompt_float(prompt: str, default: float = None, min_val: float = 0) -> float:
    default_str = f"[默认 {default}]" if default is not None else ""
    while True:
        input_str = input(f"{prompt}（元）{default_str}: ").strip()
        if input_str == "" and default is not None:
            return default
        try:
            val = float(input_str)
            if val < min_val:
                print(f"  ✗ 请输入 >= {min_val} 的值")
                continue
            return val
        except ValueError:
            print("  ✗ 请输入有效的数字")


def prompt_int(prompt: str, default: int = None, max_val: int = None) -> int:
    default_str = f"[默认 {default}]" if default is not None else ""
    max_str = f"[最多 {max_val}]" if max_val is not None else ""
    while True:
        input_str = input(f"{prompt}{default_str}{max_str}: ").strip()
        if input_str == "" and default is not None:
            return default
        try:
            val = int(input_str)
            if val <= 0:
                print("  ✗ 请输入正整数")
                continue
            if max_val is not None and val > max_val:
                print(f"  ✗ 不能超过 {max_val}")
                continue
            return val
        except ValueError:
            print("  ✗ 请输入有效的整数")


def do_buy(portfolio_svc: PortfolioService, data_svc: DataService):
    code = input("请输入ETF代码: ").strip()
    etf = data_svc.get_etf(code)
    if not etf:
        console.error(f"未找到 ETF 代码 {code}")
        return

    name = etf["name"]
    latest_price = data_svc.get_latest_price(code)
    latest_close = latest_price["close"] if latest_price else None
    price_hint = f"最新价: {latest_close:.2f}" if latest_close else "无最新价"
    print(f"  → {blue(code)} {bold(name)} {gray(price_hint)}")

    account = portfolio_svc.get_account()
    if not account:
        console.error("请先初始化账户: python -m presentation.cli.init_account")
        return

    qty = prompt_int("买入数量（股）")
    price = prompt_float("买入价格", default=latest_close)
    fee = prompt_float("手续费", default=5.0, min_val=0)

    total = qty * price + fee
    if total > account["cash"]:
        console.error(f"现金不足，当前现金 {account['cash']:.2f} 元，需要 {total:.2f} 元")
        return

    print(f"\n确认买入:")
    print(f"  代码: {blue(code)} {bold(name)}")
    print(f"  数量: {qty} 股")
    print(f"  价格: {price} 元")
    print(f"  金额: {qty * price:.0f} 元")
    print(f"  手续费: {fee} 元")
    print(f"  合计: {total:.0f} 元")

    confirm = input("\n确认提交？[y/n]: ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    trade_date = date.today().isoformat()
    try:
        portfolio_svc.execute_buy(code=code, quantity=qty, price=price, fee=fee, trade_date=trade_date)
        new_cash = account["cash"] - total
        console.success("买入记录已保存")
        print(f"  当前现金余额: {new_cash:.2f} 元")
    except ValueError as e:
        console.error(str(e))


def do_sell(portfolio_svc: PortfolioService, data_svc: DataService):
    code = input("请输入ETF代码: ").strip()
    holding = portfolio_svc.get_holding(code)
    if not holding:
        console.error(f"未持有 {code}")
        return

    etf = data_svc.get_etf(code)
    name = etf["name"] if etf else code
    latest_price = data_svc.get_latest_price(code)
    latest_close = latest_price["close"] if latest_price else 0

    cost = holding["cost_price"]
    qty = holding["quantity"]
    mv = qty * latest_close
    profit = mv - qty * cost
    profit_pct = profit / (qty * cost) if qty * cost > 0 else 0

    profit_color = green if profit >= 0 else red
    print(f"  → 当前持仓: {qty} 股，成本价 {cost:.2f}，市值 {mv:.0f} 元")
    print(f"  → 预估盈亏: {profit_color(f'{profit:.0f} 元')} ({profit_color(f'{profit_pct:.2%}')})")

    sell_qty = prompt_int("卖出数量（股）", max_val=qty)
    price = prompt_float("卖出价格", default=latest_close)
    fee = prompt_float("手续费", default=5.0, min_val=0)

    sell_amt = sell_qty * price - fee
    sell_profit = sell_qty * price - sell_qty * cost

    print(f"\n确认卖出:")
    print(f"  数量: {sell_qty} 股")
    print(f"  价格: {price} 元")
    print(f"  金额: {sell_qty * price:.0f} 元")
    print(f"  手续费: {fee} 元")
    print(f"  预估盈亏: {green(f'{sell_profit:.0f} 元') if sell_profit >= 0 else red(f'{sell_profit:.0f} 元')}")

    confirm = input("\n确认提交？[y/n]: ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    trade_date = date.today().isoformat()
    try:
        portfolio_svc.execute_sell(code=code, quantity=sell_qty, price=price, fee=fee, trade_date=trade_date)
        account = portfolio_svc.get_account()
        remaining = qty - sell_qty
        console.success("卖出记录已保存")
        print(f"  当前现金余额: {account['cash']:.2f} 元")
        if remaining > 0:
            print(f"  剩余持仓: {remaining} 股")
        else:
            print(f"  已清仓")
    except ValueError as e:
        console.error(str(e))


def show_holdings(portfolio_svc: PortfolioService, data_svc: DataService):
    holdings = portfolio_svc.get_all_holdings()
    if not holdings:
        console.info("暂无持仓")
        return

    print()
    for h in holdings:
        code = h["code"]
        etf = data_svc.get_etf(code)
        name = etf["name"] if etf else code
        latest_price = data_svc.get_latest_price(code)
        latest_close = latest_price["close"] if latest_price else 0
        qty = h["quantity"]
        cost = h["cost_price"]
        mv = qty * latest_close
        profit = mv - qty * cost
        profit_pct = profit / (qty * cost) if qty * cost > 0 else 0

        profit_color = green if profit >= 0 else red
        print(f"  {blue(code)} {bold(name)}: {qty}股 成本{cost:.2f} 现价{latest_close:.2f} 市值{mv:.0f} {profit_color(f'{profit_pct:.2%}')}")
    print()


def main():
    init_db(str(DB_PATH))
    conn = get_db(str(DB_PATH))
    try:
        portfolio_svc = PortfolioService(conn)
        data_svc = DataService(conn)

        account = portfolio_svc.get_account()
        if not account:
            console.warn("请先初始化账户: python -m presentation.cli.init_account")
            return

        print(f"\n=== 添加交易记录 ===")
        print(f"  当前现金: {account['cash']:.2f} 元")

        while True:
            choice = prompt_choice("选择操作:", ["买入", "卖出", "查看当前持仓"])

            if choice == "quit":
                break
            elif choice == "买入":
                do_buy(portfolio_svc, data_svc)
            elif choice == "卖出":
                do_sell(portfolio_svc, data_svc)
            elif choice == "查看当前持仓":
                show_holdings(portfolio_svc, data_svc)
    finally:
        conn.close()

    print("\n再见！\n")


if __name__ == "__main__":
    main()
