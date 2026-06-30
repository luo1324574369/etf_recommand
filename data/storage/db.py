import sqlite3
import os


def get_db(db_path) -> sqlite3.Connection:
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path) -> None:
    conn = get_db(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS etf_info (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sector TEXT,
                type TEXT,
                listed_date TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS etf_daily_price (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL NOT NULL,
                volume INTEGER,
                amount REAL,
                PRIMARY KEY (code, trade_date)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_price_trade_date
            ON etf_daily_price (trade_date)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_signal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_date TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                rank INTEGER,
                score REAL,
                reason TEXT,
                action TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_signal_date_strategy
            ON strategy_signal (signal_date, strategy_name)
        """)

        conn.commit()
    finally:
        conn.close()
