"""沪深300成分股 + 申万行业分类数据源

严格模式：任何数据获取失败立即抛 RuntimeError，不 fallback。
所有异常信息以"沪深300成分股"开头，便于上层 Brinson 归因识别与定位。

数据源：
- 成分股+权重: AkShare ak.index_stock_cons_weight_csindex（免费，无需积分）
- 股票行业分类: Tushare stock_basic（仅需120积分）
- 行业映射: Tushare 二级行业 → 申万一级行业（静态映射表）
"""
import sqlite3
from typing import Dict, Optional

import pandas as pd

from config.settings import BASE_DIR, TUSHARE_TOKEN


# Tushare 二级行业 → 申万一级行业 映射
# 用于将 CSI 300 成分股的 Tushare 行业归类到 SW first-level
# 与 strategy/backtest_utils.py 中 ETF_SECTOR_TO_SW 的 SW first-level 对齐
TUSHARE_INDUSTRY_TO_SW = {
    # 电子
    '半导体': '电子', '元器件': '电子', '电器仪表': '电子',
    # 通信
    '通信设备': '通信', '电信运营': '通信',
    # 计算机
    'IT设备': '计算机', '软件服务': '计算机', '互联网': '计算机',
    # 银行
    '银行': '银行',
    # 非银金融
    '证券': '非银金融', '保险': '非银金融', '多元金融': '非银金融',
    # 食品饮料
    '白酒': '食品饮料', '啤酒': '食品饮料', '乳制品': '食品饮料',
    '软饮料': '食品饮料', '食品': '食品饮料', '饲料': '农林牧渔',
    # 医药生物
    '化学制药': '医药生物', '中成药': '医药生物', '生物制药': '医药生物',
    '医疗保健': '医药生物', '医药商业': '医药生物',
    # 有色金属
    '小金属': '有色金属', '铜': '有色金属', '铝': '有色金属', '黄金': '有色金属',
    # 电力设备
    '电气设备': '电力设备',
    # 机械设备
    '专用机械': '机械设备', '工程机械': '机械设备', '化工机械': '机械设备',
    '运输设备': '机械设备',
    # 汽车
    '汽车整车': '汽车', '汽车配件': '汽车',
    # 公用事业
    '水力发电': '公用事业', '火力发电': '公用事业', '新型电力': '公用事业',
    '供气供热': '公用事业',
    # 交通运输
    '铁路': '交通运输', '水运': '交通运输', '空运': '交通运输',
    '仓储物流': '交通运输', '机场': '交通运输', '港口': '交通运输',
    '路桥': '交通运输',
    # 基础化工
    '化工原料': '基础化工', '农药化肥': '基础化工', '化纤': '基础化工',
    # 建筑装饰
    '建筑工程': '建筑装饰',
    # 建筑材料
    '玻璃': '建筑材料', '水泥': '建筑材料',
    # 钢铁
    '普钢': '钢铁', '特种钢': '钢铁',
    # 煤炭
    '煤炭开采': '煤炭',
    # 石油石化
    '石油开采': '石油石化', '石油加工': '石油石化',
    # 农林牧渔
    '农业综合': '农林牧渔',
    # 房地产
    '全国地产': '房地产', '区域地产': '房地产',
    # 社会服务
    '旅游服务': '社会服务',
    # 商贸零售
    '商品城': '商贸零售',
    # 传媒
    '影视音像': '传媒',
    # 轻工制造
    '广告包装': '轻工制造',
    # 国防军工
    '航空': '国防军工', '船舶': '国防军工',
    # 家用电器
    '家用电器': '家用电器',
}


class CSI300Source:
    """沪深300成分股数据源

    数据缓存到 etf.db.csi300_constituents 表，避免重复 API 调用。

    数据源说明：
    - 成分股+权重: AkShare（免费）
    - 行业分类: Tushare stock_basic（仅需120积分）
    - 不再依赖 Tushare index_weight（需5000积分）
    """

    INDEX_CODE = '000300'  # 中证指数公司代码

    def __init__(self, db_path: str = None, tushare_token: str = None):
        """初始化

        Args:
            db_path: SQLite 数据库路径，默认使用项目 DB_PATH
            tushare_token: Tushare token（仅需120积分用于 stock_basic）
        """
        if db_path is None:
            db_path = str(BASE_DIR / 'data' / 'etf.db')
        self.db_path = db_path

        token = tushare_token or TUSHARE_TOKEN
        self._tushare = None
        if token:
            try:
                import tushare as ts
                ts.set_token(token)
                self._tushare = ts.pro_api()
            except Exception:
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
        """获取指定日期沪深300成分股 + 权重 + 申万一级行业

        使用 AkShare 获取成分股+权重（免费），Tushare stock_basic 获取行业（120积分）。
        注意：AkShare 返回最新成分股数据，非历史快照。缓存后不重复调用。

        Args:
            date: 日期 YYYYMMDD 格式（用于缓存 key）

        Returns:
            DataFrame[date, code, weight, sw_industry]

        Raises:
            RuntimeError: 数据获取失败
        """
        cached = self._fetch_from_cache(date)
        if cached is not None:
            return cached

        # AkShare 获取成分股+权重
        try:
            import akshare as ak
            cons_df = ak.index_stock_cons_weight_csindex(symbol=self.INDEX_CODE)
        except Exception as e:
            raise RuntimeError(
                f"沪深300成分股数据获取失败: trade_date={date}. "
                f"AkShare 接口调用异常: {e}"
            ) from e

        if cons_df is None or cons_df.empty:
            raise RuntimeError(
                f"沪深300成分股数据获取失败: trade_date={date}. "
                f"AkShare 返回空数据"
            )

        # 统一代码格式为 6 位
        cons_df = cons_df.copy()
        cons_df['code'] = cons_df['成分券代码'].str.replace('.SH', '').str.replace('.SZ', '')
        cons_df = cons_df[['code', '权重']].rename(columns={'权重': 'weight'})
        cons_df['trade_date'] = date

        # Tushare stock_basic 获取行业（仅需120积分，批量获取）
        stock_industry_map = self._fetch_stock_industries()

        # 映射到申万一级行业
        cons_df['sw_industry'] = cons_df['code'].apply(
            lambda c: self._map_to_sw_industry(c, stock_industry_map)
        )

        self._write_to_cache(cons_df[['trade_date', 'code', 'weight', 'sw_industry']])
        return self._fetch_from_cache(date)

    def _fetch_stock_industries(self) -> Dict[str, str]:
        """通过 Tushare stock_basic 批量获取所有股票行业（仅需120积分）

        Returns:
            {code6: tushare_industry}
        """
        if self._tushare is None:
            raise RuntimeError(
                "沪深300行业数据获取失败: Tushare 未初始化（无 token 或导入失败）。"
                "stock_basic 仅需 120 积分。"
            )

        try:
            df = self._tushare.stock_basic(
                exchange='', list_status='L', fields='ts_code,industry'
            )
        except Exception as e:
            raise RuntimeError(
                f"沪深300行业数据获取失败: Tushare stock_basic 调用异常: {e}"
            ) from e

        if df is None or df.empty:
            raise RuntimeError(
                "沪深300行业数据获取失败: Tushare stock_basic 返回空数据"
            )

        result = {}
        for _, row in df.iterrows():
            code6 = str(row['ts_code']).replace('.SH', '').replace('.SZ', '')
            industry = row.get('industry')
            if industry and not (isinstance(industry, float) and pd.isna(industry)):
                result[code6] = str(industry)
        return result

    @staticmethod
    def _map_to_sw_industry(code: str, stock_industry_map: Dict[str, str]) -> Optional[str]:
        """将股票的 Tushare 二级行业映射到申万一级行业"""
        tushare_industry = stock_industry_map.get(code)
        if not tushare_industry:
            return None
        return TUSHARE_INDUSTRY_TO_SW.get(tushare_industry)

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

    def get_industry_weights(self, date: str) -> Dict[str, float]:
        """获取沪深300按申万一级行业聚合的权重

        Args:
            date: 日期 YYYYMMDD 格式

        Returns:
            {申万一级行业: 权重和(0~100)}

        Raises:
            RuntimeError: 数据获取失败（透传自 fetch_constituents）
        """
        df = self.fetch_constituents(date)
        df_valid = df[df['sw_industry'].notna() & (df['sw_industry'] != '')]
        if df_valid.empty:
            return {}
        return df_valid.groupby('sw_industry')['weight'].sum().to_dict()
