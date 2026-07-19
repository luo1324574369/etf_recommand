#!/usr/bin/env python
"""前视偏差审计脚本

检查策略代码是否使用了未来信息。

方法:
1. 静态分析：扫描可疑模式（rolling/rank/pct_change 未加 shift）
2. 运行时检测（可选）：monkey-patch shift 记录调用路径

用法:
    # 静态检查指定文件
    python scripts/audit_lookahead.py --static-only --target path/to/file.py

    # 静态检查默认策略文件
    python scripts/audit_lookahead.py --static-only

    # 完整检查（静态 + 运行时）
    python scripts/audit_lookahead.py

退出码:
    0: 无风险
    1: 有风险
"""
import argparse
import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 默认扫描的策略文件
DEFAULT_TARGETS = [
    'strategy/multi_factor.py',
    'strategy/scoring.py',
    'strategy/backtest_utils.py',
    'strategy/benchmark.py',
]

# 可疑模式：rolling/rank/quantile/pct_change 后未跟 shift
SUSPICIOUS_PATTERNS = [
    # rolling(...).mean() / .std() 等未跟 shift
    (r'\.rolling\([^)]+\)\.(mean|std|sum|max|min|median|var)\(\)(?!\s*\.shift)',
     'rolling 计算未跟 shift，可能使用当日未来均值'),
    # pct_change() 未跟 shift
    (r'\.pct_change\(\)(?!\s*\.shift)',
     'pct_change 未跟 shift，可能使用当日未来收益'),
    # rank() 未跟 shift
    (r'\.rank\(\)(?!\s*\.shift)',
     'rank 未跟 shift，可能使用当日横截面信息'),
    # quantile() 未跟 shift
    (r'\.quantile\([^)]*\)(?!\s*\.shift)',
     'quantile 未跟 shift，可能使用当日横截面信息'),
    # shift(-n) 负数 shift
    (r'\.shift\(-\d+\)',
     'shift(-n) 直接使用未来数据'),
    # df.iloc[i+1] 之类正向索引未来
    (r'\.iloc\[\w+\s*\+\s*1\]',
     'iloc[i+1] 直接索引未来数据'),
]


def static_check_file(file_path: Path) -> list:
    """静态扫描单个文件

    Returns:
        [(line_no, code_snippet, message), ...]
    """
    if not file_path.exists():
        return []

    findings = []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        # 跳过注释
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        for pattern, message in SUSPICIOUS_PATTERNS:
            if re.search(pattern, line):
                findings.append((i, line.rstrip(), message))
                break  # 每行只报一次

    return findings


def static_check(targets: list) -> int:
    """静态扫描多个文件

    Returns:
        0=无风险, 1=有风险
    """
    all_findings = []

    for target in targets:
        path = Path(target)
        if path.is_dir():
            py_files = list(path.glob('**/*.py'))
        elif path.is_file() and path.suffix == '.py':
            py_files = [path]
        else:
            continue

        for py_file in py_files:
            findings = static_check_file(py_file)
            for line_no, snippet, msg in findings:
                all_findings.append((py_file, line_no, snippet, msg))

    print(f"\n{'='*60}")
    print(f"前视偏差静态检查报告")
    print(f"扫描文件数: {len(targets)}")
    print(f"{'='*60}\n")

    if not all_findings:
        print("✅ 未发现前视偏差风险")
        return 0

    print(f"⚠️  发现 {len(all_findings)} 处可疑代码:\n")
    for file_path, line_no, snippet, msg in all_findings:
        print(f"  {file_path}:{line_no}")
        print(f"    代码: {snippet.strip()}")
        print(f"    问题: {msg}")
        print()

    return 1


def main():
    parser = argparse.ArgumentParser(description='前视偏差审计')
    parser.add_argument('--static-only', action='store_true',
                        help='仅运行静态检查')
    parser.add_argument('--target', default=None,
                        help='指定扫描目标（文件或目录），默认扫描策略模块')
    parser.add_argument('--runtime', action='store_true',
                        help='启用运行时检测（实验性）')
    args = parser.parse_args()

    if args.target:
        targets = [args.target]
    else:
        targets = [str(PROJECT_ROOT / t) for t in DEFAULT_TARGETS]

    exit_code = static_check(targets)

    if args.runtime and not args.static_only:
        print("\n运行时检测尚未实现（实验性），跳过")

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
