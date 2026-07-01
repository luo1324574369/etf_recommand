import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.storage.db import init_db, get_db
from data.storage.portfolio_repo import PortfolioRepository


def test_full_workflow():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    # 1. 创建账户
    repo.create_account(initial_capital=10000.0)
    account = repo.get_account()
    assert account["cash"] == 10000.0

    # 2. 买入
    repo.execute_buy(code="510300", quantity=1000, price=4.12, fee=5.0, trade_date="2026-07-01")
    account = repo.get_account()
    expected_cash = 10000.0 - 1000 * 4.12 - 5.0
    assert abs(account["cash"] - expected_cash) < 0.01

    holding = repo.get_holding("510300")
    assert holding["quantity"] == 1000
    assert holding["cost_price"] == 4.12

    # 3. 再买一笔（测试加权平均成本）
    repo.execute_buy(code="510300", quantity=500, price=4.20, fee=5.0, trade_date="2026-07-02")
    holding = repo.get_holding("510300")
    assert holding["quantity"] == 1500
    expected_cost = (1000 * 4.12 + 500 * 4.20) / 1500
    assert abs(holding["cost_price"] - expected_cost) < 0.01

    # 4. 卖出一半
    repo.execute_sell(code="510300", quantity=750, price=4.15, fee=5.0, trade_date="2026-07-05")
    holding = repo.get_holding("510300")
    assert holding["quantity"] == 750
    # 成本价不变
    assert abs(holding["cost_price"] - expected_cost) < 0.01

    # 5. 清仓
    repo.execute_sell(code="510300", quantity=750, price=4.10, fee=5.0, trade_date="2026-07-10")
    holding = repo.get_holding("510300")
    assert holding is None

    # 6. 交易记录应该有 4 条（2次买入 + 2次卖出）
    trades = repo.list_trades(limit=20)
    assert len(trades) == 4

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)
    print("Full workflow test passed")


if __name__ == "__main__":
    test_full_workflow()
