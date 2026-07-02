"""
策略说明文档生成器
每次修改策略配置后自动生成大白话说明文档
"""

import os
import sys
from datetime import date

# 因子大白话说明
FACTOR_DESCRIPTIONS = {
    "MomentumFactor": {
        "period": {
            5: "最近5个交易日",
            10: "最近10个交易日",
            20: "最近20个交易日",
            60: "最近60个交易日",
        },
        "description": "动量因子：看最近N个交易日涨了多少。涨得多的说明资金在涌入，"
                       "动量越强代表短期趋势越强。但也要小心涨太多已经透支了。",
        "good": "动量值为正且越高越好，说明近期强势上涨",
        "bad": "动量值为负，说明近期在下跌，不选",
    },
    "TrendFactor": {
        "period": {
            10: "10日均线",
            20: "20日均线",
            60: "60日均线",
        },
        "description": "趋势因子：看价格是否在均线之上。站在均线上说明是上升趋势，"
                       "跌破均线说明可能转弱。均线多头排列（短>中>长）最强。",
        "good": "价格在均线以上，趋势向上",
        "bad": "价格在均线以下，趋势向下，不选",
    },
    "VolumeFactor": {
        "short_period": {
            3: "最近3天",
            5: "最近5天",
            10: "最近10天",
        },
        "long_period": {
            20: "过去20天平均",
            60: "过去60天平均",
        },
        "description": "量能因子：看最近N天的平均成交量是过去M天平均的多少倍。量比>1表示放量，"
                       "说明有资金在参与；量比<1表示缩量，可能观望情绪浓。",
        "good": "量比>1.2，近期明显放量，有资金推动",
        "bad": "量比<0.8，缩量，缺少资金关注",
    },
}

# 筛选器大白话说明
FILTER_DESCRIPTIONS = {
    "TrendFilter": {
        "description": "趋势筛选：必须站在20日均线上才保留，跌破均线的直接淘汰。",
        "action": "只保留价格在均线上方的ETF",
    },
    "MomentumFilter": {
        "description": "动量排名筛选：只保留动量排名前N%的ETF，淘汰弱势的。",
        "action": "动量排名靠前才有机会",
    },
    "VolumeFilter": {
        "min_ratio": {
            1.0: "量比>1.0（略放量）",
            1.1: "量比>1.1（温和放量）",
            1.2: "量比>1.2（明显放量）",
            1.5: "量比>1.5（大幅放量）",
        },
        "description": "量能筛选：量比低于阈值的直接淘汰。量能是趋势的燃料，没有量能支撑的上涨难以持续。",
        "action": "量比必须达到阈值才保留",
    },
}

# 策略类型说明
STRATEGY_TYPE_DESCRIPTIONS = {
    "momentum_weekly": "周频板块动量轮动：每周调仓一次，选择近期最强的板块ETF，"
                       "追随资金流向做轮动。核心逻辑是'强者恒强'，动量效应在A股行业ETF中较为显著。",
    "value_weekly": "周频价值策略：选择估值低、业绩好的ETF。适合长期持有，风险相对较小。",
    "dual_thrust": "双均线策略：快线上穿慢线买入，快线下穿慢线卖出。趋势明确时效果好，震荡市容易反复止损。",
}


def _get_factor_desc(factor_class: str, params: dict) -> dict:
    """生成单个因子的大白话说明"""
    info = FACTOR_DESCRIPTIONS.get(factor_class, {})
    desc = info.get("description", f"{factor_class}：一种选股因子")

    if factor_class == "MomentumFactor":
        period = params.get("period", 10)
        period_text = info.get("period", {}).get(period, f"{period}个交易日")
        detail = f"计算方式：最新收盘价相比{period_text}前涨了多少"
        good = info.get("good", "")
        return {"desc": desc, "detail": detail, "good": good, "bad": info.get("bad", "")}

    elif factor_class == "TrendFactor":
        period = params.get("period", 20)
        ma_text = info.get("period", {}).get(period, f"{period}日均线")
        detail = f"计算方式：最新价格是否在{ma_text}之上"
        good = info.get("good", "")
        return {"desc": desc, "detail": detail, "good": good, "bad": info.get("bad", "")}

    elif factor_class == "VolumeFactor":
        short = params.get("short_period", 5)
        long = params.get("long_period", 20)
        short_text = info.get("short_period", {}).get(short, f"最近{short}天")
        long_text = info.get("long_period", {}).get(long, f"过去{long}天平均")
        detail = f"计算方式：{short_text}均量 / {long_text}均量，结果就是'量比'"
        good = info.get("good", "")
        return {"desc": desc, "detail": detail, "good": good, "bad": info.get("bad", "")}

    return {"desc": desc, "detail": "", "good": "", "bad": ""}


def _get_filter_desc(filter_class: str, params: dict) -> dict:
    """生成单个筛选器的大白话说明"""
    info = FILTER_DESCRIPTIONS.get(filter_class, {})
    desc = info.get("description", f"{filter_class}：一种筛选规则")

    if filter_class == "TrendFilter":
        detail = info.get("action", "只保留趋势向上的")
        return {"desc": desc, "action": detail}

    elif filter_class == "MomentumFilter":
        top_pct = params.get("top_pct", 0.3)
        pct_text = f"{int(top_pct * 100)}%" if top_pct < 1 else f"{int(top_pct)}%"
        detail = f"只保留动量排名前{pct_text}的ETF，比如24只里只留前{int(24 * top_pct)}只"
        return {"desc": desc, "action": detail}

    elif filter_class == "VolumeFilter":
        min_ratio = params.get("min_ratio", 1.2)
        ratio_text = info.get("min_ratio", {}).get(min_ratio, f"量比>{min_ratio}")
        detail = f"量比{ratio_text}才保留，否则淘汰"
        return {"desc": desc, "action": detail}

    return {"desc": desc, "action": info.get("action", "")}


def generate_strategy_doc(config: dict, output_path: str = None) -> str:
    """根据策略配置生成大白话说明文档"""
    name = config.get("name", "未命名策略")
    strategy_type = config.get("strategy_type", "")
    top_n = config.get("top_n", 5)
    score_weights = config.get("score_weights", {})
    factors = config.get("factors", [])
    filters = config.get("filters", [])
    position = config.get("position", {})

    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  策略说明文档")
    lines.append(f"{'='*60}")
    lines.append(f"")
    lines.append(f"策略名称：{name}")
    lines.append(f"生成日期：{date.today().isoformat()}")
    lines.append(f"")

    # 策略一句话概括
    type_desc = STRATEGY_TYPE_DESCRIPTIONS.get(strategy_type, "")
    if type_desc:
        lines.append(f"{'─'*60}")
        lines.append(f"【一句话概括】")
        lines.append(f"  {type_desc}")
        lines.append(f"")

    # 一、核心逻辑
    lines.append(f"{'─'*60}")
    lines.append(f"【一、核心逻辑】")
    lines.append(f"  每周从 {len(factors)} 个维度打分，选出综合得分最高的 {top_n} 只ETF。")
    lines.append(f"")

    # 权重可视化
    if score_weights:
        lines.append(f"  得分权重分配：")
        for factor, weight in score_weights.items():
            bar = "█" * int(weight * 20) + "░" * (20 - int(weight * 20))
            lines.append(f"    {factor:<12} {bar} {weight:.0%}")
        lines.append(f"")

    # 二、因子详解
    lines.append(f"{'─'*60}")
    lines.append(f"【二、打分因子详解（共{len(factors)}个）】")
    lines.append(f"")

    for i, factor_cfg in enumerate(factors, 1):
        cls = factor_cfg.get("class", "")
        params = {k: v for k, v in factor_cfg.items() if k != "class"}
        info = _get_factor_desc(cls, params)
        weight = score_weights.get(info.get("desc", "").split("：")[0], 0)
        lines.append(f"  因子{i}：{cls}")
        lines.append(f"    → {info['desc']}")
        lines.append(f"    → 计算：{info['detail']}")
        if info['good']:
            lines.append(f"    → 好的情况：{info['good']}")
        if info['bad']:
            lines.append(f"    → 坏的情况：{info['bad']}")
        lines.append(f"")

    # 三、筛选器
    lines.append(f"{'─'*60}")
    lines.append(f"【三、剔除规则（共{len(filters)}个，全部通过才保留）】")
    lines.append(f"")

    for i, filter_cfg in enumerate(filters, 1):
        cls = filter_cfg.get("class", "")
        enabled = filter_cfg.get("enabled", True)
        params = {k: v for k, v in filter_cfg.items() if k not in ("class", "enabled")}
        info = _get_filter_desc(cls, params)
        status = "✅ 启用" if enabled else "❌ 禁用"
        lines.append(f"  规则{i}：{cls} [{status}]")
        lines.append(f"    → {info['desc']}")
        if info['action'] and enabled:
            lines.append(f"    → 具体要求：{info['action']}")
        lines.append(f"")

    # 四、选出多少只
    lines.append(f"{'─'*60}")
    lines.append(f"【四、最终输出】")
    lines.append(f"  经过打分 + 筛选后，每次选出综合得分最高的 {top_n} 只ETF作为推荐。")
    if position:
        max_single = position.get("max_single_pct", 1.0)
        max_total = position.get("max_total_pct", 1.0)
        lines.append(f"  每只ETF最高仓位：{max_single:.0%}（即最多花 {max_single:.0%} 的钱买1只）")
        lines.append(f"  最高总仓位：{max_total:.0%}（留 {(1-max_total):.0%} 现金备用）")
    lines.append(f"")

    # 五、止损规则
    exit_rules = config.get("exit_rules", {})
    if exit_rules:
        lines.append(f"{'─'*60}")
        lines.append(f"【五、止损规则】")
        lines.append(f"  触发以下任一条件就考虑卖出：")
        if exit_rules.get("max_loss_pct"):
            lines.append(f"  - 亏损超过 {exit_rules['max_loss_pct']:.0%} 时止损")
        if exit_rules.get("below_ma20"):
            lines.append(f"  - 价格跌破20日均线时退出")
        if exit_rules.get("drop_out_of_top_n"):
            lines.append(f"  - 持仓ETF掉出当前排名前{top_n}时换仓")
        lines.append(f"")

    # 六、调仓频率
    freq = config.get("rebalance_freq", "weekly")
    freq_map = {"daily": "每天", "weekly": "每周", "monthly": "每月"}
    lines.append(f"{'─'*60}")
    lines.append(f"【六、调仓频率】")
    lines.append(f"  {freq_map.get(freq, freq)}调仓一次。")
    lines.append(f"  注意：调仓有手续费，频繁调仓可能吃掉利润。")
    lines.append(f"")

    # 七、完整配置
    lines.append(f"{'─'*60}")
    lines.append(f"【七、原始配置（技术参考）】")
    lines.append(f"  {config}")
    lines.append(f"")
    lines.append(f"{'='*60}")

    doc = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(doc)
        print(f"策略说明文档已生成：{output_path}")

    return doc


if __name__ == "__main__":
    # 演示：生成当前策略的说明文档
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.settings import STRATEGY_CONFIG, DEFAULT_STRATEGY

    config = STRATEGY_CONFIG[DEFAULT_STRATEGY]
    output = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs",
        "strategy_doc.md",
    )
    os.makedirs(os.path.dirname(output), exist_ok=True)
    doc = generate_strategy_doc(config, output)
    print()
    print(doc)
