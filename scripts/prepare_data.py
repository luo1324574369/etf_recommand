"""
数据准备脚本 - 批量补充ETF行情和PE历史数据

使用方法:
    # 补充所有ETF
    .venv/bin/python scripts/prepare_data.py

    # 补充指定ETF
    .venv/bin/python scripts/prepare_data.py 510300 510500

    # 仅补充行情数据
    .venv/bin/python scripts/prepare_data.py --prices-only

    # 仅补充PE数据
    .venv/bin/python scripts/prepare_data.py --pe-only
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from config.settings import ETF_UNIVERSE, DB_PATH, TUSHARE_TOKEN
from data.sources.hybrid_source import HybridDataSource
from data.storage.db import init_db, get_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo

PE_MIN_RECORDS = 100
PE_NOT_APPLICABLE = {"159985", "518880", "159920", "513100", "512200"}


def main():
    parser = argparse.ArgumentParser(description="批量补充ETF行情和PE历史数据")
    parser.add_argument("codes", nargs="*", help="指定ETF代码（不指定则处理全部）")
    parser.add_argument("--prices-only", action="store_true", help="仅补充行情数据")
    parser.add_argument("--pe-only", action="store_true", help="仅补充PE历史数据")
    parser.add_argument("--start", default="2019-01-01", help="开始日期")
    parser.add_argument("--end", default="2024-12-31", help="结束日期")
    args = parser.parse_args()

    init_db(str(DB_PATH))
    data_source = HybridDataSource(tushare_token=TUSHARE_TOKEN)
    price_repo = PriceRepository(get_db(str(DB_PATH)))
    etf_repo = ETFRepository(get_db(str(DB_PATH)))
    valuation_repo = ValuationRepo(str(DB_PATH))

    # 确定要处理的ETF
    if args.codes:
        selected_codes = args.codes
    else:
        selected_codes = [e["code"] for e in ETF_UNIVERSE]

    print(f"待处理ETF: {len(selected_codes)} 只")
    print(f"日期范围: {args.start} ~ {args.end}")

    # Step 1: 行情数据
    if not args.pe_only:
        print(f"\n{'='*60}")
        print("Step 1: 检查并补充行情数据")
        print(f"{'='*60}")
        for idx, code in enumerate(selected_codes, 1):
            existing = price_repo.get_daily_price(code, args.start, args.end)
            if len(existing) >= 20:
                print(f"  [{idx}/{len(selected_codes)}] {code}: ✅ {len(existing)}条")
                continue

            print(f"  [{idx}/{len(selected_codes)}] {code}: 补充中...（现有{len(existing)}条）")
            try:
                price_data = data_source.get_daily_price(code, args.start, args.end)
                inserted = price_repo.insert_daily_price(code, price_data)
                print(f"    ✅ 新增 {inserted} 条")
            except Exception as e:
                print(f"    ❌ 失败: {e}")

    # Step 2: PE历史数据
    if not args.prices_only:
        print(f"\n{'='*60}")
        print("Step 2: 检查并补充PE历史数据")
        print(f"{'='*60}")

        codes_need_pe = []
        for code in selected_codes:
            if code in PE_NOT_APPLICABLE:
                continue
            count = valuation_repo.get_pe_history_count(code)
            if count < PE_MIN_RECORDS:
                codes_need_pe.append(code)
                print(f"  {code}: ❌ {count}条（需要补充）")
            else:
                print(f"  {code}: ✅ {count}条")

        if codes_need_pe:
            print(f"\n共 {len(codes_need_pe)} 只ETF需要补充PE数据: {codes_need_pe}")
            print("开始批量获取（按ts_code优化，约500次API调用）...")

            def on_progress(msg):
                print(f"  [进度] {msg}", flush=True)

            batch_result = data_source.batch_get_pe_history(codes_need_pe, on_progress=on_progress)

            for code in codes_need_pe:
                pe_data = batch_result.get(code, [])
                if pe_data:
                    valuation_repo.batch_insert_pe_history(code, pe_data)
                    print(f"  {code}: ✅ 写入 {len(pe_data)} 条")
                else:
                    # 尝试单独获取（fallback到行业分类法）
                    print(f"  {code}: 批量获取失败，尝试单独获取...")
                    try:
                        pe_data = data_source.get_index_pe_history(code)
                        if pe_data:
                            valuation_repo.batch_insert_pe_history(code, pe_data)
                            print(f"  {code}: ✅ 单独获取 {len(pe_data)} 条")
                        else:
                            print(f"  {code}: ❌ 无法获取PE数据")
                    except Exception as e:
                        print(f"  {code}: ❌ 失败: {e}")
        else:
            print("  所有ETF的PE数据已充足，无需补充")

    # 汇总
    print(f"\n{'='*60}")
    print("数据准备完成")
    print(f"{'='*60}")
    ready = 0
    for code in selected_codes:
        price_count = len(price_repo.get_daily_price(code, args.start, args.end))
        if code in PE_NOT_APPLICABLE:
            pe_status = "⏭️ 跳过"
        else:
            pe_count = valuation_repo.get_pe_history_count(code)
            pe_status = f"✅ {pe_count}条" if pe_count >= PE_MIN_RECORDS else f"❌ {pe_count}条"
        price_status = "✅" if price_count >= 20 else "❌"
        print(f"  {code}: 行情{price_status} {price_count}条 | PE {pe_status}")
        if price_count >= 20 and (code in PE_NOT_APPLICABLE or valuation_repo.get_pe_history_count(code) >= PE_MIN_RECORDS):
            ready += 1
    print(f"\n就绪: {ready}/{len(selected_codes)}")


if __name__ == "__main__":
    main()
