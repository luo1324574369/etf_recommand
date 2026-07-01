from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
from datetime import date

from data.storage.db import get_db
from service import PortfolioService

bp = Blueprint("portfolio", __name__, url_prefix="/portfolio")


@bp.route("/")
def overview():
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        svc = PortfolioService(conn)
        ov = svc.get_portfolio_overview(trade_limit=10)
    finally:
        conn.close()

    return render_template(
        "portfolio.html",
        account=ov["account"],
        holdings=ov["holdings"],
        trades=ov["trades"],
        etf_name_map=ov["etf_name_map"],
        total_market_value=ov["total_market_value"],
        total_profit=ov["total_profit"],
        total_profit_pct=ov["total_profit_pct"],
        today=date.today().isoformat(),
    )


@bp.route("/init", methods=["POST"])
def init_account():
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        svc = PortfolioService(conn)
        existing = svc.get_account()
        if existing:
            flash("账户已存在", "warning")
            return redirect(url_for("portfolio.overview"))

        initial_capital = float(request.form.get("initial_capital", 10000))
        if initial_capital <= 0:
            flash("请输入有效的初始资金", "error")
            return redirect(url_for("portfolio.overview"))

        svc.create_account(initial_capital=initial_capital)
        flash(f"账户已创建，初始资金 {initial_capital} 元", "success")
    finally:
        conn.close()

    return redirect(url_for("portfolio.overview"))


@bp.route("/buy", methods=["POST"])
def buy():
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        svc = PortfolioService(conn)

        code = request.form.get("code")
        quantity = int(request.form.get("quantity"))
        price = float(request.form.get("price"))
        fee = float(request.form.get("fee", 5))
        trade_date = request.form.get("trade_date") or date.today().isoformat()

        try:
            svc.execute_buy(code=code, quantity=quantity, price=price, fee=fee, trade_date=trade_date)
            flash(f"买入成功：{code} {quantity}股 {price}元", "success")
        except ValueError as e:
            flash(str(e), "error")
    finally:
        conn.close()

    return redirect(url_for("portfolio.overview"))


@bp.route("/sell", methods=["POST"])
def sell():
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        svc = PortfolioService(conn)

        code = request.form.get("code")
        quantity = int(request.form.get("quantity"))
        price = float(request.form.get("price"))
        fee = float(request.form.get("fee", 5))
        trade_date = request.form.get("trade_date") or date.today().isoformat()

        try:
            svc.execute_sell(code=code, quantity=quantity, price=price, fee=fee, trade_date=trade_date)
            flash(f"卖出成功：{code} {quantity}股 {price}元", "success")
        except ValueError as e:
            flash(str(e), "error")
    finally:
        conn.close()

    return redirect(url_for("portfolio.overview"))
