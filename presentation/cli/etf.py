"""
ETF 详情命令行展示模块
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


def _color_change(val) -> str:
    if val is None:
        return gray("-")
    v = float(val)
    if v > 0:
        return green(f"+{v:.2%}")
    elif v < 0:
        return red(f"{v:.2%}")
    return gray("0.00%")


def render_etf_detail(etf_info: dict, factor_values: dict, price_history: list[dict]):
    """
    在终端渲染单个ETF的详细信息

    参数:
        etf_info: ETF基础信息
        factor_values: 因子计算结果
        price_history: 近30天行情数据
    """
    code = etf_info.get("code", "")
    name = etf_info.get("name", code)
    sector = etf_info.get("sector", "-")
    etype = etf_info.get("type", "-")

    # ─── 基本信息 ───
    print(section(f"ETF 详情  {name} ({code})", color="cyan"))
    print(f"  代码: {blue(code)}  名称: {bold(name)}")
    print(f"  板块: {cyan(sector)}  类型: {gray(etype)}")
    print()

    # ─── 因子指标 ───
    print(section("因子指标", color="blue"))

    # 动量
    mom = factor_values.get("momentum")
    if mom is not None:
        color = "green" if mom > 0 else "red"
        indicator = green("▲ 强势") if mom > 0.05 else (yellow("△ 温和") if mom > 0 else red("▼ 弱势"))
        print(f"  动量因子(10日)  {indicator}  涨跌幅: {green(f'+{mom:.2%}') if mom > 0 else red(f'{mom:.2%}')}")

    # 趋势
    trend = factor_values.get("trend", {})
    if trend:
        above = trend.get("above_ma")
        ma_val = trend.get("ma_value")
        price = trend.get("price")
        if above is True:
            status = green("✓ 在20日均线上方（上升趋势）")
        elif above is False:
            status = red("✗ 在20日均线下方（下降趋势）")
        else:
            status = gray("趋势未知")
        print(f"  趋势因子(20日)  {status}")
        if ma_val is not None and price is not None:
            diff = (price - ma_val) / ma_val * 100
            print(f"    {gray('20日均线:')} {gray(f'{ma_val:.4f}')}  {gray('当前价:')} {gray(f'{price:.4f}')}  {gray('偏离:')} {_color_change(diff/100)}")

    # 量能
    vol = factor_values.get("volume")
    if vol is not None:
        if vol >= 1.5:
            status = green(f"▲ 明显放量（量比 {vol:.2f}）")
        elif vol >= 1.1:
            status = yellow(f"△ 温和放量（量比 {vol:.2f}）")
        else:
            status = red(f"▼ 缩量（量比 {vol:.2f}）")
        print(f"  量能因子(5/20日)  {status}")

    # 综合得分
    score = factor_values.get("score")
    if score is not None:
        if score >= 0.5:
            level = green("★★★★★ 强力推荐")
        elif score >= 0.3:
            level = yellow("★★★★☆ 建议关注")
        else:
            level = gray("★★★☆☆ 观望")
        print(f"\n  综合得分: {level} ({score:.4f})")

    print()

    # ─── 近期行情 ───
    if price_history:
        print(section("近期行情（最近20个交易日）", color="yellow"))

        # 表头
        widths = [12, 10, 10, 10, 10, 14, 16]
        print(table_top(widths))
        print(header_row(["日期", "开盘", "最高", "最低", "收盘", "涨跌幅", "成交量"], widths))
        print(table_mid(widths))

        # 最近20条（倒序，最新的在前面）
        rows = list(reversed(price_history[-20:]))
        prev_close = None
        for i, p in enumerate(rows):
            trade_date = str(p.get("trade_date", "-"))
            open_p = p.get("open", 0)
            high = p.get("high", 0)
            low = p.get("low", 0)
            close = p.get("close", 0)
            volume = p.get("volume", 0)
            amount = p.get("amount", 0)

            # 涨跌幅
            if prev_close is not None and prev_close > 0:
                chg_pct = (close - prev_close) / prev_close
                chg_str = _color_change(chg_pct)
            else:
                chg_pct = 0
                chg_str = gray("-")

            prev_close = close

            # 成交量格式化
            if amount >= 1e8:
                vol_str = f"{amount/1e8:.2f}亿"
            elif amount >= 1e4:
                vol_str = f"{amount/1e4:.0f}万"
            else:
                vol_str = f"{amount:.0f}"

            # 最新行高亮
            if i == 0:
                print(
                    row(
                        [trade_date, f"{open_p:.3f}", f"{high:.3f}", f"{low:.3f}",
                         bold(green(f"{close:.3f}")), chg_str, vol_str],
                        widths,
                        colors=["white", "white", "white", "white", "green", "white", "white"],
                    )
                )
            else:
                print(
                    row(
                        [trade_date, f"{open_p:.3f}", f"{high:.3f}", f"{low:.3f}",
                         f"{close:.3f}", chg_str, vol_str],
                        widths,
                    )
                )

        print(table_bot(widths))
        print()
