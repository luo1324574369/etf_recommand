from flask import Flask

from config.settings import DB_PATH, WEB_CONFIG
from presentation.routes.home import bp as home_bp
from presentation.routes.etf import bp as etf_bp
from presentation.routes.backtest import bp as backtest_bp
from presentation.routes.cmd import bp as cmd_bp
from presentation.routes.portfolio import bp as portfolio_bp


def create_app(db_path=None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path) if db_path else str(DB_PATH)
    app.secret_key = "etf-quant-secret"

    app.register_blueprint(home_bp)
    app.register_blueprint(etf_bp)
    app.register_blueprint(backtest_bp)
    app.register_blueprint(cmd_bp)
    app.register_blueprint(portfolio_bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=WEB_CONFIG["host"],
        port=WEB_CONFIG["port"],
        debug=WEB_CONFIG["debug"],
    )
