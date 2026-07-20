"""沪深300成分股 + 申万行业分类数据源

严格模式：任何数据获取失败立即抛 RuntimeError，不 fallback。
所有异常信息以"沪深300成分股"开头，便于上层 Brinson 归因识别与定位。
"""
import os
import sqlite3
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from config.settings import BASE_DIR


class CSI300Source:
    """沪深300成分股数据源

    数据缓存到 etf.db.csi300_constituents 表，避免重复 API 调用。
    """

    INDEX_CODE = '000300.SH'  # Tushare 沪深300指数代码

    def __init__(self, db_path: str = None, tushare_token: str = None):
        """初始化

        Args:
            db_path: SQLite 数据库路径，默认使用项目 DB_PATH
            tushare_token: Tushare token，None 时尝试从环境变量 TUSHARE_TOKEN 读取
        """
        if db_path is None:
            db_path = str(BASE_DIR / 'data' / 'etf.db')
        self.db_path = db_path

        token = tushare_token or os.environ.get('TUSHARE_TOKEN', '')
        self._tushare = None
        if token:
            try:
                import tushare as ts
                self._tushare = ts.pro_api(token)
            except Exception:
                # token 无效或 tushare 未安装，留给 fetch_constituents 时抛错
                self._tushare = None

        self._ensure_cache_table()

    def _ensure_cache_table(self):
        """创建缓存表（幂等）"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS csi300_constituents (
                    trade_date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    weight REAL NOT NULL,
                    sw_industry TEXT,
                    PRIMARY KEY (trade_date, code)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_csi300_date "
                "ON csi300_constituents(trade_date)"
            )
            conn.commit()
        finally:
            conn.close()

    def fetch_constituents(self, date: str) -> pd.DataFrame:
        """获取指定日期沪深300成分股 + 权重 + 申万行业

        Args:
            date: 日期 YYYYMMDD 格式

        Returns:
            DataFrame[date, code, weight, sw_industry]

        Raises:
            RuntimeError: Tushare 调用失败、未初始化或返回空数据
        """
        cached = self._fetch_from_cache(date)
        if cached is not None:
            return cached

        if self._tushare is None:
            raise RuntimeError(
                f"沪深300成分股数据获取失败: trade_date={date}. "
                f"Tushare 未初始化（无 token 或导入失败）"
            )

        try:
            df = self._tushare.index_weight(
                index_code=self.INDEX_CODE,
                trade_date=date,
            )
        except Exception as e:
            raise RuntimeError(
                f"沪深300成分股数据获取失败: trade_date={date}. "
                f"Tushare 接口调用异常: {e}"
            ) from e

        if df is None or df.empty:
            raise RuntimeError(
                f"沪深300成分股数据获取失败: trade_date={date}. "
                f"Tushare 返回空数据，请检查积分是否足够（index_weight 需 5000 积分）"
            )

        # Tushare 字段 con_code 为成分股代码
        df = df.rename(columns={'con_code': 'code'})
        df = df[['trade_date', 'code', 'weight']].copy()
        df['sw_industry'] = df['code'].apply(self._get_stock_industry_cached)

        self._write_to_cache(df)
        # 缓存读出统一格式
        return self._fetch_from_cache(date)

    def _fetch_from_cache(self, date: str) -> Optional[pd.DataFrame]:
        """从缓存读取，未命中返回 None"""
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql(
                "SELECT trade_date as date, code, weight, sw_industry "
                "FROM csi300_constituents WHERE trade_date = ?",
                conn, params=(date,)
            )
        finally:
            conn.close()
        if df.empty:
            return None
        return df

    def _write_to_cache(self, df: pd.DataFrame):
        """写入缓存（trade_date + code 主键冲突时忽略）"""
        conn = sqlite3.connect(self.db_path)
        try:
            for _, row in df.iterrows():
                conn.execute(
                    "INSERT OR IGNORE INTO csi300_constituents "
                    "(trade_date, code, weight, sw_industry) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        str(row['trade_date']),
                        str(row['code']),
                        float(row['weight']),
                        row.get('sw_industry') if pd.notna(row.get('sw_industry')) else None,
                    )
                )
            conn.commit()
        finally:
            conn.close()

    def _get_stock_industry_cached(self, code: str) -> Optional[str]:
        """获取股票申万一级行业（无缓存时直接调 Tushare stock_basic）"""
        if self._tushare is None:
            return None
        try:
            df = self._tushare.stock_basic(
                ts_code=code,
                fields='ts_code,industry',
            )
            if df is not None and not df.empty:
                industry = df.iloc[0].get('industry', None)
                if industry is None or (isinstance(industry, float) and pd.isna(industry)):
                    return None
                return str(industry)
        except Exception:
            return None
        return None

    def get_industry_weights(self, date: str) -> Dict[str, float]:
        """获取沪深300按申万行业聚合的权重

        Args:
            date: 日期 YYYYMMDD 格式

        Returns:
            {申万一级行业: 权重和(0~1)}

        Raises:
            RuntimeError: 数据获取失败（透传自 fetch_constituents）
        """
        df = self.fetch_constituents(date)
        df_valid = df[df['sw_industry'].notna() & (df['sw_industry'] != '')]
        if df_valid.empty:
            return {}
        return df_valid.groupby('sw_industry')['weight'].sum().to_dict()
