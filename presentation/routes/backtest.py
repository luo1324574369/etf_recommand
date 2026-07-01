from flask import Blueprint, render_template

bp = Blueprint("backtest", __name__, url_prefix="/backtest")


@bp.route("/")
def index():
    return render_template("backtest.html")
