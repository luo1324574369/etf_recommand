import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from pathlib import Path

from service.application_service import (
    ApplicationService,
    FACTOR_DIRECTIONS,
    FACTOR_LABELS,
    PRIMARY_BENCHMARK,
    DEFAULT_BACKTEST_CONSTRAINTS,
)
from config.settings import ETF_UNIVERSE, DB_PATH, PARAM_PRESETS

INITIAL_CAPITAL = 1000000
app_service = ApplicationService(DB_PATH)

REBALANCE_FREQ_OPTIONS = {
    "5日（周线）": 5,
    "10日（半月）": 10,
    "20日（月线）": 20,
    "60日（季线）": 60,
    "120日（半年线）": 120,
    "250日（年线）": 250,
}

PARAM_CN_LABELS = {
    "lookback_momentum": "反转/动量回看(日)",
    "lookback_volatility": "低波回看(日)",
    "top_n": "卫星选股数",
    "rebalance_freq": "调仓频率(日)",
    "sector_penalty_factor": "赛道软降权系数",
    "sector_exclude_threshold": "赛道硬排除阈值",
    "max_monthly_turnover": "月度换手率上限(%)",
    "drawdown_threshold": "回撤止损阈值(%)",
    "max_sector_exposure_pct": "单赛道仓位上限(%)",
    "market_regime_switch": "启用市场状态切换",
    "enable_factor_monitor": "启用因子失效监控",
}

st.set_page_config(page_title="ETF量化策略平台", layout="wide")

st.title("📈 ETF量化策略平台")

def run_backtest_for_result(selected_codes, start_date, end_date, params, constraints_dict,
                           enable_attribution=False, attribution_benchmark_type='csi300'):
    return app_service.run_backtest(
        selected_codes,
        start_date,
        end_date,
        params,
        constraints_dict,
        enable_attribution=enable_attribution,
        attribution_benchmark_type=attribution_benchmark_type,
    )


def build_trade_table(trade_list):
    if not trade_list:
        return pd.DataFrame()

    trade_type_map = {
        'core': '🎯 核心',
        'satellite': '🛰️ 卫星',
        'stoploss': '🛑 止损',
    }

    # 先从内存映射查名称，找不到再查数据库
    name_map = {e['code']: e['name'] for e in ETF_UNIVERSE}

    rows = []
    for t in trade_list:
        code = t.get('code', '')
        name = name_map.get(code, '')
        if not name:
            etf_info = app_service.get_etf(code)
            name = etf_info.get('name', '') if etf_info else ''
        direction = t.get('direction', '')
        if direction == '买入':
            direction_display = '🟢 买入'
        elif direction == '卖出':
            direction_display = '🔴 卖出'
        else:
            direction_display = direction

        trade_type = t.get('trade_type', 'satellite')
        type_display = trade_type_map.get(trade_type, '🛰️ 卫星')

        rows.append({
            '日期': t.get('date', ''),
            '代码': code,
            '名称': name,
            '方向': direction_display,
            '交易类型': type_display,
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


def _render_alpha_stability_section(result, primary_benchmark):
    """渲染 Alpha 稳定性分析：6 指标卡 + 警告 + 2 图 + 1 表 + 2 卡片"""
    asd = result.get('alpha_stability') if result else None
    if not asd:
        st.info("暂无 Alpha 稳定性分析数据")
        return

    cum_excess = None
    excess_1y = None
    rw = asd.get('rolling_windows')
    if isinstance(rw, pd.DataFrame) and not rw.empty:
        row_full = rw[rw['window'] == '成立以来']
        if not row_full.empty:
            cum_excess = float(row_full.iloc[0]['excess_pct'])
        row_1y = rw[rw['window'] == '1年']
        if not row_1y.empty:
            excess_1y = float(row_1y.iloc[0]['excess_pct'])

    warning_level = asd.get('warning_level')
    recent_failed = asd.get('recent_failed', False)

    # expander 标签
    icon = "✅"
    suffix = ""
    if cum_excess is not None and cum_excess > 0:
        icon = "⚠️" if warning_level else "✅"
        if warning_level == 'severe':
            suffix = "（近期已失效）"
        elif warning_level == 'mild':
            suffix = "（近1年走弱）"
    label = f"{icon} 累计超额 {_fmt_metric(cum_excess)}%{suffix}"

    with st.expander(label, expanded=True):
        st.caption("识别「累计超额为正但近期已失效」的错觉 —— "
                   "当累计超额>0但近1年/半年超额<0时，说明 Alpha 已退化，当前累计正超额仅来自历史缓冲。")

        # ---- 顶部警告 ----
        if warning_level == 'severe':
            st.warning(f"⚠️ 严重警告：累计超额为正（{_fmt_metric(cum_excess)}%），但近1年超额（{_fmt_metric(excess_1y)}%）和近半年超额均为负。"
                      "策略 Alpha 已退化，累计正超额仅来自历史缓冲。建议缩短回测窗口或检查策略在当前市场环境下的有效性。")
        elif warning_level == 'mild':
            st.info(f"ℹ️ 提示：累计超额为正（{_fmt_metric(cum_excess)}%），但近1年超额（{_fmt_metric(excess_1y)}%）为负。策略表现近期有走弱迹象。")

        # ---- 6 指标卡 ----
        ir = asd.get('information_ratio')
        rel_dd = asd.get('max_relative_drawdown')
        te = asd.get('tracking_error')
        hr = asd.get('monthly_hit_rate')
        excess_half = None
        if isinstance(rw, pd.DataFrame) and not rw.empty:
            row_h = rw[rw['window'] == '6月']
            if not row_h.empty:
                excess_half = float(row_h.iloc[0]['excess_pct'])

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            st.metric("累计超额", f"{_fmt_metric(cum_excess)}%")
        with c2:
            delta = None
            delta_color = "normal"
            if excess_1y is not None:
                delta = "失效" if excess_1y < 0 else "有效"
                delta_color = "inverse" if excess_1y < 0 else "normal"
            st.metric("近1年超额", f"{_fmt_metric(excess_1y)}%", delta=delta, delta_color=delta_color)
        with c3:
            st.metric("信息比率(IR)", f"{_fmt_metric(ir)}",
                      help="IR>0.5 合格，>1.0 优秀。单位主动风险获得的超额收益。")
        with c4:
            st.metric("相对回撤", f"{_fmt_metric(rel_dd)}%",
                      help="超额净值（策略/基准）的最大回撤。评估 Alpha 稳定性。")
        with c5:
            st.metric("跟踪误差(TE)", f"{_fmt_metric(te)}%",
                      help="策略日收益 vs 基准日收益差的年化波动率。增强型基金 TE<5% 合格。")
        with c6:
            hr_str = f"{_fmt_metric(hr)}%"
            delta_hr = None
            delta_color_hr = "normal"
            if hr is not None:
                delta_hr = "稳定" if hr >= 60 else "偏低"
                delta_color_hr = "normal" if hr >= 60 else "inverse"
            st.metric("月度命中率", hr_str, delta=delta_hr, delta_color=delta_color_hr,
                      help="月度超额>0 的月份占比。>60% 为稳定 Alpha。")

        # ---- 累计超额净值曲线 ----
        st.markdown("##### 累计超额净值曲线（策略/基准）")
        ens = asd.get('excess_nav_series')
        dd_info = asd.get('max_relative_dd_info')
        if isinstance(ens, pd.DataFrame) and not ens.empty:
            ens = ens.copy()
            ens['date'] = pd.to_datetime(ens['date'])
            fig_e = go.Figure()
            fig_e.add_trace(go.Scatter(
                x=ens['date'], y=ens['excess_nav'], mode='lines', name='策略/基准',
                line=dict(color='#2ca02c', width=1.5),
            ))
            if rel_dd is not None and rel_dd < -1 and dd_info:
                try:
                    ds = pd.to_datetime(dd_info.get('date_start'))
                    de = pd.to_datetime(dd_info.get('date_end'))
                    fig_e.add_vrect(
                        x0=ds, x1=de,
                        fillcolor='rgba(255,165,0,0.15)', line_width=0,
                        annotation_text=f'最大相对回撤 {rel_dd:.1f}%',
                        annotation_position='top left',
                    )
                except (TypeError, ValueError):
                    pass
            fig_e.add_hline(y=1.0, line_dash='dash', line_color='gray')
            fig_e.update_layout(
                yaxis_title='策略/基准', xaxis_title='日期',
                template='plotly_white', height=320,
                margin=dict(l=10, r=10, t=30, b=10),
            )
            st.plotly_chart(fig_e, use_container_width=True)
            st.caption("曲线向上=跑赢基准，向下=跑输。橙色区间为最大相对回撤期。")
        else:
            st.info("暂无足够数据绘制累计超额净值曲线")

        # ---- 滚动 Alpha 折线图 ----
        st.markdown("##### 滚动超额收益（3窗口）")
        ras = asd.get('rolling_alpha_series')
        if isinstance(ras, pd.DataFrame) and not ras.empty:
            ras = ras.copy()
            ras['date'] = pd.to_datetime(ras['date'])
            fig_r = go.Figure()
            fig_r.add_trace(go.Scatter(x=ras['date'], y=ras['excess_252d'], mode='lines', name='252日(1年)', line=dict(color='#1f77b4', width=1.5)))
            fig_r.add_trace(go.Scatter(x=ras['date'], y=ras['excess_126d'], mode='lines', name='126日(半年)', line=dict(color='#ff7f0e', width=1.2)))
            fig_r.add_trace(go.Scatter(x=ras['date'], y=ras['excess_63d'],  mode='lines', name='63日(3月)',  line=dict(color='#2ca02c', width=1.0)))
            fig_r.add_hline(y=0, line_dash='dash', line_color='red',
                            annotation_text='0%基准线', annotation_position='top left')
            fig_r.update_layout(
                yaxis_title='滚动超额(%)', xaxis_title='日期',
                template='plotly_white', height=320,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(l=10, r=10, t=30, b=10),
            )
            st.plotly_chart(fig_r, use_container_width=True)
            st.caption("曲线长期在0轴上方=Alpha稳定；近期跌破0轴=策略失效。")
        else:
            st.info("数据不足，无法绘制滚动Alpha（需至少63个交易日）")

        # ---- 滚动窗口收益表 ----
        st.markdown("##### 滚动窗口收益对比")
        if isinstance(rw, pd.DataFrame) and not rw.empty:
            rw_display = rw.copy()
            for col in ['strategy_pct', 'benchmark_pct', 'excess_pct']:
                rw_display[col] = rw_display[col].apply(lambda v: f"{v:+.2f}%" if isinstance(v, (int, float)) else v)
            rw_display['sufficient_data'] = rw_display['sufficient_data'].map({True: '✅', False: '⚠️ 不足'})
            rename_cols = {
                'window': '区间',
                'strategy_pct': '策略(%)',
                'benchmark_pct': f'{primary_benchmark}(%)',
                'excess_pct': '超额(%)',
                'sufficient_data': '数据',
            }
            rw_display = rw_display.rename(columns=rename_cols)
            st.dataframe(rw_display, use_container_width=True, hide_index=True)
            st.caption("公募基金季报格式。近N月窗口=取末尾 N×21 个交易日。")
        else:
            st.info("暂无滚动窗口收益数据")

        # ---- Up/Down Capture ----
        st.markdown("##### 牛/熊市捕获率（Up / Down Capture）")
        cap = asd.get('up_down_capture')
        if cap:
            col_u, col_d = st.columns(2)
            up = cap.get('up_capture_pct')
            down = cap.get('down_capture_pct')
            up_cnt = cap.get('up_months_count', 0)
            down_cnt = cap.get('down_months_count', 0)
            with col_u:
                up_status = "✅ >100 弹性大" if up is not None and up > 100 else ("✅ <100 抗涨" if up is not None and up <= 100 else "-")
                st.metric(f"上行捕获率（{up_cnt}个涨月）",
                          f"{_fmt_metric(up)}%",
                          delta=up_status,
                          help="基准月收益>0的月份：策略月收益均值 / 基准月收益均值 × 100。")
            with col_d:
                down_status = "✅ <100 抗跌" if down is not None and down < 100 else ("⚠️ >100 跌更深" if down is not None and down >= 100 else "-")
                st.metric(f"下行捕获率（{down_cnt}个跌月）",
                          f"{_fmt_metric(down)}%",
                          delta=down_status,
                          help="基准月收益<0的月份：策略月收益均值 / 基准月收益均值 × 100。")
        else:
            st.info("暂无 Up/Down Capture 数据（可能不足2个完整月份）")


def _render_factor_diagnostics_section(result):
    """渲染因子诊断面板：统计、滚动IC、分层收益和权重演变。"""
    import numpy as np
    fd = result.get('factor_diagnostics') if result else None
    if not fd:
        return
    with st.expander("📊 因子诊断面板", expanded=True):
        # 顶部 4 指标卡
        factor_stats = fd.get('factor_stats')
        if factor_stats is None:
            factor_stats = pd.DataFrame()
        weight_mode = fd.get('weight_mode', 'unknown')
        excluded_factors = fd.get('excluded_factors') or []
        if not factor_stats.empty:
            active_n = int((factor_stats['status'] == 'active').sum()) if 'status' in factor_stats else len(factor_stats)
            total_n = len(factor_stats)
        else:
            active_n, total_n = 0, 0

        icir_mean = 0.0
        if not factor_stats.empty and 'icir' in factor_stats:
            ic_series = pd.to_numeric(factor_stats['icir'], errors='coerce').replace([np.inf, -np.inf], np.nan)
            icir_mean = float(ic_series.mean()) if not ic_series.empty else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("有效因子", f"{active_n} / {total_n}")
        c2.metric("因子 ICIR 均值", f"{icir_mean:.3f}")
        if excluded_factors:
            label = ", ".join(f"{x.get('factor', '?')}" for x in excluded_factors[:3])
            if len(excluded_factors) > 3:
                label += f" 等{len(excluded_factors)}"
            c3.metric("已剔除因子", label)
        else:
            c3.metric("已剔除因子", "无")
        mode_txt = "ICIR动态加权" if weight_mode == 'icir_dynamic' else "等权(fallback)"
        c4.metric("权重模式", mode_txt)

        if weight_mode == 'equal_weight_fallback' and total_n > 0:
            st.warning("当前全部因子ICIR≤0，已降级为等权组合。请检查因子有效性或延长回测期间。")

        # 因子统计表
        if not factor_stats.empty:
            show_cols = ['label', 'rank_ic_mean', 'icir', 'hit_rate_12m', 'status', 'used_weight_mean', 'excluded_months', 'missing_rate']
            show_cols = [c for c in show_cols if c in factor_stats.columns]
            display_df = factor_stats[show_cols].copy()

            def _paint_row(row):
                css = ""
                if str(row.get('status')) == 'excluded':
                    css = "background-color: #ffe0e0; color: #b00020;"
                return [css] * len(row)

            format_map = {}
            for col in ['rank_ic_mean']:
                if col in display_df:
                    format_map[col] = '{:.4f}'
            for col in ['icir']:
                if col in display_df:
                    format_map[col] = '{:.3f}'
            for col in ['hit_rate_12m']:
                if col in display_df:
                    format_map[col] = '{:.1%}'
            for col in ['used_weight_mean']:
                if col in display_df:
                    format_map[col] = '{:.2%}'
            if 'missing_rate' in display_df:
                format_map['missing_rate'] = '{:.1%}'

            try:
                styled = display_df.style.apply(_paint_row, axis=1)
                if format_map:
                    styled = styled.format(format_map, na_rep='-')
                st.dataframe(styled, use_container_width=True, hide_index=True)
            except Exception:
                st.dataframe(display_df, use_container_width=True, hide_index=True)

        factor_health = result.get('factor_health') or []
        if factor_health:
            st.markdown("#### 因子生命周期状态")
            health_rows = []
            for health in factor_health:
                health_values = health if isinstance(health, dict) else None
                health_rows.append({
                    '因子': health.get('factor_name', '-') if health_values is not None else health.factor_name,
                    '状态': health.get('status', '-') if health_values is not None else health.status,
                    '观察窗口(月)': health.get('window_months', 0) if health_values is not None else health.window_months,
                    '失效信号': (', '.join(health.get('failed_metrics', ())) if health_values is not None else ', '.join(health.failed_metrics)) or '无',
                })
            st.dataframe(pd.DataFrame(health_rows), use_container_width=True, hide_index=True)

        # 滚动 IC 曲线
        rolling_ic = fd.get('rolling_ic_series')
        if rolling_ic is None:
            rolling_ic = pd.DataFrame()
        if not rolling_ic.empty and 'date' in rolling_ic.columns:
            cols = set(rolling_ic.columns)
            if {'factor', 'ic'}.issubset(cols):
                # 长表格式（date, factor, ic）直接使用
                long_df = rolling_ic.copy()
            else:
                # 宽表格式（date, factor1, factor2, ...）melt 成长表
                long_df = rolling_ic.melt(id_vars='date', var_name='factor', value_name='ic')
            long_df['label'] = long_df['factor'].map(FACTOR_LABELS).fillna(long_df['factor'])
            fig = px.line(
                long_df, x='date', y='ic', color='label',
                title='近12个月滚动月度 RankIC（0轴上下=因子有效性）',
                labels={'ic': 'RankIC', 'date': '日期', 'label': '因子'},
                template='plotly_white',
            )
            fig.add_hline(y=0, line_dash='dash', line_color='red', opacity=0.6,
                          annotation_text='IC=0（无效）', annotation_position='bottom right')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无滚动 IC 数据（预热阶段不足或回测周期过短）")

        # 分层收益
        grouped = fd.get('grouped_returns') or {}
        if grouped:
            st.markdown("#### 分层收益单调性（按因子值分5组，组1=暴露最大）")
            n_f = len(grouped)
            cols = st.columns(min(3, n_f)) if n_f else []
            for i, (f, df_g) in enumerate(grouped.items()):
                if cols:
                    with cols[i % len(cols)]:
                        st.markdown(f"**{FACTOR_LABELS.get(f, f)}**")
                        if isinstance(df_g, pd.DataFrame) and not df_g.empty:
                            st.dataframe(df_g, use_container_width=True, hide_index=True)
        else:
            with st.expander("分层收益单调性", expanded=False):
                st.info("数据不足以形成五组分层收益（至少需要两个截面且每个截面有五只ETF）。")

        # 权重演变 area chart
        wh = fd.get('weight_history')
        if wh is None:
            wh = pd.DataFrame()
        if not wh.empty and 'date' in wh.columns:
            num_cols = [c for c in wh.columns if c != 'date']
            if num_cols:
                long_df = wh.melt(id_vars='date', var_name='factor', value_name='weight')
                long_df['label'] = long_df['factor'].map(FACTOR_LABELS).fillna(long_df['factor'])
                fig = px.area(
                    long_df, x='date', y='weight', color='label',
                    title='历次调仓实际使用的因子权重演变',
                    labels={'weight': '权重', 'date': '日期', 'label': '因子'},
                    template='plotly_white',
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无权重历史数据（预热阶段不足或未触发 ICIR 加权）")


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
    return app_service.compute_factor_snapshot(selected_codes)


@st.dialog("ETF详情", width="large")
def show_etf_detail(code):
    etf_info = app_service.get_etf(code)
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
            if selected_factor in ['pe_percentile', 'pb_percentile']:
                pe_history = app_service.get_pe_history(code)
                pb_history = app_service.get_pb_history(code)
            else:
                pe_history = None
                pb_history = None
            hist_df = app_service.compute_factor_history(
                code,
                [selected_factor],
                pe_history=pe_history,
                pb_history=pb_history,
            )
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

    default_codes = [e['code'] for e in etf_pool]
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
    import datetime as _dt
    _today = _dt.date.today()
    _default_start = (_today - _dt.timedelta(days=365*2)).replace(day=1)
    _default_end = (_today - _dt.timedelta(days=31*3)).replace(day=1)
    start_date = st.date_input("开始日期", _default_start)
    end_date = st.date_input("结束日期", _default_end)

    st.markdown("---")
    st.subheader("⚙️ 策略参数")
    st.caption("多因子轮动策略：反转 + 估值 + 低波 + 红利 ICIR动态加权，核心卫星50/50隔离")

    presets = PARAM_PRESETS.get('多因子轮动', [])
    preset_options = [
        {"name": p["name"], "params": p["params"]}
        for p in presets
    ]

    preset_names = [p["name"] for p in preset_options]
    preset_select = st.selectbox("参数预设", preset_names, index=0, key="preset_select")
    selected_preset = next((p for p in preset_options if p["name"] == preset_select), None)
    preset_params = selected_preset.get("params") if selected_preset else None
    if preset_params is None:
        # 自定义参数模式：使用默认参数
        from config.settings import STRATEGY_CONFIG
        mf_config = STRATEGY_CONFIG.get("multi_factor", {})
        params = {
            "lookback_momentum": mf_config.get("lookback_momentum", 60),
            "lookback_volatility": mf_config.get("lookback_volatility", 60),
            "top_n": mf_config.get("top_n", 5),
            "rebalance_freq": mf_config.get("rebalance_freq", 20),
            "sector_penalty_factor": 1.0,
            "sector_exclude_threshold": -0.15,
            "max_monthly_turnover": 100.0,
            "drawdown_threshold": 15.0,
            "max_sector_exposure_pct": 50.0,
            "market_regime_switch": True,
            "enable_factor_monitor": True,
        }
    else:
        params = dict(preset_params)
    lookback_momentum = params["lookback_momentum"]
    lookback_volatility = params["lookback_volatility"]
    top_n = params["top_n"]
    rebalance_days = params["rebalance_freq"]
    rebalance_label = next((k for k, v in REBALANCE_FREQ_OPTIONS.items() if v == rebalance_days), "20日（月线）")

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.info(f"反转/动量回看: {lookback_momentum}日")
        st.info(f"低波回看: {lookback_volatility}日")
    with col_p2:
        st.info(f"卫星选股数: {top_n}只")
        st.info(f"调仓频率: {rebalance_label}")

    # 展示全部预设参数
    extra_params = {k: v for k, v in params.items()
                    if k not in ('lookback_momentum', 'lookback_volatility', 'top_n', 'rebalance_freq')}
    if extra_params:
        with st.expander("📋 全部预设参数", expanded=False):
            for k, v in extra_params.items():
                label = PARAM_CN_LABELS.get(k, k)
                st.text(f"  {label}: {v}")

    st.markdown("---")
    st.subheader("🔒 风控约束")
    enable_constraints = st.checkbox("启用约束条件", value=True)
    # 预设模式下，用预设值作为约束滑块默认值
    preset_turnover = params.get('max_monthly_turnover', DEFAULT_BACKTEST_CONSTRAINTS['max_monthly_turnover'])
    preset_sector_pct = params.get('max_sector_exposure_pct', None)
    if enable_constraints:
        max_positions = st.slider("最大持仓数", 1, 10, DEFAULT_BACKTEST_CONSTRAINTS['max_positions'])
        min_positions = st.slider("最少持仓数", 0, 10, DEFAULT_BACKTEST_CONSTRAINTS['min_positions'],
                                   help="卖出后持仓数不能低于此值，0表示不限制")
        max_position_pct = st.slider("单仓位上限(%)", 10, 100, int(DEFAULT_BACKTEST_CONSTRAINTS['max_position_pct']), step=5)
        max_total_exposure_pct = st.slider("总仓位上限(%)", 20, 100, int(DEFAULT_BACKTEST_CONSTRAINTS['max_total_exposure_pct']),
                                            step=5, help="所有持仓总市值/总资金的上限，留现金缓冲")
        slippage_rate = st.slider("滑点率(%)", 0.0, 1.0, DEFAULT_BACKTEST_CONSTRAINTS['slippage_rate'], step=0.05)
        t_plus_one = st.checkbox("T+1交易约束", value=DEFAULT_BACKTEST_CONSTRAINTS['t_plus_one'])
        min_trade_amount = st.slider("最低交易金额(元)", 1000, 50000, int(DEFAULT_BACKTEST_CONSTRAINTS['min_trade_amount']), step=1000)
        max_monthly_turnover = st.slider("月度换手率上限(%)", 20, 200, int(preset_turnover), step=10)
        max_per_sector = st.slider("单一风格上限", 0, 10, DEFAULT_BACKTEST_CONSTRAINTS['max_per_sector'],
                                   help="同一sector(如科技、医药)最多持仓数，0=不限制")

        constraints_dict = {
            "long_only": True,
            "max_positions": max_positions,
            "min_positions": min_positions,
            "max_position_pct": max_position_pct,
            "max_total_exposure_pct": max_total_exposure_pct,
            "slippage_rate": slippage_rate,
            "t_plus_one": t_plus_one,
            "min_trade_amount": min_trade_amount,
            "max_monthly_turnover": max_monthly_turnover,
            "max_per_sector": max_per_sector,
            "core_allocation_pct": 50.0,
            "core_etf_codes": ("510300", "510500"),
            "core_weights": (0.5, 0.5),
            "max_sector_exposure_pct": params.get("max_sector_exposure_pct", 50.0),
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
            "core_allocation_pct": 50.0,
            "core_etf_codes": ("510300", "510500"),
            "core_weights": (0.5, 0.5),
            "max_sector_exposure_pct": 50.0,
        }

    st.markdown("---")
    enable_attribution = st.checkbox(
        "🔬 启用归因",
        value=False,
        help="归因结果基于默认约束标定，自定义约束下结果仅作参考。"
    )
    attribution_benchmark_type = st.selectbox(
        "归因基准",
        options=['csi300', 'equal_weight'],
        format_func=lambda value: '沪深300（需历史基准快照）' if value == 'csi300' else 'ETF池等权',
        disabled=not enable_attribution,
    )
    st.session_state['enable_attribution'] = enable_attribution
    run_clicked = st.button("🧪 运行回测", type="primary", use_container_width=True)


if run_clicked:
    if not selected_codes:
        st.error("请至少选择一只ETF")
    else:
        # Step 1: 数据检查
        with st.status("正在检查数据...", expanded=True) as status:
            progress_placeholder = st.empty()
            st.write("检查数据完整性...")

            def on_data_progress(msg):
                progress_placeholder.text(msg)

            data_result = app_service.ensure_data_ready(
                selected_codes,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
                on_progress=on_data_progress,
            )

            if data_result['status'] == 'error':
                status.update(label="数据不足，请补充", state="error", expanded=True)
                st.error("❌ 数据不足，无法运行回测。请先在命令行补充数据：")
                st.code(data_result['message'], language='bash')
                st.info("💡 补充完数据后，重新点击「运行回测」即可。")
                data_ok = False
            elif data_result['status'] == 'warn':
                st.warning("⚠️ 数据存在警告，仍可继续回测（部分因子可能对部分ETF跳过）：")
                st.code(data_result['message'], language='bash')
                st.info("💡 建议后续按提示补充数据以获得更完整的因子覆盖。")
                status.update(label="数据检查通过（含警告）", state="complete", expanded=False)
                data_ok = True
            else:
                st.write("✅ 数据检查通过")
                status.update(label="数据检查完成", state="complete", expanded=False)
                data_ok = True

        # Step 2: 运行回测
        if data_ok:
            with st.spinner("正在运行回测..."):
                try:
                    result = run_backtest_for_result(
                        selected_codes,
                        start_date,
                        end_date,
                        params,
                        constraints_dict,
                        enable_attribution=enable_attribution,
                        attribution_benchmark_type=attribution_benchmark_type,
                    )
                except RuntimeError as bt_err:
                    result = None
                    st.error(f"回测失败: {bt_err}")
                st.session_state['result'] = result
                st.session_state['selected_codes_saved'] = selected_codes
                if result is not None:
                    st.success(f"✅ 多因子轮动 回测完成（{start_date} ~ {end_date}）")


result = st.session_state.get('result')
if result:
    st.markdown("### 📊 回测概览")

    data_quality = result.get('data_quality', {})
    if data_quality.get('status') == 'passed':
        st.success(f"✅ 数据质量通过（快照 {data_quality.get('snapshot_id', '-') }）")

    report_paths = result.get('report_paths', {})
    if report_paths:
        st.markdown("#### 📄 运行报告")
        report_columns = st.columns(4)
        report_labels = {
            'html': '下载 HTML 报告',
            'markdown': '下载 Markdown 报告',
            'data': '下载 JSON 事实数据',
            'manifest': '下载运行清单',
        }
        for column, report_type in zip(report_columns, ('html', 'markdown', 'data', 'manifest')):
            report_path = Path(report_paths[report_type]) if report_paths.get(report_type) else None
            if report_path and report_path.exists():
                with column:
                    st.download_button(
                        report_labels[report_type],
                        data=report_path.read_bytes(),
                        file_name=report_path.name,
                        key=f"download_{report_type}_{result.get('report_status', 'run')}",
                    )

    with st.expander("🧭 历史运行与因子治理", expanded=False):
        history = result.get('historical_comparison') or {}
        previous_summary = history.get('previous_summary')
        if previous_summary:
            st.markdown(f"**上次运行：** `{previous_summary.get('run_id', '-')}`")
            comparison = history.get('current_vs_previous') or {}
            if comparison:
                rows = []
                for metric, values in comparison.items():
                    rows.append({
                        '指标': metric,
                        '当前': values.get('current'),
                        '上次运行': values.get('reference'),
                        '差值': values.get('difference'),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("暂无上次正式运行报告，首次运行只展示基准对比。")

        shadow_candidates = history.get('shadow_candidates') or []
        if shadow_candidates:
            st.markdown("**影子运行候选**")
            st.dataframe(pd.DataFrame(shadow_candidates), use_container_width=True, hide_index=True)
        shadow_comparisons = history.get('current_vs_shadow') or []
        if shadow_comparisons:
            st.markdown("**当前策略 vs 影子候选**")
            st.json(shadow_comparisons)
        factor_candidates = result.get('factor_candidates') or []
        if factor_candidates:
            st.markdown("**因子候选状态**")
            st.dataframe(pd.DataFrame(factor_candidates), use_container_width=True, hide_index=True)
        st.caption("系统不调用 AI。下载 JSON 后由你自行交给 AI 或人工分析；候选因子不会自动进入正式策略。")

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
    st.markdown("#### 📈 Alpha 稳定性分析")
    _render_alpha_stability_section(result, PRIMARY_BENCHMARK)
    _render_factor_diagnostics_section(result)
    st.markdown("---")
    st.markdown("### 📊 归因分析")

    attribution = result.get('attribution')
    if attribution is not None:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("配置收益(%)", f"{attribution.allocation_effect:+.2f}")
        with col2:
            st.metric("选品收益(%)", f"{attribution.selection_effect:+.2f}")
        with col3:
            st.metric("总超额(%)", f"{attribution.total_excess:+.2f}")
        with col4:
            st.metric("调仓期数", f"{attribution.total_periods}")

        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("持有收益(%)", f"{attribution.hold_return:+.2f}")
        with col6:
            st.metric("换仓收益(%)", f"{attribution.switch_return:+.2f}")
        with col7:
            st.metric("换仓胜率", f"{attribution.switch_win_rate:.1%}")
        with col8:
            st.metric("滚动IR", f"{attribution.rolling_ir:.2f}")

        if not attribution.sector_breakdown.empty:
            st.markdown("#### 分赛道配置收益")
            fig_sector = px.bar(
                attribution.sector_breakdown,
                x='赛道',
                y='配置收益(%)',
                title="分赛道配置收益(%)",
                template='plotly_white',
                color='配置收益(%)',
                color_continuous_scale='RdYlGn',
            )
            fig_sector.update_layout(yaxis_title='配置收益(%)', showlegend=False)
            st.plotly_chart(fig_sector, use_container_width=True)

        if not attribution.period_breakdown.empty:
            st.markdown("#### BF归因期间走势")
            period_df = attribution.period_breakdown.copy()
            period_df['累计配置收益(%)'] = period_df['配置收益(%)'].cumsum()
            period_df['累计选品收益(%)'] = period_df['选品收益(%)'].cumsum()
            period_df['累计总超额(%)'] = period_df['总超额(%)'].cumsum()
            fig_period = px.line(
                period_df,
                x='期间结束',
                y=['累计配置收益(%)', '累计选品收益(%)', '累计总超额(%)'],
                title="BF归因累计效应(%)",
                template='plotly_white',
            )
            fig_period.update_layout(yaxis_title='累计效应(%)', legend_title='')
            st.plotly_chart(fig_period, use_container_width=True)

        if not attribution.switch_period_breakdown.empty:
            st.markdown("#### 换仓/持有收益累计走势")
            switch_df = attribution.switch_period_breakdown.copy()
            switch_df['累计持有收益(%)'] = switch_df['持有收益(%)'].cumsum()
            switch_df['累计换仓收益(%)'] = switch_df['换仓收益(%)'].cumsum()
            switch_df['累计总收益(%)'] = switch_df['总收益(%)'].cumsum()
            fig_switch = px.line(
                switch_df,
                x='期间结束',
                y=['累计持有收益(%)', '累计换仓收益(%)', '累计总收益(%)'],
                title="换仓/持有收益累计(%)",
                template='plotly_white',
            )
            fig_switch.update_layout(yaxis_title='累计收益(%)', legend_title='')
            st.plotly_chart(fig_switch, use_container_width=True)

        tab1, tab2, tab3 = st.tabs(["分赛道明细", "分期间BF归因", "换仓/持有明细"])
        with tab1:
            st.dataframe(attribution.sector_breakdown, use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(attribution.period_breakdown, use_container_width=True, hide_index=True)
        with tab3:
            st.dataframe(attribution.switch_period_breakdown, use_container_width=True, hide_index=True)
            if not attribution.etf_switch_breakdown.empty:
                st.markdown("##### 分ETF换仓明细")
                st.dataframe(attribution.etf_switch_breakdown, use_container_width=True, hide_index=True)

        benchmark_label = '沪深300' if attribution.benchmark_type == 'csi300' else 'ETF池等权组合'
        st.caption(f"基准类型：{benchmark_label}")
    else:
        attr_err = result.get('attribution_error')
        attr_status = result.get('attribution_status')
        if attr_status == 'unavailable' or attr_err:
            st.warning(f"归因不可用: {attr_err or '基准数据不足'}")
        else:
            st.info("归因结果未生成。请确保回测时已启用归因计算。")

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
    val_results = app_service.list_validation_results(factor_name="pe_cross_check")
    if val_results:
        val_rows = []
        name_map = {e['code']: e['name'] for e in ETF_UNIVERSE}
        for v in val_results:
            code = v['etf_code']
            name = name_map.get(code, '')
            if not name:
                etf_info = app_service.get_etf(code)
                name = etf_info.get('name', '') if etf_info else ''
            metrics = v.get('metrics', [])
            metric_dict = {m['name']: m for m in metrics}
            val_rows.append({
                "代码": code,
                "名称": name,
                "状态": _status_label(v['status']),
                "数据点": metric_dict.get("重合数据点", {}).get("value"),
                "相关系数": metric_dict.get("相关系数", {}).get("value"),
                "平均误差": f"{metric_dict.get('平均相对误差', {}).get('value', '-')}%",
                "通过率": f"{metric_dict.get('通过率', {}).get('value', '-')}%",
                "最新本地PE": metric_dict.get("均值比率", {}).get("value"),
                "校验时间": v.get('validated_at', '')[:19],
            })
        val_df = pd.DataFrame(val_rows)
        # object列(含None/数值混合)安全转Arrow:统一把None保留,数值列转float避免'-' str→int64失败
        for col in ("数据点", "相关系数", "最新本地PE"):
            if col in val_df.columns:
                val_df[col] = pd.to_numeric(val_df[col], errors='coerce')
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
        detail_name_map = {
            code: (app_service.get_etf(code) or {}).get('name', '')
            for code in detail_codes
        }
        col_select, col_btn = st.columns([3, 1])
        with col_select:
            detail_code = st.selectbox(
                "选择ETF查看详情",
                detail_codes,
                format_func=lambda x: f"{x} - {detail_name_map.get(x, '')}",
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
