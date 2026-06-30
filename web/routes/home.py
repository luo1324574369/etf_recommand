from flask import Blueprint, render_template, current_app

from config.settings import DEFAULT_STRATEGY
from data.storage.db import get_db
from data.storage.signal_repo import SignalRepository

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        signal_repo = SignalRepository(conn)
        signals = signal_repo.get_latest_signals(DEFAULT_STRATEGY)
        signal_date = signals[0]["signal_date"] if signals else None
        strategy_name = DEFAULT_STRATEGY
    finally:
        conn.close()

    return render_template(
        "index.html",
        signals=signals,
        signal_date=signal_date,
        strategy_name=strategy_name,
    )
