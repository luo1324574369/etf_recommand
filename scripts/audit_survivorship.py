#!/usr/bin/env python
"""生存偏差审计脚本

检查 ETF_UNIVERSE 是否存在幸存者偏差：ETF 上市日是否晚于回测起始日。

用法:
    python scripts/audit_survivorship.py --start 2020-01-01 [--db data/etf.db]

退出码:
    0: 无生存偏差风险
    1: 存在风险（输出明细）
    2: 数据缺失无法判断
"""
import argparse
import sqlite3
import sys
from pathlib import Path

# 项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import ETF_UNIVERSE


def audit_survivorship(start_date: str, db_path: str) -> int:
    """运行生存偏差审计

    Returns:
        0=无风险, 1=有风险, 2=数据缺失
    """
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"[ERROR] 数据库不存在: {db_path}")
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 检查 etf_info 表是否存在
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='etf_info'"
    ).fetchall()
    if not tables:
        print(f"[ERROR] 数据库 {db_path} 中 etf_info 表不存在")
        conn.close()
        return 2

    late_listed = []
    missing_list_date = []
    audited_count = 0

    start_normalized = start_date.replace('-', '')

    for etf in ETF_UNIVERSE:
        code = etf['code']
        row = conn.execute(
            "SELECT list_date FROM etf_info WHERE code = ?", (code,)
        ).fetchone()

        # 数据库中无该 ETF 记录：视为不在本次审计范围内，跳过
        if row is None:
            continue

        audited_count += 1
        list_date = row['list_date']
        if not list_date:
            missing_list_date.append((code, etf['name'], 'list_date 为空'))
            continue

        # 标准化日期格式比较（支持 YYYY-MM-DD 与 YYYYMMDD 两种格式）
        list_date_normalized = list_date.replace('-', '') if '-' in list_date else list_date
        if list_date_normalized > start_normalized:
            late_listed.append((code, etf['name'], list_date))

    conn.close()

    # 输出报告
    print(f"\n{'='*60}")
    print(f"生存偏差审计报告")
    print(f"回测起始日: {start_date}")
    print(f"ETF 池大小: {len(ETF_UNIVERSE)}（本次审计 {audited_count} 只）")
    print(f"{'='*60}\n")

    if late_listed:
        print(f"⚠️  上市晚于回测起始日的 ETF（共 {len(late_listed)} 只）:")
        print(f"{'代码':<10}{'名称':<20}{'上市日期':<15}")
        print("-" * 50)
        for code, name, list_date in late_listed:
            print(f"{code:<10}{name:<20}{list_date:<15}")

    if missing_list_date:
        print(f"\n❌ 上市日期缺失（共 {len(missing_list_date)} 只）:")
        for code, name, reason in missing_list_date:
            print(f"  {code} ({name}): {reason}")

    if not late_listed and not missing_list_date:
        print("✅ 未发现生存偏差风险：所有 ETF 上市日均早于回测起始日")
        return 0
    elif late_listed:
        print(f"\n结论：发现 {len(late_listed)} 只 ETF 上市晚于回测起始日，存在前视偏差风险")
        return 1
    else:
        print(f"\n结论：{len(missing_list_date)} 只 ETF 上市日期缺失，无法完整判断")
        return 2


def main():
    parser = argparse.ArgumentParser(description='生存偏差审计')
    parser.add_argument('--start', required=True, help='回测起始日 YYYY-MM-DD')
    parser.add_argument('--db', default='data/etf.db', help='数据库路径')
    args = parser.parse_args()

    exit_code = audit_survivorship(args.start, args.db)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
