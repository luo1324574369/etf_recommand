import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from data.sources.hybrid_source import HybridDataSource, ETF_INDEX_MAP
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.etf_repo import ETFRepository
from data.storage.valuation_repo import ValuationRepo
from strategy import dual_momentum, valuation_dca
from strategy.scoring import (
    compute_all_factors,
    zscore_normalize,
    equal_weight_score,
    build_rank_table,
    FACTOR_DIRECTIONS,
    DEFAULT_FACTORS,
    FACTOR_LABELS,
)

TUSHARE_TOKEN = "513fe191b298257675f19e1ff2acb6be83cd43cefb322a918b1e5d2d"
INITIAL_CAPITAL = 1000000

st.set_page_config(page_title="ETF量化策略平台", layout="wide")

st.title("📈 ETF量化策略平台")

db_path = "data/etf.db"
init_db(db_path)
data_source = HybridDataSource(tushare_token=TUSHARE_TOKEN)
price_repo = PriceRepository(get_db(db_path))
etf_repo = ETFRepository(get_db(db_path))
valuation_repo = ValuationRepo(db_path)

with st.sidebar:
    st.header("数据管理")
    if st.button("拉取ETF列表"):
        with st.spinner("正在拉取..."):
            etf_list = data_source.get_etf_list()
            for etf in etf_list[:50]:
                etf_repo.insert_etf(etf['code'], etf['name'])
            st.success(f"已拉取 {len(etf_list)} 只ETF")

    etf_list = etf_repo.list_etfs()
    etf_codes = [e['code'] for e in etf_list]
    selected_codes = st.multiselect("选择ETF", etf_codes, default=["510300", "510500", "512480"])

    start_date = st.date_input("开始日期", datetime(2019, 1, 1))
    end_date = st.date_input("结束日期", datetime(2024, 12, 31))

    if st.button("拉取行情数据"):
        with st.spinner("正在拉取..."):
            prices_by_code = {}
            for code in selected_codes:
                prices = data_source.get_daily_price(
                    code,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d")
                )
                prices_by_code[code] = prices
            price_repo.batch_insert(prices_by_code)
            st.success(f"已拉取 {len(selected_codes)} 只ETF行情数据")

    if st.button("拉取PE历史数据"):
        with st.spinner("正在拉取指数PE历史（5000+条）..."):
            success_count = 0
            for code in selected_codes:
                pe_history = data_source.get_index_pe_history(code)
                if pe_history:
                    valuation_repo.batch_insert_pe_history(code, pe_history)
                    success_count += 1
            st.success(f"已拉取 {success_count}/{len(selected_codes)} 只ETF的PE历史数据")

    st.header("因子配置")
    default_factors = DEFAULT_FACTORS
    selected_factors = st.multiselect(
        "选择因子（等权加权）",
        list(FACTOR_LABELS.keys()),
        default=default_factors,
        format_func=lambda x: FACTOR_LABELS[x],
    )

    st.header("策略参数")
    strategy_type = st.selectbox("策略类型", ["双动量轮动", "估值百分位定投"])
    top_n = st.slider("选择标的数", 1, 5, 3)

tab1, tab2, tab3, tab4 = st.tabs(["推荐列表", "因子明细", "回测结果", "净值曲线"])

with tab1:
    st.subheader("📊 ETF推荐列表（Z-score标准化 · 等权加权）")
    if st.button("生成推荐"):
        with st.spinner("正在计算因子..."):
            etf_factors = {}
            etf_names = {}

            for code in selected_codes:
                prices = price_repo.get_daily_price(code)
                if len(prices) < 60:
                    continue

                # 优先使用真实PE历史百分位，回退到50.0
                pe_pct = valuation_repo.get_pe_percentile(code)
                pe_count = valuation_repo.get_pe_history_count(code)
                factors = compute_all_factors(code, prices, pe_percentile=pe_pct)

                if factors:
                    if pe_count > 0:
                        factors["pe_latest"] = valuation_repo.get_latest_pe(code)
                        factors["pe_history_count"] = float(pe_count)
                    etf_factors[code] = factors
                    etf_info = etf_repo.get_etf(code)
                    etf_names[code] = etf_info.get("name", "") if etf_info else ""

            if not etf_factors:
                st.warning("暂无足够数据，请先拉取行情数据（至少60个交易日）")
            else:
                active_factors = [
                    f for f in selected_factors
                    if any(f in fs for fs in etf_factors.values())
                ]
                zscores = zscore_normalize(etf_factors, active_factors)
                scores = equal_weight_score(zscores, active_factors)
                df = build_rank_table(etf_factors, zscores, scores, etf_names, active_factors)

                st.success(f"共 {len(df)} 只ETF，基于 {len(active_factors)} 个因子 Z-score 标准化后等权加权")
                st.dataframe(df, use_container_width=True)

with tab2:
    st.subheader("🔍 因子说明")
    st.markdown("""
    **因子方向约定**
    - 正向因子（值越高越好）：动量、成交额、股息率
    - 反向因子（值越低越好）：波动率、PE/PB百分位

    **Z-score 标准化**
    - 对每只ETF的因子值做 (x - μ) / σ 计算
    - 反向因子额外乘以 -1，确保所有因子方向一致
    - 极值截断在 [-3, 3] 区间，避免异常值干扰

    **等权加权**
    - 所有选中因子权重相同，简单平均得到综合评分
    - 综合评分越高，排名越靠前
    """)

with tab3:
    st.subheader("🧪 回测结果")
    if st.button("运行回测"):
        with st.spinner("正在回测..."):
            data_dict = {}
            for code in selected_codes:
                prices = price_repo.get_daily_price(code)
                if prices:
                    df = pd.DataFrame(prices)
                    data_dict[code] = df
            
            if strategy_type == "双动量轮动":
                result = dual_momentum.run_backtest(
                    data_dict,
                    initial_capital=INITIAL_CAPITAL,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    top_n=top_n,
                    lookback_short=60,
                    lookback_long=120,
                )
            else:
                result = valuation_dca.run_backtest(
                    data_dict,
                    initial_capital=INITIAL_CAPITAL,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )
            
            metrics = {
                '指标': ['最终市值', '总收益率(%)', '年化收益率(%)', '夏普比率', '最大回撤(%)', '交易次数'],
                '值': [
                    f"{result['final_value']:,.2f}",
                    f"{result['total_return']:.2f}",
                    f"{result['annual_return']:.2f}",
                    f"{result['sharpe_ratio']:.2f}",
                    f"{result['max_drawdown']:.2f}",
                    result['num_trades'],
                ]
            }
            st.dataframe(pd.DataFrame(metrics), use_container_width=True)

with tab4:
    st.subheader("📈 净值曲线")
    if st.button("生成曲线"):
        with st.spinner("正在计算..."):
            data_dict = {}
            for code in selected_codes:
                prices = price_repo.get_daily_price(code)
                if prices:
                    df = pd.DataFrame(prices)
                    data_dict[code] = df
            
            if strategy_type == "双动量轮动":
                nav_df = dual_momentum.get_nav_curve(
                    data_dict,
                    initial_capital=INITIAL_CAPITAL,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    top_n=top_n,
                    lookback_short=60,
                    lookback_long=120,
                )
            else:
                nav_df = valuation_dca.get_nav_curve(
                    data_dict,
                    initial_capital=INITIAL_CAPITAL,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )
            
            fig = px.line(nav_df, x='date', y='nav', 
                         title=f'{strategy_type}策略净值曲线',
                         labels={'nav': '净值', 'date': '日期'},
                         template='plotly_white')
            fig.update_layout(yaxis_range=[0.5, 2.0])
            st.plotly_chart(fig, use_container_width=True)