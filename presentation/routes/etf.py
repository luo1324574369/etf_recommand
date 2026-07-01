from flask import Blueprint, render_template, current_app, abort

from data.storage.db import get_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor

bp = Blueprint("etf", __name__, url_prefix="/etf")


@bp.route("/<code>")
def detail(code):
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        etf_repo = ETFRepository(conn)
        etf = etf_repo.get_etf(code)
        if etf is None:
            abort(404)

        price_repo = PriceRepository(conn)
        all_prices = price_repo.get_daily_price(code)
        recent_prices = list(reversed(all_prices[-30:]))

        latest_date = all_prices[-1]["trade_date"] if all_prices else None

        momentum_factor = MomentumFactor(period=20)
        trend_factor = TrendFactor(period=20)
        volume_factor = VolumeFactor(short_period=5, long_period=20)

        momentum_value = None
        trend_value = None
        volume_value = None

        if latest_date:
            momentum_value = momentum_factor.calculate(code, all_prices, latest_date)
            trend_value = trend_factor.calculate(code, all_prices, latest_date)
            volume_value = volume_factor.calculate(code, all_prices, latest_date)

        factors = {
            "momentum": momentum_value,
            "trend": trend_value,
            "volume": volume_value,
        }
    finally:
        conn.close()

    return render_template(
        "etf_detail.html",
        etf=etf,
        recent_prices=recent_prices,
        factors=factors,
    )
