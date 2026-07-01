from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
from datetime import date

from data.storage.db import get_db
from data.storage.portfolio_repo import PortfolioRepository
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository

bp = Blueprint("portfolio", __name__, url_prefix="/portfolio")


@bp.route("/")
def overview():
    """持仓总览页面"""
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        repo = PortfolioRepository(conn)
        etf_repo = ETFRepository(conn)
        price_repo = PriceRepository(conn)

        account = repo.get_account()
        if not account:
            return render_template("portfolio.html", account=None, holdings=[], trades=[])

        holdings = repo.get_all_holdings()
        trades = repo.list_trades(limit=10)

        # 构建 name 和 price 映射
        etf_name_map = {}
        price_map = {}
        for h in holdings:
            code = h["code"]
            etf = etf_repo.get_etf(code)
            etf_name_map[code] = etf["name"] if etf else code
            latest = price_repo.get_latest_price(code)
            price_map[code] = latest["close"] if latest else 0

        for t in trades:
            code = t["code"]
            if code not in etf_name_map:
                etf = etf_repo.get_etf(code)
                etf_name_map[code] = etf["name"] if etf else code

        # 计算总市值和盈亏
        total_mv = sum(h["quantity"] * price_map.get(h["code"], 0) for h in holdings)
        total_profit = (account["cash"] + total_mv) - account["initial_capital"]
        total_profit_pct = total_profit / account["initial_capital"] if account["initial_capital"] > 0 else 0

        # 为每个持仓计算盈亏
        holdings_with_profit = []
        for h in holdings:
            code = h["code"]
            qty = h["quantity"]
            cost = h["cost_price"]
            current = price_map.get(code, 0)
            mv = qty * current
            profit = mv - qty * cost
            profit_pct = profit / (qty * cost) if qty * cost > 0 else 0
            holdings_with_profit.append({
                "code": code,
                "name": etf_name_map.get(code, code),
                "quantity": qty,
                "cost_price": cost,
                "current_price": current,
                "market_value": mv,
                "profit": profit,
                "profit_pct": profit_pct,
            })
    finally:
        conn.close()

    return render_template(
        "portfolio.html",
        account=account,
        holdings=holdings_with_profit,
        trades=trades,
        etf_name_map=etf_name_map,
        total_market_value=total_mv,
        total_profit=total_profit,
        total_profit_pct=total_profit_pct,
        today=date.today().isoformat(),
    )


@bp.route("/init", methods=["POST"])
def init_account():
    """初始化账户"""
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        repo = PortfolioRepository(conn)
        existing = repo.get_account()
        if existing:
            flash("账户已存在", "warning")
            return redirect(url_for("portfolio.overview"))

        initial_capital = float(request.form.get("initial_capital", 10000))
        if initial_capital <= 0:
            flash("请输入有效的初始资金", "error")
            return redirect(url_for("portfolio.overview"))

        repo.create_account(initial_capital=initial_capital)
        flash(f"账户已创建，初始资金 {initial_capital} 元", "success")
    finally:
        conn.close()

    return redirect(url_for("portfolio.overview"))


@bp.route("/buy", methods=["POST"])
def buy():
    """买入"""
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        repo = PortfolioRepository(conn)
        account = repo.get_account()
        if not account:
            flash("请先初始化账户", "error")
            return redirect(url_for("portfolio.overview"))

        code = request.form.get("code")
        quantity = int(request.form.get("quantity"))
        price = float(request.form.get("price"))
        fee = float(request.form.get("fee", 5))
        trade_date = request.form.get("trade_date") or date.today().isoformat()

        total = quantity * price + fee
        if total > account["cash"]:
            flash(f"现金不足，当前现金 {account['cash']:.2f} 元，需要 {total:.2f} 元", "error")
            return redirect(url_for("portfolio.overview"))

        repo.execute_buy(code=code, quantity=quantity, price=price, fee=fee, trade_date=trade_date)
        flash(f"买入成功：{code} {quantity}股 {price}元", "success")
    finally:
        conn.close()

    return redirect(url_for("portfolio.overview"))


@bp.route("/sell", methods=["POST"])
def sell():
    """卖出"""
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        repo = PortfolioRepository(conn)
        account = repo.get_account()
        if not account:
            flash("请先初始化账户", "error")
            return redirect(url_for("portfolio.overview"))

        code = request.form.get("code")
        quantity = int(request.form.get("quantity"))
        price = float(request.form.get("price"))
        fee = float(request.form.get("fee", 5))
        trade_date = request.form.get("trade_date") or date.today().isoformat()

        holding = repo.get_holding(code)
        if not holding or holding["quantity"] < quantity:
            flash(f"持仓不足或未持有 {code}", "error")
            return redirect(url_for("portfolio.overview"))

        repo.execute_sell(code=code, quantity=quantity, price=price, fee=fee, trade_date=trade_date)
        flash(f"卖出成功：{code} {quantity}股 {price}元", "success")
    finally:
        conn.close()

    return redirect(url_for("portfolio.overview"))