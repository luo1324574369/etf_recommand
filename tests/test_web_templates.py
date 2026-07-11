import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from presentation.app import create_app
from data.storage.db import init_db


def test_pages():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    
    app = create_app(db_path=db_path)
    app.config["TESTING"] = True
    client = app.test_client()

    print("Testing / (home page)...")
    response = client.get("/")
    print(f"  Status: {response.status_code}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert b"ETF Quant" in response.data
    print("  PASSED")

    print("\nTesting /etf/510300 (ETF detail, should be 404)...")
    response = client.get("/etf/510300")
    print(f"  Status: {response.status_code}")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    print("  PASSED (404 as expected, route works)")

    print("\nTesting /backtest/ (backtest page)...")
    response = client.get("/backtest/")
    print(f"  Status: {response.status_code}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert b"\xe7\xad\x96\xe7\x95\xa5\xe5\x9b\x9e\xe6\xb5\x8b" in response.data
    assert b"\xe5\xbc\x80\xe5\xa7\x8b\xe5\x9b\x9e\xe6\xb5\x8b" in response.data
    print("  PASSED")

    print("\nAll tests passed!")
    
    import os
    os.close(db_fd)
    os.unlink(db_path)


if __name__ == "__main__":
    test_pages()
