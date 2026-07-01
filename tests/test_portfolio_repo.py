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


if __name__ == "__main__":
    test_create_account()
    test_get_account()
    test_update_cash()
    print("All account tests passed")
