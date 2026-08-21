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
                adj_factor REAL NOT NULL DEFAULT 1.0,
                signal_open REAL,
                signal_high REAL,
                signal_low REAL,
                signal_close REAL,
                adjustment_status TEXT NOT NULL DEFAULT 'unavailable',
                adjustment_source TEXT,
                volume INTEGER,
                amount REAL,
                PRIMARY KEY (code, trade_date)
            )
        """)

        _ensure_price_columns(conn)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_price_trade_date
            ON etf_daily_price (trade_date)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS etf_valuation (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                pe REAL,
                pb REAL,
                ps REAL,
                dividend_yield REAL,
                nav REAL,
                premium_rate REAL,
                PRIMARY KEY (code, trade_date)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_valuation_trade_date
            ON etf_valuation (trade_date)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_pe_history (
                code TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                pe REAL,
                pe_ttm REAL,
                pe_static REAL,
                pe_equal REAL,
                pe_median REAL,
                PRIMARY KEY (code, trade_date)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pe_history_code
            ON index_pe_history (code)
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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY,
                name TEXT DEFAULT '主账户',
                initial_capital REAL NOT NULL,
                cash REAL NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 1,
                trade_date TEXT NOT NULL,
                code TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                fee REAL DEFAULT 0,
                note TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_date
            ON trade (trade_date)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trade_code
            ON trade (code)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS holding (
                account_id INTEGER DEFAULT 1,
                code TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                cost_price REAL NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (account_id, code)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_result (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                etf_code TEXT NOT NULL,
                factor_name TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                metrics_json TEXT,
                validated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_data_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                as_of_date TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                records_json TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_validation_etf_factor
            ON validation_result (etf_code, factor_name)
        """)

        conn.commit()
    finally:
        conn.close()


def _ensure_price_columns(conn: sqlite3.Connection) -> None:
    """为已有数据库补齐复权字段，并回填历史记录的默认信号价格。"""
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(etf_daily_price)").fetchall()
    }
    additions = {
        "adj_factor": "REAL NOT NULL DEFAULT 1.0",
        "signal_open": "REAL",
        "signal_high": "REAL",
        "signal_low": "REAL",
        "signal_close": "REAL",
        "adjustment_status": "TEXT NOT NULL DEFAULT 'unavailable'",
        "adjustment_source": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE etf_daily_price ADD COLUMN {name} {definition}")
    conn.execute("""
        UPDATE etf_daily_price
        SET adj_factor = COALESCE(adj_factor, 1.0),
            signal_open = COALESCE(signal_open, open * COALESCE(adj_factor, 1.0)),
            signal_high = COALESCE(signal_high, high * COALESCE(adj_factor, 1.0)),
            signal_low = COALESCE(signal_low, low * COALESCE(adj_factor, 1.0)),
            signal_close = COALESCE(signal_close, close * COALESCE(adj_factor, 1.0))
        WHERE signal_close IS NULL
           OR signal_open IS NULL
           OR signal_high IS NULL
           OR signal_low IS NULL
    """)
