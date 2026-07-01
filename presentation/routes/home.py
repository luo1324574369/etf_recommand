from flask import Blueprint, render_template, current_app

from data.storage.db import get_db
from service import StrategyService

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        svc = StrategyService(conn)
        signals, signal_date, strategy_name = svc.get_latest_signals()
    finally:
        conn.close()

    return render_template(
        "index.html",
        signals=signals,
        signal_date=signal_date,
        strategy_name=strategy_name,
    )
