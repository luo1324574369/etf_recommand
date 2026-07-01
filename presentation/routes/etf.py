from flask import Blueprint, render_template, current_app, abort

from data.storage.db import get_db
from service import DataService

bp = Blueprint("etf", __name__, url_prefix="/etf")


@bp.route("/<code>")
def detail(code):
    db_path = current_app.config["DB_PATH"]
    conn = get_db(db_path)
    try:
        svc = DataService(conn)
        result = svc.get_etf_detail(code)
        if result is None:
            abort(404)
    finally:
        conn.close()

    return render_template(
        "etf_detail.html",
        etf=result["etf"],
        recent_prices=result["recent_prices"],
        factors=result["factors"],
    )
