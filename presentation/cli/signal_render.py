"""
策略信号命令行展示模块
"""

from .render import (
    console,
    section,
    divider,
    table_top,
    table_mid,
    table_bot,
    header_row,
    row,
    green,
    yellow,
    red,
    blue,
    cyan,
    bold,
    gray,
    bar,
)


def _fmt_score(score: float) -> str:
    if score >= 0.6:
        return green(f"{score:.4f}")
    elif score >= 0.3:
        return yellow(f"{score:.4f}")
    else:
        return red(f"{score:.4f}")


def _fmt_momentum(val) -> str:
    if val is None:
        return gray("-")
    v = float(val)
    if v > 0.05:
        return green(f"+{v:.2%}")
    elif v > 0:
        return yellow(f"+{v:.2%}")
    else:
        return red(f"{v:.2%}")


def _fmt_volume(val) -> str:
    if val is None:
        return gray("-")
    v = float(val)
    if v >= 1.5:
        return green(f"{v:.2f}")
    elif v >= 1.1:
        return yellow(f"{v:.2f}")
    else:
        return red(f"{v:.2f}")


def _fmt_trend(factor_values: dict) -> str:
    trend = factor_values.get("trend", {})
    if not trend:
        return gray("-")
    above = trend.get("above_ma")
    if above is True:
        return green("↗ 上升")
    elif above is False:
        return red("↘ 下降")
    return gray("-")


def render_signals(results: list[dict], strategy_name: str, signal_date: str, etf_name_map: dict = None):
    """
    在终端渲染策略选股结果

    参数:
        results: 策略引擎返回的选股结果列表
        strategy_name: 策略名称
        signal_date: 信号日期
        etf_name_map: {code: name} 映射
    """
    if etf_name_map is None:
        etf_name_map = {}

    name_map = etf_name_map or {}

    # ─── 标题区 ───
    print()
    print(section(f"策略信号  {strategy_name}", color="cyan"))
    print(f"  信号日期：{bold(signal_date)}")
    print(f"  选出数量：{bold(str(len(results)))} 只")
    print()

    if not results:
        console.warn("没有通过筛选的ETF，请检查策略参数或数据")
        print()
        return

    # ─── 主表格 ───
    # 5列：排名 | 代码+名称 | 综合得分 | 动量 | 量比
    widths = [6, 28, 12, 14, 14]

    print(table_top(widths))
    print(header_row(["排名", "代码 · 名称", "综合得分", "动量(10日)", "量比(5/20日)"], widths))
    print(table_mid(widths))

    for r in results:
        code = r["code"]
        name = name_map.get(code, code)
        rank = r["rank"]
        score = r.get("score", 0)
        fv = r.get("factor_values", {})

        mom = fv.get("momentum")
        vol = fv.get("volume")
        trend_text = _fmt_trend(fv)

        # 代码+名称列
        if score >= 0.5:
            rank_str = green(f"#{rank}")
        elif score >= 0.3:
            rank_str = yellow(f"#{rank}")
        else:
            rank_str = red(f"#{rank}")

        code_cell = f"{blue(code)} {bold(name)}"

        print(
            row(
                [rank_str, code_cell, _fmt_score(score), _fmt_momentum(mom), _fmt_volume(vol)],
                widths,
                colors=["white", "white", "white", "white", "white"],
            )
        )

    print(table_bot(widths))

    # ─── 详情区块 ───
    print()
    print(section("入选理由详情", color="blue"))

    for r in results[:5]:
        code = r["code"]
        name = name_map.get(code, code)
        fv = r.get("factor_values", {})
        score = r.get("score", 0)
        rank = r["rank"]

        print(f"  {green(f'#{rank}')}  {bold(blue(code))} {bold(name)}  {gray('得分:')} {gray(f'{score:.4f}')}")
        print(f"  {divider(char='─', width=60, color='gray')}")

        # 动量
        mom = fv.get("momentum")
        if mom is not None:
            direction = green("↑") if mom > 0 else red("↓")
            print(
                f"    {gray('动量:')} {direction} {_fmt_momentum(mom)}  "
                f"{gray('近10日价格变化率')}"
            )

        # 趋势
        trend = fv.get("trend", {})
        if trend:
            above = trend.get("above_ma")
            ma_val = trend.get("ma_value")
            price = trend.get("price")
            status = green("✓ 在均线上方") if above else red("✗ 在均线下方")
            print(f"    {gray('趋势:')} {status}  {gray('MA20:') if ma_val else ''} {gray(str(round(ma_val, 4)) if ma_val else '')} {gray('当前价:')} {gray(str(round(price, 4)) if price else '')}")

        # 量比
        vol = fv.get("volume")
        if vol is not None:
            if vol >= 1.5:
                vol_indicator = green("▲ 明显放量")
            elif vol >= 1.1:
                vol_indicator = yellow("△ 温和放量")
            else:
                vol_indicator = red("▼ 缩量")
            print(f"    {gray('量能:')} {vol_indicator}  {gray('量比:')} {_fmt_volume(vol)}  {gray('近5日均量/近20日均量')}")

        # 归一化得分
        mom_norm = fv.get("momentum_norm")
        vol_norm = fv.get("volume_norm")
        if mom_norm is not None and vol_norm is not None:
            print(f"    {gray('动量排名:')} {gray(bar(mom_norm, 1.0, 15, 'green'))} {gray(f'{mom_norm:.2f}')}")
            print(f"    {gray('量能排名:')} {gray(bar(vol_norm, 1.0, 15, 'cyan'))} {gray(f'{vol_norm:.2f}')}")

        print()

    # ─── 操作提示 ───
    print(divider(color="gray"))
    print(f"  {gray('💡 提示:')} 可使用 {cyan('python scripts/update_data.py')} 更新数据，{cyan('python scripts/run_strategy.py')} 重新选股")
    print()


def render_signals_simple(results: list[dict], strategy_name: str, signal_date: str, etf_name_map: dict = None):
    """
    简化版信号展示（用于嵌入在其他输出中）
    """
    name_map = etf_name_map or {}
    print(f"\n策略: {strategy_name} | 日期: {signal_date}")
    print(f"{'排名':<6}{'代码':<12}{'名称':<15}{'得分':<10}{'动量':<12}{'量比':<12}")
    print(divider(char="-", width=70, color="gray"))

    for r in results:
        code = r["code"]
        name = name_map.get(code, "")
        fv = r.get("factor_values", {})
        mom = fv.get("momentum", "")
        vol = fv.get("volume", "")
        if isinstance(mom, float):
            mom = f"{mom:.4f}"
        if isinstance(vol, float):
            vol = f"{vol:.4f}"
        print(f"{r['rank']:<6}{code:<12}{name:<15}{r['score']:<10.4f}{str(mom):<12}{str(vol):<12}")
