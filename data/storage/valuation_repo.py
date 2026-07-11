import sqlite3
from data.storage.db import get_db


class ValuationRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def insert_valuation(self, code: str, trade_date: str, data: dict):
        conn = get_db(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO etf_valuation
                (code, trade_date, pe, pb, ps, dividend_yield, nav, premium_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code,
                trade_date,
                data.get("pe"),
                data.get("pb"),
                data.get("ps"),
                data.get("dividend_yield"),
                data.get("nav"),
                data.get("premium_rate"),
            ))
            conn.commit()
        finally:
            conn.close()

    def batch_insert_valuation(self, valuations: list[dict]):
        conn = get_db(self.db_path)
        try:
            for v in valuations:
                conn.execute("""
                    INSERT OR REPLACE INTO etf_valuation
                    (code, trade_date, pe, pb, ps, dividend_yield, nav, premium_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    v.get("code"),
                    v.get("trade_date"),
                    v.get("pe"),
                    v.get("pb"),
                    v.get("ps"),
                    v.get("dividend_yield"),
                    v.get("nav"),
                    v.get("premium_rate"),
                ))
            conn.commit()
        finally:
            conn.close()

    def get_valuation(self, code: str, end_date: str = None) -> list[dict]:
        conn = get_db(self.db_path)
        try:
            query = "SELECT * FROM etf_valuation WHERE code = ?"
            params = [code]
            if end_date:
                query += " AND trade_date <= ?"
                params.append(end_date)
            query += " ORDER BY trade_date DESC"
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_latest_valuation(self, code: str) -> dict:
        conn = get_db(self.db_path)
        try:
            row = conn.execute("""
                SELECT * FROM etf_valuation
                WHERE code = ? ORDER BY trade_date DESC LIMIT 1
            """, (code,)).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def get_valuation_percentile(self, code: str, metric: str = "pe", end_date: str = None) -> float:
        """从 etf_valuation 表计算百分位（旧接口，数据较少时不可靠）"""
        conn = get_db(self.db_path)
        try:
            query = f"SELECT {metric} FROM etf_valuation WHERE code = ? AND {metric} IS NOT NULL"
            params = [code]
            if end_date:
                query += " AND trade_date <= ?"
                params.append(end_date)
            rows = conn.execute(query, params).fetchall()
            if not rows:
                return 50.0
            values = [float(row[0]) for row in rows]
            values.sort()
            latest = conn.execute(f"""
                SELECT {metric} FROM etf_valuation
                WHERE code = ? AND {metric} IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            """, (code,)).fetchone()
            if not latest or latest[0] is None:
                return 50.0
            latest_val = float(latest[0])
            cnt = sum(1 for v in values if v <= latest_val)
            return (cnt / len(values)) * 100
        finally:
            conn.close()

    # ── 指数PE历史数据 ──────────────────────────────────

    def batch_insert_pe_history(self, code: str, pe_data: list[dict]):
        conn = get_db(self.db_path)
        try:
            conn.executemany("""
                INSERT OR REPLACE INTO index_pe_history
                (code, trade_date, pe, pe_ttm, pe_static, pe_equal, pe_median)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    code,
                    item["trade_date"],
                    item.get("pe"),
                    item.get("pe_ttm"),
                    item.get("pe_static"),
                    item.get("pe_equal"),
                    item.get("pe_median"),
                )
                for item in pe_data
            ])
            conn.commit()
        finally:
            conn.close()

    def get_pe_history(self, code: str, end_date: str = None) -> list[dict]:
        conn = get_db(self.db_path)
        try:
            query = "SELECT * FROM index_pe_history WHERE code = ? AND pe IS NOT NULL"
            params = [code]
            if end_date:
                query += " AND trade_date <= ?"
                params.append(end_date)
            query += " ORDER BY trade_date"
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_pe_percentile(self, code: str, end_date: str = None) -> float:
        """从 index_pe_history 计算PE百分位（基于5000+条历史数据）"""
        conn = get_db(self.db_path)
        try:
            query = "SELECT pe FROM index_pe_history WHERE code = ? AND pe IS NOT NULL"
            params = [code]
            if end_date:
                query += " AND trade_date <= ?"
                params.append(end_date)
            rows = conn.execute(query, params).fetchall()
            if not rows:
                return 50.0

            values = [float(row[0]) for row in rows]
            values.sort()

            latest_query = """
                SELECT pe FROM index_pe_history
                WHERE code = ? AND pe IS NOT NULL
            """
            latest_params = [code]
            if end_date:
                latest_query += " AND trade_date <= ?"
                latest_params.append(end_date)
            latest_query += " ORDER BY trade_date DESC LIMIT 1"

            latest = conn.execute(latest_query, latest_params).fetchone()
            if not latest or latest[0] is None:
                return 50.0

            latest_val = float(latest[0])
            cnt = sum(1 for v in values if v <= latest_val)
            return (cnt / len(values)) * 100
        finally:
            conn.close()

    def get_latest_pe(self, code: str) -> float | None:
        conn = get_db(self.db_path)
        try:
            row = conn.execute("""
                SELECT pe, trade_date FROM index_pe_history
                WHERE code = ? AND pe IS NOT NULL
                ORDER BY trade_date DESC LIMIT 1
            """, (code,)).fetchone()
            return float(row[0]) if row else None
        finally:
            conn.close()

    def get_pe_history_count(self, code: str) -> int:
        conn = get_db(self.db_path)
        try:
            row = conn.execute("""
                SELECT COUNT(*) FROM index_pe_history
                WHERE code = ? AND pe IS NOT NULL
            """, (code,)).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
