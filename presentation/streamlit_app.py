import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from data.sources.hybrid_source import HybridDataSource, ETF_INDEX_MAP
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.etf_repo import ETFRepository
from data.storage.valuation_repo import ValuationRepo
from strategy.scoring import (
    compute_all_factors,
    zscore_normalize,
    compute_factor_history,
    FACTOR_DIRECTIONS,
    FACTOR_LABELS,
)
from service.data_service import ensure_data_ready
from config.settings import ETF_UNIVERSE, DB_PATH, PARAM_PRESETS
from strategy.benchmark import PRIMARY_BENCHMARK
from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS

TUSHARE_TOKEN = "8f5a3c76e085ad6b24e4a248664f88c8a3a0a4fb716a04977a2bc7d0"
INITIAL_CAPITAL = 1000000
db_path = DB_PATH

REBALANCE_FREQ_OPTIONS = {
    "5日（周线）": 5,
    "10日（半月）": 10,
    "20日（月线）": 20,
    "60日（季线）": 60,
    "120日（半年线）": 120,
    "250日（年线）": 250,
}

st.set_page_config(page_title="ETF量化策略平台", layout="wide")

st.title("📈 ETF量化策略平台")

init_db(db_path)
data_source = HybridDataSource(tushare_token=TUSHARE_TOKEN)
price_repo = PriceRepository(get_db(db_path))
etf_repo = ETFRepository(get_db(db_path))
valuation_repo = ValuationRepo(db_path)


def run_backtest_for_result(selected_codes, start_date, end_date, params, constraints_dict):
    data_dict = {}
    for code in selected_codes:
        prices = price_repo.get_daily_price(code)
        if prices:
            df = pd.DataFrame(prices)
            data_dict[code] = df

    full_params = {**params, 'constraints': constraints_dict}
    full_params['valuation_repo'] = valuation_repo

    from strategy import multi_factor
    result = multi_factor.run_backtest(
        data_dict,
        initial_capital=INITIAL_CAPITAL,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        **full_params,
    )
    return result


def build_trade_table(trade_list):
    if not trade_list:
        return pd.DataFrame()

    rows = []
    for t in trade_list:
        code = t.get('code', '')
        etf_info = etf_repo.get_etf(code)
        name = etf_info.get('name', '') if etf_info else ''
        direction = t.get('direction', '')
        if direction == '买入':
            direction_display = '🟢 买入'
        elif direction == '卖出':
            direction_display = '🔴 卖出'
        else:
            direction_display = direction

        rows.append({
            '日期': t.get('date', ''),
            '代码': code,
            '名称': name,
            '方向': direction_display,
            '数量': t.get('quantity', 0),
            '价格': round(t.get('price', 0), 3),
            '金额': round(t.get('amount', 0), 2),
            '手续费': round(t.get('fee', 0), 2),
            '持仓后': t.get('position_after', 0),
            '当笔盈亏': round(t.get('pnl', 0), 2),
            '累计盈亏': round(t.get('cumulative_pnl', 0), 2),
            '调仓原因': t.get('reason', ''),
        })

    return pd.DataFrame(rows)


def _fmt_metric(val):
    """格式化绩效指标值"""
    if val is None:
        return '-'
    if isinstance(val, float):
        if val == float('inf'):
            return '∞'
        return f'{val:.2f}'
    return str(val)


def _status_label(status: str) -> str:
    if status == "pass":
        return "✅ 通过"
    elif status == "warning":
        return "⚠️ 警告"
    elif status == "fail":
        return "❌ 失败"
    elif status == "skip":
        return "⏭️ 跳过"
    return status


def compute_factor_snapshot(selected_codes):
    etf_factors = {}
    etf_names = {}
    active_factors = []

    for code in selected_codes:
        prices = price_repo.get_daily_price(code)
        if len(prices) < 60:
            continue

        pe_pct = valuation_repo.get_pe_percentile(code)
        factors = compute_all_factors(code, prices, pe_percentile=pe_pct)

        if factors:
            etf_factors[code] = factors
            etf_info = etf_repo.get_etf(code)
            etf_names[code] = etf_info.get("name", "") if etf_info else ""
            for f in factors.keys():
                if f not in active_factors:
                    active_factors.append(f)

    if not etf_factors:
        return {}, {}, [], {}

    zscores = zscore_normalize(etf_factors, active_factors)
    return etf_factors, zscores, active_factors, etf_names


@st.dialog("ETF详情", width="large")
def show_etf_detail(code):
    etf_info = etf_repo.get_etf(code)
    name = etf_info.get('name', '') if etf_info else ''
    st.subheader(f"{code} · {name}")

    selected_codes = st.session_state.get('selected_codes', [code])
    if code not in selected_codes:
        selected_codes = [code] + list(selected_codes)

    etf_factors, zscores, active_factors, etf_names = compute_factor_snapshot(selected_codes)

    st.markdown("#### 因子快照")
    if code in etf_factors and active_factors:
        snapshot_rows = []
        for f in active_factors:
            raw_val = etf_factors[code].get(f)
            z_val = zscores.get(code, {}).get(f)
            direction = FACTOR_DIRECTIONS.get(f, 1)
            label = FACTOR_LABELS.get(f, f)

            if z_val is not None:
                if direction == 1:
                    status = "🟢 有利" if z_val > 0 else "🔴 不利"
                else:
                    status = "🟢 有利" if z_val < 0 else "🔴 不利"
            else:
                status = "-"

            if raw_val is not None:
                if f == "avg_amount_20d":
                    raw_display = f"{round(raw_val / 10000, 0):,.0f} 万"
                else:
                    raw_display = f"{round(raw_val, 2)}"
            else:
                raw_display = "-"

            z_display = f"{round(z_val, 2)}" if z_val is not None else "-"
            direction_display = "正向↑" if direction == 1 else "反向↓"

            snapshot_rows.append({
                '因子名称': label,
                '原始值': raw_display,
                'Z-score': z_display,
                '方向': direction_display,
                '状态': status,
            })
        st.dataframe(pd.DataFrame(snapshot_rows), use_container_width=True, hide_index=True)
    else:
        st.info("暂无足够因子数据")

    st.markdown("#### 因子历史走势")
    factor_options = [FACTOR_LABELS.get(f, f) for f in active_factors]
    if factor_options:
        selected_factor_label = st.selectbox("选择因子", factor_options, key="detail_factor_select")
        factor_map = {FACTOR_LABELS.get(f, f): f for f in active_factors}
        selected_factor = factor_map.get(selected_factor_label)

        if selected_factor:
            prices = price_repo.get_daily_price(code)
            pe_history = valuation_repo.get_pe_history(code) if selected_factor in ['pe_percentile', 'pb_percentile'] else None
            hist_df = compute_factor_history(code, prices, [selected_factor], pe_history=pe_history)
            if not hist_df.empty and selected_factor in hist_df.columns:
                fig = px.line(
                    hist_df,
                    x='date',
                    y=selected_factor,
                    title=f"{selected_factor_label} 历史走势",
                    labels={'date': '日期', selected_factor: selected_factor_label},
                    template='plotly_white',
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("暂无历史走势数据")
    else:
        st.info("暂无可用因子")

    st.markdown("#### 本次回测交易记录")
    result = st.session_state.get('result')
    if result and result.get('trade_list'):
        code_trades = [t for t in result['trade_list'] if t.get('code') == code]
        if code_trades:
            trade_df = build_trade_table(code_trades)
            st.dataframe(trade_df, use_container_width=True, hide_index=True)
        else:
            st.info("该ETF在本次回测中无交易记录")
    else:
        st.info("请先运行回测以查看交易记录")

    if st.button("关闭", use_container_width=True):
        st.rerun()


with st.sidebar:
    st.subheader("📊 ETF选择")
    etf_pool = ETF_UNIVERSE
    etf_options = {f"{e['code']} - {e['name']}": e['code'] for e in etf_pool}
    all_labels = list(etf_options.keys())

    default_codes = ["510300", "510500", "512480"]
    available_defaults = [c for c in default_codes if c in etf_options.values()]
    if not available_defaults and etf_pool:
        available_defaults = [etf_pool[0]['code'], etf_pool[1]['code'], etf_pool[2]['code']]
    default_labels = [k for k, v in etf_options.items() if v in available_defaults]

    if 'etf_multiselect' not in st.session_state:
        st.session_state['etf_multiselect'] = default_labels

    def select_all_etfs():
        st.session_state['etf_multiselect'] = list(all_labels)

    def clear_all_etfs():
        st.session_state['etf_multiselect'] = []

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        st.button("全选", use_container_width=True, key="btn_select_all", on_click=select_all_etfs)
    with col_sel2:
        st.button("清空", use_container_width=True, key="btn_clear_all", on_click=clear_all_etfs)

    selected_labels = st.multiselect(
        "选择ETF",
        all_labels,
        key="etf_multiselect",
    )
    selected_codes = [etf_options[l] for l in selected_labels]
    st.session_state['selected_codes'] = selected_codes
    st.caption(f"已选择 {len(selected_codes)} 只ETF")

    st.markdown("---")
    st.subheader("📅 日期范围")
    start_date = st.date_input("开始日期", datetime(2019, 1, 1))
    end_date = st.date_input("结束日期", datetime(2024, 12, 31))

    st.markdown("---")
    st.subheader("⚙️ 策略参数")
    st.caption("多因子轮动策略：动量 + 估值 + 低波动 等权合成")

    dynamic_presets = st.session_state.get('dynamic_presets', {}).get('多因子轮动', [])
    if dynamic_presets:
        preset_options = list(dynamic_presets)
    else:
        presets = PARAM_PRESETS.get('多因子轮动', [])
        preset_options = [
            {"name": p["name"], "params": p["params"], "is_dynamic": False}
            for p in presets
        ]

    preset_names = [p["name"] for p in preset_options]
    preset_select = st.selectbox("参数预设", preset_names, index=0, key="preset_select")
    selected_preset = next((p for p in preset_options if p["name"] == preset_select), None)
    preset_params = selected_preset.get("params") if selected_preset else None
    is_custom = preset_params is None

    if is_custom:
        lookback_momentum = st.slider("动量回看(日)", 10, 120, 60)
        lookback_volatility = st.slider("波动率回看(日)", 10, 120, 60)
        top_n = st.slider("选择标的数", 1, 10, 3)
        rebalance_label = st.selectbox(
            "调仓频率",
            list(REBALANCE_FREQ_OPTIONS.keys()),
            index=2,
        )
        rebalance_days = REBALANCE_FREQ_OPTIONS[rebalance_label]
    else:
        lookback_momentum = preset_params["lookback_momentum"]
        lookback_volatility = preset_params["lookback_volatility"]
        top_n = preset_params["top_n"]
        rebalance_days = preset_params["rebalance_freq"]
        rebalance_label = next((k for k, v in REBALANCE_FREQ_OPTIONS.items() if v == rebalance_days), "20日（月线）")

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.info(f"动量回看: {lookback_momentum}日")
            st.info(f"波动率回看: {lookback_volatility}日")
        with col_p2:
            st.info(f"选择标的: {top_n}只")
            st.info(f"调仓频率: {rebalance_label}")

    params = {
        "lookback_momentum": lookback_momentum,
        "lookback_volatility": lookback_volatility,
        "top_n": top_n,
        "rebalance_freq": rebalance_days,
    }

    st.markdown("---")
    st.subheader("🔒 风控约束")
    enable_constraints = st.checkbox("启用约束条件", value=True)
    if enable_constraints:
        long_only = st.checkbox("单向做多（禁止卖空）", value=DEFAULT_BACKTEST_CONSTRAINTS['long_only'])
        max_positions = st.slider("最大持仓数", 1, 10, DEFAULT_BACKTEST_CONSTRAINTS['max_positions'])
        min_positions = st.slider("最少持仓数", 0, 10, DEFAULT_BACKTEST_CONSTRAINTS['min_positions'],
                                   help="卖出后持仓数不能低于此值，0表示不限制")
        max_position_pct = st.slider("单仓位上限(%)", 10, 100, int(DEFAULT_BACKTEST_CONSTRAINTS['max_position_pct']), step=5)
        max_total_exposure_pct = st.slider("总仓位上限(%)", 20, 100, int(DEFAULT_BACKTEST_CONSTRAINTS['max_total_exposure_pct']),
                                            step=5, help="所有持仓总市值/总资金的上限，留现金缓冲")
        slippage_rate = st.slider("滑点率(%)", 0.0, 1.0, DEFAULT_BACKTEST_CONSTRAINTS['slippage_rate'], step=0.05)
        t_plus_one = st.checkbox("T+1交易约束", value=DEFAULT_BACKTEST_CONSTRAINTS['t_plus_one'])
        min_trade_amount = st.slider("最低交易金额(元)", 1000, 50000, int(DEFAULT_BACKTEST_CONSTRAINTS['min_trade_amount']), step=1000)
        max_monthly_turnover = st.slider("月度换手率上限(%)", 20, 200, int(DEFAULT_BACKTEST_CONSTRAINTS['max_monthly_turnover']), step=10)
        max_per_sector = st.slider("单一风格上限", 0, 10, DEFAULT_BACKTEST_CONSTRAINTS['max_per_sector'],
                                   help="同一sector(如科技、医药)最多持仓数，0=不限制")

        constraints_dict = {
            "long_only": long_only,
            "max_positions": max_positions,
            "min_positions": min_positions,
            "max_position_pct": max_position_pct,
            "max_total_exposure_pct": max_total_exposure_pct,
            "slippage_rate": slippage_rate,
            "t_plus_one": t_plus_one,
            "min_trade_amount": min_trade_amount,
            "max_monthly_turnover": max_monthly_turnover,
            "max_per_sector": max_per_sector,
        }
    else:
        constraints_dict = {
            "long_only": True,
            "max_positions": 999,
            "min_positions": 0,
            "max_position_pct": 100.0,
            "max_total_exposure_pct": 100.0,
            "slippage_rate": 0.0,
            "t_plus_one": False,
            "min_trade_amount": 0,
            "max_monthly_turnover": 9999.0,
            "max_per_sector": 0,
        }

    if st.button("🔬 因子分析", use_container_width=True,
                 help="检验各因子在ETF池中的有效性（RankIC/ICIR/分层回测）"):
        st.session_state['factor_analysis_clicked'] = True
    st.markdown("---")
    run_clicked = st.button("🧪 运行回测", type="primary", use_container_width=True)


if run_clicked:
    if not selected_codes:
        st.error("请至少选择一只ETF")
    else:
        with st.status("正在检查数据...", expanded=True) as status:
            progress_placeholder = st.empty()
            st.write("检查数据完整性...")

            def on_data_progress(msg):
                progress_placeholder.text(msg)

            data_result = ensure_data_ready(
                selected_codes,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
                data_source,
                etf_repo,
                price_repo,
                valuation_repo,
                on_progress=on_data_progress,
            )

            if data_result['status'] == 'error':
                status.update(label="数据不足，请补充", state="error", expanded=True)
                st.error("❌ 数据不足，无法运行回测。请先在命令行补充数据：")
                st.code(data_result['message'], language='bash')
                st.info("💡 补充完数据后，重新点击「运行回测」即可。")
            else:
                st.write("✅ 数据检查通过")
                status.update(label="数据检查完成", state="complete", expanded=False)

                data_dict = {}
                for code in selected_codes:
                    prices = price_repo.get_daily_price(code)
                    if prices:
                        df = pd.DataFrame(prices)
                        data_dict[code] = df

                with st.spinner("正在运行回测..."):
                    result = run_backtest_for_result(
                        selected_codes,
                        start_date,
                        end_date,
                        params,
                        constraints_dict,
                    )
                    st.session_state['result'] = result
                    st.session_state['selected_codes_saved'] = selected_codes
                    st.success(f"✅ 多因子轮动 回测完成（{start_date} ~ {end_date}）")


# 因子分析弹窗（独立于回测结果）
if st.session_state.get('factor_analysis_clicked'):
    @st.dialog("因子有效性分析", width="large")
    def show_factor_analysis():
        from strategy.factor_analysis import analyze_all_etfs
        from strategy.scoring import FACTOR_LABELS

        with st.spinner("正在计算因子有效性（约30-60秒）..."):
            try:
                report = analyze_all_etfs(
                    etf_codes=[e['code'] for e in ETF_UNIVERSE],
                    price_repo=price_repo,
                    valuation_repo=valuation_repo,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )
            except Exception as e:
                st.error(f"因子分析失败: {e}")
                return

        if not report:
            st.warning("无可用因子数据，请确保ETF行情和PE数据已更新")
            return

        st.markdown(f"**分析区间**: {start_date} ~ {end_date} | **ETF数**: {len(ETF_UNIVERSE)}")

        # 因子汇总表
        summary_rows = []
        for factor, metrics in report.items():
            icir_info = metrics.get('icir', {})
            summary_rows.append({
                '因子': FACTOR_LABELS.get(factor, factor),
                'RankIC均值': f"{metrics.get('ic_mean', 0):.4f}",
                'ICIR': f"{icir_info.get('icir', 0):.3f}",
                'IC正比例': f"{metrics.get('ic_positive_ratio', 0):.1%}",
                '单调性': metrics.get('monotonicity', '-'),
                '判定': metrics.get('verdict', '-'),
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        # 因子切换 + 详情图表
        factor_options = list(report.keys())
        if factor_options:
            selected_factor = st.selectbox("选择因子查看详情", factor_options)
            if selected_factor:
                m = report[selected_factor]

                # IC时间序列
                ic_series = m.get('ic_series', [])
                if ic_series:
                    ic_df = pd.DataFrame(ic_series)
                    fig_ic = go.Figure()
                    fig_ic.add_trace(go.Bar(
                        x=ic_df['date'], y=ic_df['ic'],
                        name='月度IC', marker_color='blue'
                    ))
                    fig_ic.add_trace(go.Scatter(
                        x=ic_df['date'], y=ic_df['ic'].cumsum(),
                        name='累计IC', yaxis='y2',
                        line=dict(color='red', width=2)
                    ))
                    fig_ic.update_layout(
                        title=f"{FACTOR_LABELS.get(selected_factor, selected_factor)} 月度IC序列",
                        yaxis=dict(title="月度IC"),
                        yaxis2=dict(title="累计IC", overlaying='y', side='right'),
                        template='plotly_white',
                    )
                    st.plotly_chart(fig_ic, use_container_width=True)

                # 分层回测
                strat_data = m.get('stratified', [])
                if strat_data:
                    strat_df = pd.DataFrame(strat_data)
                    strat_df['cum_return'] = strat_df.groupby('group')['avg_return'].transform(
                        lambda x: (1 + x).cumprod() - 1
                    )
                    fig_strat = px.line(
                        strat_df, x='date', y='cum_return', color='group',
                        title=f"{FACTOR_LABELS.get(selected_factor, selected_factor)} 分层回测累计收益",
                        labels={'date': '日期', 'cum_return': '累计收益', 'group': '分组'},
                        template='plotly_white',
                    )
                    st.plotly_chart(fig_strat, use_container_width=True)

        if st.button("关闭", use_container_width=True):
            st.session_state['factor_analysis_clicked'] = False
            st.rerun()

    show_factor_analysis()


result = st.session_state.get('result')
if result:
    st.markdown("### 📊 回测概览")

    trade_list = result.get('trade_list', [])
    nav_df = result.get('nav_df', pd.DataFrame())

    if trade_list and not nav_df.empty:
        first_trade_date = trade_list[0].get('date', '')
        start_date_str = str(nav_df.iloc[0]['date'])[:10]
        from datetime import datetime
        try:
            first_dt = datetime.strptime(first_trade_date, '%Y-%m-%d')
            start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
            empty_days = (first_dt - start_dt).days
            total_days = len(nav_df)
            pct_empty = empty_days / max(total_days, 1) * 100

            if empty_days > 5:
                if pct_empty > 30:
                    icon = "⚠️"
                    msg = f"首笔交易在 {first_trade_date}，回测前 {empty_days} 天（{pct_empty:.0f}%）空仓"
                    tip = "策略等待动量信号转正后才入场，震荡市/熊市初期可能长期空仓。可尝试降低 lookback 或调小 min_momentum 阈值。"
                else:
                    icon = "ℹ️"
                    msg = f"首笔交易在 {first_trade_date}，回测前 {empty_days} 天空仓（正常预热）"
                    tip = "策略在动量信号转正后入场，属正常行为。"
                st.info(f"{icon} {msg}\n\n💡 {tip}")
        except (ValueError, KeyError):
            pass
    elif not trade_list:
        st.warning("⚠️ 回测区间内无任何交易。可能原因：动量信号全部为负、ETF数量不足、或约束条件过严。")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("最终市值", f"{result['final_value']:,.0f}",
                  delta=f"{result['total_return']:+.2f}%")
    with col2:
        st.metric("年化收益率", f"{result['annual_return']:.2f}%")
    with col3:
        st.metric("夏普比率", f"{result['sharpe_ratio']:.2f}")
    with col4:
        st.metric("最大回撤", f"{result['max_drawdown']:.2f}%",
                  delta=f"持续 {result['max_drawdown_days']:.0f} 天",
                  delta_color="inverse")

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        comp = result.get('comparison', {})
        primary_comp = comp.get('comparison', {}).get(PRIMARY_BENCHMARK, {})
        primary_metrics = comp.get('benchmark_metrics', {}).get(PRIMARY_BENCHMARK, {})
        st.metric(f"{PRIMARY_BENCHMARK}基准", f"{primary_metrics.get('total_return', 0):.2f}%",
                  delta=f"超额 {primary_comp.get('excess_return', 0):+.2f}%")
    with col6:
        st.metric("交易次数", result['num_trades'])
    with col7:
        st.metric("胜率", f"{result['win_rate']:.1f}%")
    with col8:
        st.metric("盈亏比", f"{result['profit_factor']:.2f}")

    st.markdown("---")

    with st.expander("📋 策略 vs 基准 绩效对比", expanded=True):
        comp = result.get('comparison', {})
        sm = comp.get('strategy_metrics', {})
        bm = comp.get('benchmark_metrics', {})

        metric_names = ['total_return', 'annual_return', 'volatility', 'sharpe_ratio',
                       'sortino_ratio', 'max_drawdown', 'calmar_ratio']
        metric_labels = ['总收益率(%)', '年化收益率(%)', '年化波动率(%)', '夏普比率',
                        '索提诺比率', '最大回撤(%)', '卡玛比率']

        bench_names = list(bm.keys())
        cols = ['指标', '策略'] + bench_names
        rows = []
        for label, key in zip(metric_labels, metric_names):
            row = {'指标': label}
            row['策略'] = _fmt_metric(sm.get(key, 0))
            for bn in bench_names:
                row[bn] = _fmt_metric(bm[bn].get(key, 0))
            rows.append(row)

        comparison_data = comp.get('comparison', {})
        for bn in bench_names:
            excess = comparison_data.get(bn, {}).get('excess_return', 0)
            row = {'指标': f'超额收益(vs {bn})'}
            row['策略'] = f'{excess:+.2f}%'
            for b in bench_names:
                row[b] = '-'
            rows.append(row)

        st.dataframe(pd.DataFrame(rows, columns=cols), use_container_width=True, hide_index=True)

    st.markdown("---")
    with st.expander("📊 业界对齐指标", expanded=True):
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.metric("累计换手率", f"{result.get('turnover_total_pct', 0):.1f}%")
        with col_t2:
            st.metric("年化换手率", f"{result.get('turnover_annual_pct', 0):.1f}%")

        turnover_series = result.get('turnover_series')
        if turnover_series is not None and not turnover_series.empty:
            if st.checkbox("显示逐次调仓换手率"):
                import plotly.express as px
                fig_t = px.line(
                    turnover_series, x='date', y='turnover_pct',
                    title="每次调仓换手率(%)",
                    template='plotly_white',
                )
                fig_t.update_layout(yaxis_title='换手率(%)', xaxis_title='调仓日')
                st.plotly_chart(fig_t, use_container_width=True)

    with st.expander("🔍 数据合规审计", expanded=False):
        st.markdown("""
        **数据合规审计为独立 CLI 工具，需手动执行**：

        ```bash
        # 生存偏差审计
        python scripts/audit_survivorship.py --start 2020-01-01

        # 前视偏差审计
        python scripts/audit_lookahead.py --static-only
        ```
        """)

    st.markdown("---")
    st.markdown("### 📈 收益曲线")

    with st.expander("📖 基准说明", expanded=False):
        st.markdown(f"""
        **基准对比说明**：

        - **{PRIMARY_BENCHMARK}**：大盘价值风格标尺（510300），业界标准基准

        收益曲线从0%开始计算，点击图例可隐藏/显示某条线。
        """)

    comp = result.get('comparison', {})
    cr_df = comp.get('cumulative_return_df')
    dr_df = comp.get('daily_return_df')
    bench_names = list(comp.get('benchmark_metrics', {}).keys())

    if cr_df is not None and not cr_df.empty and bench_names:
        selected_bench = st.selectbox("选择对比基准", bench_names, key='returns_bench_select', index=0)

        fig = go.Figure()

        # 策略收益
        fig.add_trace(go.Scatter(
            x=cr_df['date'], y=cr_df['strategy'],
            name='策略收益',
            line=dict(color='#1f77b4', width=3),
            mode='lines',
        ))

        # 基准收益
        fig.add_trace(go.Scatter(
            x=cr_df['date'], y=cr_df[selected_bench],
            name=f'{selected_bench}收益',
            line=dict(color='#d62728', width=2),
            mode='lines',
        ))

        # 超额收益
        excess = cr_df['strategy'] - cr_df[selected_bench]
        fig.add_trace(go.Scatter(
            x=cr_df['date'], y=excess,
            name='超额收益',
            line=dict(color='#ff7f0e', width=2),
            mode='lines',
            fill='tozeroy',
            fillcolor='rgba(127,127,127,0.2)',
        ))

        fig.update_layout(
            title="累计收益率对比",
            template='plotly_white',
            legend=dict(title=''),
            yaxis=dict(
                title='收益率(%)',
                tickformat='.0f',
            ),
            xaxis=dict(title='日期'),
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

        # 日收益率柱状图
        if dr_df is not None and not dr_df.empty:
            colors = ['#2ca02c' if v >= 0 else '#d62728' for v in dr_df['strategy']]
            fig_daily = go.Figure(go.Bar(
                x=dr_df['date'],
                y=dr_df['strategy'],
                marker_color=colors,
                name='日收益率',
            ))
            fig_daily.update_layout(
                title="日收益率",
                template='plotly_white',
                legend=dict(title=''),
                yaxis=dict(
                    title='收益率(%)',
                    tickformat='.1f',
                ),
                xaxis=dict(title='日期'),
                height=200,
            )
            st.plotly_chart(fig_daily, use_container_width=True)
    else:
        st.info("暂无收益曲线数据")

    st.markdown("---")
    st.markdown("### 📉 回撤对比")
    drawdown_df = comp.get('drawdown_df')
    if drawdown_df is not None and not drawdown_df.empty:
        dd_cols = [c for c in drawdown_df.columns if c != 'date']
        dd_color_map = {
            'strategy': '#1f77b4',
            '沪深300': '#d62728',
        }
        dd_labels = {'strategy': '策略', '沪深300': '沪深300'}
        fig_dd = px.line(
            drawdown_df, x='date', y=dd_cols,
            title="策略与基准回撤对比",
            template='plotly_white',
            color_discrete_map=dd_color_map,
            labels=dd_labels,
        )
        fig_dd.update_traces(
            selector=dict(name='strategy'),
            line_width=3,
        )
        fig_dd.update_layout(
            legend=dict(title=''),
            yaxis_title='回撤(%)',
        )
        st.plotly_chart(fig_dd, use_container_width=True)
    else:
        st.info("暂无回撤数据")

    st.markdown("---")
    st.markdown("### 📊 超额收益分析")
    excess_nav_df = comp.get('excess_nav_df')
    comparison_data = comp.get('comparison', {})
    bench_names_excess = list(comparison_data.keys())

    if excess_nav_df is not None and not excess_nav_df.empty and bench_names_excess:
        selected_bench = st.selectbox("选择对比基准", bench_names_excess, key='excess_bench_select')

        if selected_bench in excess_nav_df.columns:
            fig_excess = px.line(
                excess_nav_df, x='date', y=selected_bench,
                title=f"策略相对{selected_bench}超额净值",
                template='plotly_white',
                color_discrete_map={selected_bench: '#1f77b4'},
            )
            fig_excess.update_layout(
                yaxis_title='超额净值（起点=1.0）',
                showlegend=False,
            )
            st.plotly_chart(fig_excess, use_container_width=True)

        sc = comparison_data.get(selected_bench, {})
        col_ir, col_alpha, col_beta, col_mw, col_qw = st.columns(5)
        with col_ir:
            st.metric("信息比率", f"{sc.get('information_ratio', 0):.2f}")
        with col_alpha:
            st.metric("Alpha(%)", f"{sc.get('alpha', 0):+.2f}")
        with col_beta:
            st.metric("Beta", f"{sc.get('beta', 0):.2f}")
        with col_mw:
            wr_m = sc.get('win_rate_monthly')
            st.metric("月度胜率", f"{wr_m:.1f}%" if wr_m is not None else "数据不足")
        with col_qw:
            wr_q = sc.get('win_rate_quarterly')
            st.metric("季度胜率", f"{wr_q:.1f}%" if wr_q is not None else "数据不足")

        if wr_m is not None:
            st.caption(f"策略在 {wr_m:.1f}% 的月份跑赢{selected_bench}基准")
    else:
        st.info("暂无超额收益数据")

    st.markdown("---")
    st.markdown("### 🔍 因子校验结果")
    val_results = valuation_repo.list_validation_results(factor_name="pe_cross_check")
    if val_results:
        val_rows = []
        name_map = {e['code']: e['name'] for e in ETF_UNIVERSE}
        for v in val_results:
            code = v['etf_code']
            name = name_map.get(code, '')
            if not name:
                etf_info = etf_repo.get_etf(code)
                name = etf_info.get('name', '') if etf_info else ''
            metrics = v.get('metrics', [])
            metric_dict = {m['name']: m for m in metrics}
            val_rows.append({
                "代码": code,
                "名称": name,
                "状态": _status_label(v['status']),
                "数据点": metric_dict.get("重合数据点", {}).get("value", "-"),
                "相关系数": metric_dict.get("相关系数", {}).get("value", "-"),
                "平均误差": f"{metric_dict.get('平均相对误差', {}).get('value', '-')}%",
                "通过率": f"{metric_dict.get('通过率', {}).get('value', '-')}%",
                "最新本地PE": metric_dict.get("均值比率", {}).get("value", "-"),
                "校验时间": v.get('validated_at', '')[:19],
            })
        val_df = pd.DataFrame(val_rows)
        st.dataframe(val_df, use_container_width=True, hide_index=True)

        pass_count = sum(1 for v in val_results if v['status'] == 'pass')
        warn_count = sum(1 for v in val_results if v['status'] == 'warning')
        fail_count = sum(1 for v in val_results if v['status'] == 'fail')
        skip_count = sum(1 for v in val_results if v['status'] == 'skip')
        st.caption(
            f"共{len(val_results)}只ETF：✅通过{pass_count} ⚠️警告{warn_count} ❌失败{fail_count} ⏭️跳过{skip_count}"
        )
    else:
        st.info("暂无校验结果，运行回测后自动生成")

    st.markdown("---")
    st.markdown("### 📝 交易明细")
    trade_list = result.get('trade_list', [])
    if trade_list:
        trade_df = build_trade_table(trade_list)
        st.dataframe(trade_df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无交易记录")

    st.markdown("---")
    st.markdown("### 🔍 ETF详情查看器")

    detail_codes = st.session_state.get('selected_codes_saved', selected_codes)
    if detail_codes:
        col_select, col_btn = st.columns([3, 1])
        with col_select:
            detail_code = st.selectbox(
                "选择ETF查看详情",
                detail_codes,
                format_func=lambda x: f"{x} - {etf_repo.get_etf(x).get('name', '') if etf_repo.get_etf(x) else ''}",
                key="detail_code_selector",
            )
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("查看详情", type="primary", use_container_width=True):
                st.session_state['detail_code'] = detail_code
                show_etf_detail(detail_code)
    else:
        st.info("请选择ETF并运行回测")
else:
    st.info("👈 请在左侧选择参数，点击「运行回测」开始分析")
