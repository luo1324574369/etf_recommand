import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.storage.db import init_db, get_db
from data.storage.portfolio_repo import PortfolioRepository


def test_create_account():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    account = repo.create_account(initial_capital=10000.0)
    assert account["id"] == 1
    assert account["initial_capital"] == 10000.0
    assert account["cash"] == 10000.0

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_get_account():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    account = repo.get_account()
    assert account is not None
    assert account["cash"] == 10000.0

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_update_cash():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.update_cash(new_cash=5000.0)
    account = repo.get_account()
    assert account["cash"] == 5000.0

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_add_trade():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    trade_id = repo.add_trade({
        "trade_date": "2026-07-01",
        "code": "510300",
        "direction": "buy",
        "quantity": 1000,
        "price": 4.12,
        "fee": 5.0,
    })
    assert trade_id == 1

    trades = repo.list_trades(limit=5)
    assert len(trades) == 1
    assert trades[0]["code"] == "510300"

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_list_trades_by_code():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.add_trade({"trade_date": "2026-07-01", "code": "510300", "direction": "buy", "quantity": 1000, "price": 4.12, "fee": 5.0})
    repo.add_trade({"trade_date": "2026-07-02", "code": "159995", "direction": "buy", "quantity": 500, "price": 3.40, "fee": 5.0})

    trades_510300 = repo.get_trades_by_code("510300")
    assert len(trades_510300) == 1

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_get_holding():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    holding = repo.get_holding("510300")
    assert holding is None

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_update_holding():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.update_holding(code="510300", quantity=1000, cost_price=4.12)
    holding = repo.get_holding("510300")
    assert holding is not None
    assert holding["quantity"] == 1000
    assert holding["cost_price"] == 4.12

    repo.update_holding(code="510300", quantity=500, cost_price=4.20)
    holding = repo.get_holding("510300")
    assert holding["quantity"] == 1500
    assert abs(holding["cost_price"] - 4.147) < 0.01

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_get_all_holdings():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.update_holding(code="510300", quantity=1000, cost_price=4.12)
    repo.update_holding(code="159995", quantity=500, cost_price=3.40)

    holdings = repo.get_all_holdings()
    assert len(holdings) == 2

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_delete_holding():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.update_holding(code="510300", quantity=1000, cost_price=4.12)
    repo.delete_holding(code="510300")
    holding = repo.get_holding("510300")
    assert holding is None

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_execute_buy():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.execute_buy(code="510300", quantity=1000, price=4.12, fee=5.0, trade_date="2026-07-01")

    account = repo.get_account()
    assert account["cash"] == 10000.0 - 1000 * 4.12 - 5.0

    holding = repo.get_holding("510300")
    assert holding["quantity"] == 1000
    assert holding["cost_price"] == 4.12

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_execute_sell():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.execute_buy(code="510300", quantity=1000, price=4.12, fee=5.0, trade_date="2026-07-01")
    repo.execute_sell(code="510300", quantity=500, price=4.15, fee=5.0, trade_date="2026-07-05")

    account = repo.get_account()
    expected_cash = 10000.0 - 1000 * 4.12 - 5.0 + 500 * 4.15 - 5.0
    assert abs(account["cash"] - expected_cash) < 0.01

    holding = repo.get_holding("510300")
    assert holding["quantity"] == 500
    assert holding["cost_price"] == 4.12

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_execute_sell_all():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.execute_buy(code="510300", quantity=1000, price=4.12, fee=5.0, trade_date="2026-07-01")
    repo.execute_sell(code="510300", quantity=1000, price=4.15, fee=5.0, trade_date="2026-07-05")

    holding = repo.get_holding("510300")
    assert holding is None

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


if __name__ == "__main__":
    test_create_account()
    test_get_account()
    test_update_cash()
    test_add_trade()
    test_list_trades_by_code()
    test_get_holding()
    test_update_holding()
    test_get_all_holdings()
    test_delete_holding()
    test_execute_buy()
    test_execute_sell()
    test_execute_sell_all()
    print("All account tests passed")
