from .render import (
    section,
    table_top,
    table_mid,
    table_bot,
    header_row,
    row,
    green,
    red,
    blue,
    bold,
    gray,
)


def _fmt_money(val: float) -> str:
    if val >= 0:
        return green(f"+{val:.2f}")
    else:
        return red(f"{val:.2f}")


def _fmt_pct(val: float) -> str:
    if val >= 0:
        return green(f"+{val:.2%}")
    else:
        return red(f"{val:.2%}")


def render_account_summary(account: dict, total_market_value: float):
    initial = account.get("initial_capital", 0)
    cash = account.get("cash", 0)
    total_asset = cash + total_market_value
    profit = total_asset - initial
    profit_pct = profit / initial if initial > 0 else 0

    print(section("我的账户概览", color="cyan"))
    print(f"  初始投入: {bold(f'{initial:.2f}')} 元")
    print(f"  当前现金: {bold(f'{cash:.2f}')} 元")
    print(f"  持仓市值: {bold(f'{total_market_value:.2f}')} 元")
    print(f"  总资产:   {bold(f'{total_asset:.2f}')} 元")
    print(f"  总盈亏:     {_fmt_money(profit)} ({_fmt_pct(profit_pct)})")
    print()


def render_holdings(holdings: list, etf_name_map: dict, price_map: dict):
    print(section("当前持仓", color="blue"))

    if not holdings:
        print("  暂无持仓")
        print()
        return

    widths = [12, 20, 10, 10, 10, 10, 12]
    print(table_top(widths))
    print(header_row(["代码", "名称", "数量", "成本价", "当前价", "市值", "盈亏"], widths))
    print(table_mid(widths))

    for h in holdings:
        code = h["code"]
        name = etf_name_map.get(code, code)
        qty = h["quantity"]
        cost = h["cost_price"]
        current = price_map.get(code, 0)
        mv = qty * current
        profit = mv - qty * cost
        profit_pct = profit / (qty * cost) if qty * cost > 0 else 0

        profit_str = f"{profit_pct:.2%}"
        if profit_pct >= 0:
            profit_cell = green(profit_str)
        else:
            profit_cell = red(profit_str)

        print(row(
            [code, name, str(qty), f"{cost:.2f}", f"{current:.2f}", f"{mv:.0f}", profit_cell],
            widths,
        ))

    print(table_bot(widths))
    print()


def render_recent_trades(trades: list, etf_name_map: dict):
    print(section("最近交易记录", color="yellow"))

    if not trades:
        print("  暂无交易记录")
        print()
        return

    for t in trades[:10]:
        date = t["trade_date"]
        code = t["code"]
        name = etf_name_map.get(code, code)
        direction = t["direction"]
        qty = t["quantity"]
        price = t["price"]
        fee = t.get("fee", 0)

        dir_text = green("买入") if direction == "buy" else red("卖出")
        print(f"  {gray(date)}  {dir_text}  {blue(code)} {name}  {qty}股  {price}元  手续费{fee}元")

    print()
