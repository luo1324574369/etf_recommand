"""Walk-Forward 多因子参数优化 CLI

运行 Walk-Forward 优化生成5个差异化预设，AST 写回 config/settings.py。

用法:
    .venv/bin/python scripts/optimize_presets.py --start 2019-01-01 --end 2024-12-31
    .venv/bin/python scripts/optimize_presets.py --dry-run  # 仅查看结果不写回
"""
import argparse
import ast
import json
import shutil
import sys
import time
from pathlib import Path
from typing import List, Dict, Any


def _build_presets_list_source(presets: List[Dict[str, Any]]) -> str:
    """构造 PARAM_PRESETS['多因子轮动'] 列表字面量源码

    Args:
        presets: [{"name": str, "params": dict|None}, ...]

    Returns:
        Python 源码字符串，形如:
        [
            {"name": "🏆 ...", "params": {"lookback_momentum": 20, ...}},
            {"name": "⚙️ 自定义参数", "params": None},
        ]
    """
    lines = ["["]
    for p in presets:
        name = p['name']
        params = p['params']
        if params is None:
            lines.append(f'    {{"name": "{name}", "params": None}},')
        else:
            params_str = ", ".join(f'"{k}": {v}' for k, v in params.items())
            lines.append(f'    {{"name": "{name}", "params": {{{params_str}}}}},')
    lines.append("]")
    return "\n".join(lines)


def update_presets_in_settings(settings_path: str, new_presets: List[Dict[str, Any]]):
    """AST 精确替换 PARAM_PRESETS['多因子轮动'] 列表

    Args:
        settings_path: settings.py 文件路径
        new_presets: 新预设列表

    Raises:
        RuntimeError: 未找到 PARAM_PRESETS['多因子轮动']
        TypeError: params 包含不可序列化的对象
    """
    src = Path(settings_path).read_text(encoding='utf-8')
    tree = ast.parse(src)

    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'PARAM_PRESETS':
                    for key_node, value_node in zip(node.value.keys, node.value.values):
                        if isinstance(key_node, ast.Constant) and key_node.value == "多因子轮动":
                            target_node = value_node
                            break
            if target_node:
                break

    if target_node is None:
        raise RuntimeError("未找到 PARAM_PRESETS['多因子轮动']")

    new_list_src = _build_presets_list_source(new_presets)

    src_bytes = src.encode('utf-8')
    lines_bytes = src_bytes.splitlines(keepends=True)
    start_offset = sum(len(l) for l in lines_bytes[:target_node.lineno - 1]) + target_node.col_offset
    end_offset = sum(len(l) for l in lines_bytes[:target_node.end_lineno - 1]) + target_node.end_col_offset
    replaced = (src_bytes[:start_offset] + new_list_src.encode('utf-8') + src_bytes[end_offset:]).decode('utf-8')

    Path(settings_path).write_text(replaced, encoding='utf-8')


def print_progress(current, total, msg):
    """进度回调，输出到 stderr 避免污染 stdout JSON"""
    print(f"({current}/{total}) {msg}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Walk-Forward 多因子参数优化')
    parser.add_argument('--start', type=str, default='2019-01-01', help='回测起始日期')
    parser.add_argument('--end', type=str, default='2024-12-31', help='回测结束日期')
    parser.add_argument('--max-combinations', type=int, default=144, help='最大参数组合数')
    parser.add_argument('--dry-run', action='store_true', help='仅打印结果不写回 settings.py')
    parser.add_argument('--no-backup', action='store_true', help='跳过 .bak 备份')
    parser.add_argument('--output', type=str, default=None, help='输出 JSON 报告到文件')
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from config.settings import ETF_UNIVERSE, DB_PATH
    from data.storage.db import init_db, get_db
    from data.storage.price_repo import PriceRepository
    from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES
    from strategy.walk_forward import generate_walk_forward_presets
    from tabulate import tabulate

    init_db(DB_PATH)
    price_repo = PriceRepository(get_db(DB_PATH))

    # 加载行情数据
    data_dict = {}
    for etf in ETF_UNIVERSE:
        prices = price_repo.get_daily_price(etf['code'])
        if prices and len(prices) >= 120:
            import pandas as pd
            data_dict[etf['code']] = pd.DataFrame(prices)
        else:
            print(f"⚠️ {etf['code']} 数据不足，跳过", file=sys.stderr)

    if not data_dict:
        print("❌ 无可用ETF数据", file=sys.stderr)
        sys.exit(1)

    print(f"加载 {len(data_dict)} 只ETF数据", file=sys.stderr)

    # 跑 Walk-Forward 优化
    start_time = time.time()
    wf_result = generate_walk_forward_presets(
        data_dict,
        args.start,
        args.end,
        MULTI_FACTOR_PARAM_RANGES,
        max_combinations=args.max_combinations,
        progress_callback=print_progress,
    )
    elapsed = time.time() - start_time

    if not wf_result.get('presets'):
        print("❌ 优化未生成预设，请检查数据是否充足", file=sys.stderr)
        print(f"  验证窗口数: {len(wf_result.get('windows', []))}", file=sys.stderr)
        sys.exit(1)

    # 构造新预设列表
    new_presets = []
    for p in wf_result['presets']:
        new_presets.append({
            "name": p['name'],
            "params": p['params'],
        })
    new_presets.append({"name": "⚙️ 自定义参数", "params": None})

    # 打印报告到 stdout
    print("\n" + "=" * 60)
    print(f"Walk-Forward 多因子参数优化 ({args.start} ~ {args.end})")
    print(f"ETF数: {len(data_dict)} | 参数组合: {args.max_combinations} | 验证窗口: {len(wf_result.get('windows', []))}")
    print(f"耗时: {elapsed:.1f}s")
    print("=" * 60 + "\n")

    table_rows = []
    for p in wf_result['presets']:
        m = p.get('metrics', {})
        table_rows.append([
            p['name'],
            f"{m.get('full_annual_return', 0):.2f}",
            f"{m.get('full_sharpe_ratio', 0):.2f}",
            f"{m.get('full_max_drawdown', 0):.2f}",
            f"{m.get('cagr', 0):.2f}",
            m.get('full_num_trades', 0),
        ])
    print(tabulate(table_rows,
                   headers=['预设名称', '全周期年化(%)', '全周期夏普', '全周期回撤(%)', '窗口CAGR(%)', '交易次数'],
                   tablefmt='pipe'))

    # 写回 settings.py
    if not args.dry_run:
        settings_path = Path(__file__).resolve().parent.parent / 'config' / 'settings.py'
        if not args.no_backup:
            backup_path = settings_path.with_suffix('.py.bak')
            shutil.copy2(settings_path, backup_path)
            print(f"\n📦 原文件备份至 {backup_path}", file=sys.stderr)

        try:
            update_presets_in_settings(str(settings_path), new_presets)
            print(f"\n✅ 已写回 {settings_path}", file=sys.stderr)
            print("💡 请重启 Streamlit 使新预设生效", file=sys.stderr)
        except Exception as e:
            print(f"\n❌ 写回失败: {e}", file=sys.stderr)
            if not args.no_backup:
                backup_path = settings_path.with_suffix('.py.bak')
                shutil.copy2(backup_path, settings_path)
                print(f"🔄 已从 {backup_path} 回滚", file=sys.stderr)
            sys.exit(2)
    else:
        print("\n🔍 --dry-run 模式，未写回 settings.py", file=sys.stderr)

    # 输出 JSON 报告
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(wf_result, f, ensure_ascii=False, indent=2, default=str)
        print(f"📄 JSON 报告已保存至 {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
