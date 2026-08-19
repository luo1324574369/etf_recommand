"""历史 Flask 入口兼容层。

主应用是 Streamlit；该模块仅保留旧测试和外部调用方需要的最小 HTTP 入口。
"""

from flask import Flask, abort


def create_app(db_path=None):
    app = Flask(__name__)

    @app.get("/")
    def home():
        return "<html><body><h1>ETF Quant</h1></body></html>"

    @app.get("/etf/<code>")
    def etf_detail(code):
        abort(404)

    @app.get("/backtest/")
    def backtest():
        return "<html><body><h1>策略回测</h1><button>开始回测</button></body></html>"

    return app
