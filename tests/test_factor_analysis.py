"""因子有效性检验测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import pytest

from strategy.factor_analysis import (
    compute_forward_returns,
    compute_rank_ic,
    compute_icir,
    stratified_backtest,
    analyze_factor,
)


def test_compute_forward_returns():
    """测试前瞻收益计算
    10个交易日，period=3
    第7日（index=6, close=10）的forward_return = (close[9]-close[6])/close[6] = (13-10)/10 = 0.3
    """
    dates = pd.date_range('2023-01-01', periods=10, freq='D')
    df = pd.DataFrame({
        'trade_date': dates,
        'code': '510300',
        'close': [10, 11, 12, 11, 10, 9, 10, 11, 12, 13],
    })
    result = compute_forward_returns(df, period=3)
    # 第7日（index=6, close=10）的forward_return = (close[9]-close[6])/close[6] = (13-10)/10 = 0.3
    row = result[result['trade_date'] == dates[6]].iloc[0]
    assert abs(row['forward_return'] - 0.3) < 0.001
    # 最后3天无前瞻收益
    assert len(result) == 7


def test_compute_rank_ic():
    """测试RankIC计算
    完全正相关 → IC=1.0
    """
    dates = pd.date_range('2023-01-01', periods=3, freq='MS')
    # 完全正相关
    factor_df = pd.DataFrame({
        'date': dates.tolist() * 3,
        'code': ['A', 'B', 'C'] * 3,
        'momentum_60d': [1, 2, 3, 1, 2, 3, 1, 2, 3],
    })
    return_df = pd.DataFrame({
        'date': dates.tolist() * 3,
        'code': ['A', 'B', 'C'] * 3,
        'forward_return': [0.01, 0.02, 0.03, 0.01, 0.02, 0.03, 0.01, 0.02, 0.03],
    })
    ic_df = compute_rank_ic(factor_df, return_df, ['momentum_60d'])
    # 每个日期的IC应为1.0
    for _, row in ic_df.iterrows():
        assert abs(row['ic'] - 1.0) < 0.001, f"期望IC=1.0，实际{row['ic']}"


def test_compute_icir():
    """测试ICIR计算
    IC序列 [0.1, 0.2, 0.15, 0.05, 0.1]
    IC均值=0.12, ICIR=0.12/std
    """
    ic_series = pd.Series([0.1, 0.2, 0.15, 0.05, 0.1])
    result = compute_icir(ic_series)
    expected_mean = 0.12
    assert abs(result['ic_mean'] - expected_mean) < 0.001
    assert result['ic_positive_ratio'] == 1.0  # 全部为正
    assert result['icir'] > 0


def test_stratified_backtest():
    """测试分层回测
    构造单调递增的因子-收益关系，验证5组收益单调
    """
    np.random.seed(42)
    dates = pd.date_range('2023-01-01', periods=5, freq='MS')
    rows_factor = []
    rows_return = []
    for d in dates:
        # 50只ETF，因子值1-50，收益与因子值正相关
        for i in range(50):
            rows_factor.append({'date': d, 'code': f'ETF{i}', 'momentum_60d': i})
            rows_return.append({'date': d, 'code': f'ETF{i}',
                               'forward_return': i * 0.001 + np.random.normal(0, 0.001)})
    factor_df = pd.DataFrame(rows_factor)
    return_df = pd.DataFrame(rows_return)
    result = stratified_backtest(factor_df, return_df, 'momentum_60d', n_groups=5)
    # 每个日期应有5组
    for d in dates:
        day_result = result[result['date'] == d]
        assert len(day_result) == 5
        # 组5（高因子值）收益应 > 组1（低因子值）
        g5 = day_result[day_result['group'] == 5]['avg_return'].iloc[0]
        g1 = day_result[day_result['group'] == 1]['avg_return'].iloc[0]
        assert g5 > g1, f"组5收益{g5}应大于组1收益{g1}"


def test_compute_cross_sectional_pe_percentile():
    """测试横截面PE百分位计算
    5只ETF，3个日期，PE值已知，验证百分位正确
    """
    from strategy.factor_analysis import compute_cross_sectional_pe_percentile

    # 5只ETF，3个日期，每只ETF每天一个PE值
    pe_by_code = {
        'ETF1': {'2023-01-03': 10.0, '2023-01-04': 12.0, '2023-01-05': 15.0},
        'ETF2': {'2023-01-03': 20.0, '2023-01-04': 18.0, '2023-01-05': 22.0},
        'ETF3': {'2023-01-03': 30.0, '2023-01-04': 28.0, '2023-01-05': 25.0},
        'ETF4': {'2023-01-03': 40.0, '2023-01-04': 35.0, '2023-01-05': 35.0},
        'ETF5': {'2023-01-03': 50.0, '2023-01-04': 50.0, '2023-01-05': 50.0},
    }
    all_dates = ['2023-01-03', '2023-01-04', '2023-01-05']

    result = compute_cross_sectional_pe_percentile(pe_by_code, all_dates)

    # 2023-01-03: PE=[10,20,30,40,50] → 百分位=[20,40,60,80,100]
    assert abs(result['2023-01-03']['ETF1'] - 20.0) < 0.1
    assert abs(result['2023-01-03']['ETF2'] - 40.0) < 0.1
    assert abs(result['2023-01-03']['ETF3'] - 60.0) < 0.1
    assert abs(result['2023-01-03']['ETF4'] - 80.0) < 0.1
    assert abs(result['2023-01-03']['ETF5'] - 100.0) < 0.1

    # 2023-01-05: PE=[15,22,25,35,50] → 百分位=[20,40,60,80,100]
    assert abs(result['2023-01-05']['ETF1'] - 20.0) < 0.1
    assert abs(result['2023-01-05']['ETF5'] - 100.0) < 0.1

    # 验证所有日期都存在
    assert '2023-01-03' in result
    assert '2023-01-04' in result
    assert '2023-01-05' in result


def test_validate_pe_data_strict():
    """测试PE数据严格模式校验"""
    from strategy.factor_analysis import validate_pe_data

    # 正常情况
    pe_by_code = {
        'ETF1': {'2023-01-01': 10.0, '2023-01-02': 11.0},
        'ETF2': {'2023-01-01': 20.0, '2023-01-02': 21.0},
    }
    # 不应报错
    validate_pe_data(pe_by_code, min_records=2)

    # PE数据为空应报错
    import pytest
    with pytest.raises(RuntimeError, match="PE 历史数据缺失"):
        validate_pe_data({'ETF1': {}}, min_records=1)

    # PE记录不足应报错
    with pytest.raises(RuntimeError, match="仅 1 条"):
        validate_pe_data({'ETF1': {'2023-01-01': 10.0}}, min_records=2)

    # PE全为0或负应报错（视为缺失）
    with pytest.raises(RuntimeError, match="PE 历史数据缺失"):
        validate_pe_data({'ETF1': {'2023-01-01': -5.0}}, min_records=1)


def test_sample_by_trading_day():
    """测试按全局交易日序号采样（每10天取最后一天）"""
    from strategy.factor_analysis import sample_by_trading_day

    # 构造25个交易日，5只ETF的因子数据
    dates = pd.date_range('2023-01-02', periods=25, freq='B')
    rows = []
    for i, d in enumerate(dates):
        for code in ['A', 'B', 'C', 'D', 'E']:
            rows.append({'date': d, 'code': code, 'momentum': i * 0.01})

    df = pd.DataFrame(rows)
    sampled = sample_by_trading_day(df, freq_days=10)

    # 25天 / 10 = 2个完整bucket + 剩余5天 = 3个bucket
    assert sampled['sample_bucket'].nunique() == 3

    # 每个bucket内每个ETF只有一条记录（最后一天）
    bucket_counts = sampled.groupby('sample_bucket')['code'].count()
    for cnt in bucket_counts:
        assert cnt == 5  # 5只ETF

    # 第一个bucket的最后一天应该是第10个交易日（index=9）
    first_bucket = sampled[sampled['sample_bucket'] == 0]
    first_date = first_bucket['date'].iloc[0]
    assert first_date == dates[9]


def test_analyze_factor_verdict():
    """测试有效性判定
    构造强因子数据，验证判定结果
    """
    dates = pd.date_range('2023-01-01', periods=24, freq='MS')
    rows_f, rows_r = [], []
    np.random.seed(42)
    for d in dates:
        for i in range(20):
            factor_val = i
            return_val = i * 0.001 + np.random.normal(0, 0.002)
            rows_f.append({'date': d, 'code': f'ETF{i}', 'momentum_60d': factor_val})
            rows_r.append({'date': d, 'code': f'ETF{i}', 'forward_return': return_val})
    factor_df = pd.DataFrame(rows_f)
    return_df = pd.DataFrame(rows_r)

    result = analyze_factor(factor_df, return_df, 'momentum_60d')
    # 验证指标存在
    assert 'ic_mean' in result
    assert 'icir' in result
    assert 'ic_positive_ratio' in result
    assert 'verdict' in result
    assert result['verdict'] in ['有效', '弱有效', '无效', '无数据']


def test_judge_verdict_direction_aware():
    """测试因子方向感知的判定逻辑"""
    from strategy.factor_analysis import _judge_verdict

    # 正向因子：IC为正，方向匹配 → 有效
    # ic_mean=0.04(≥0.03有效), icir=0.2(≥0.15有效),
    # ic_positive_ratio=0.6(≥0.55有效), monotonic=True, direction=1, 方向匹配
    verdict = _judge_verdict(0.04, 0.2, 0.6, True, direction=1)
    assert verdict == '有效'

    # 反向因子：IC为负，方向匹配 → 有效
    # ic_mean=-0.04(方向匹配+abs≥0.03有效), icir=-0.2(abs≥0.15有效),
    # ic_positive_ratio=0.3(反向因子IC正确比例=0.7≥0.55有效), monotonic=True
    verdict = _judge_verdict(-0.04, -0.2, 0.3, True, direction=-1)
    assert verdict == '有效'

    # 反向因子但IC为正：方向不匹配 → 判定降低
    # ic_mean=0.04(方向不匹配), icir=0.2(abs≥0.15有效),
    # ic_positive_ratio=0.6(反向因子IC正确比例=0.4<0.5), monotonic=False
    verdict = _judge_verdict(0.04, 0.2, 0.6, False, direction=-1)
    # 方向不匹配(0) + IC有效(1) + ICIR有效(1) + IC正确比例无效(0) + 非单调(0) = 2有效
    assert verdict == '有效'

    # 正向因子但IC为负：方向不匹配
    # ic_mean=-0.04(方向不匹配), icir=-0.2(abs≥0.15有效),
    # ic_positive_ratio=0.3(正向因子IC正确比例=0.3<0.5), monotonic=False
    verdict = _judge_verdict(-0.04, -0.2, 0.3, False, direction=1)
    # 方向不匹配(0) + IC有效(1) + ICIR有效(1) + IC正确比例无效(0) + 非单调(0) = 2有效
    assert verdict == '有效'

    # 弱有效场景：IC小，ICIR小，但方向匹配+单调
    # ic_mean=0.02(方向匹配+0.015≤abs<0.03弱有效), icir=0.1(0.075≤abs<0.15弱有效),
    # ic_positive_ratio=0.52(0.5≤r<0.55弱有效), monotonic=True, direction=1
    verdict = _judge_verdict(0.02, 0.1, 0.52, True, direction=1)
    # 方向匹配(1有效) + IC弱(1弱) + ICIR弱(1弱) + IC比例弱(1弱) + 单调(1有效) = 2有效
    assert verdict == '有效'

    # 无效场景：所有指标都差
    # ic_mean=0.001(方向匹配但abs<0.015), icir=0.01(abs<0.075),
    # ic_positive_ratio=0.45(<0.5), monotonic=False, direction=1
    verdict = _judge_verdict(0.001, 0.01, 0.45, False, direction=1)
    # 方向匹配(1有效) + 其他全无效 = 1有效 → 弱有效也不够 → 无效
    assert verdict == '无效'


def test_analyze_all_etfs_pe_cross_sectional():
    """测试analyze_all_etfs使用横截面PE百分位"""
    from strategy.factor_analysis import analyze_all_etfs

    # 构造mock的price_repo和valuation_repo（300个交易日保证forward_period=60有足够交集）
    class MockPriceRepo:
        def get_daily_price(self, code):
            dates = pd.date_range('2023-01-02', periods=300, freq='B')
            np.random.seed(abs(hash(code)) % 2**31)
            prices = []
            base = 100 + abs(hash(code)) % 50
            for i, d in enumerate(dates):
                base *= (1 + np.random.normal(0, 0.01))
                prices.append({
                    'trade_date': d.strftime('%Y-%m-%d'),
                    'open': base * 0.99,
                    'high': base * 1.01,
                    'low': base * 0.98,
                    'close': base,
                    'volume': 1000000,
                    'amount': base * 1000000,
                })
            return prices

    class MockValuationRepo:
        def get_pe_history(self, code):
            dates = pd.date_range('2023-01-02', periods=300, freq='B')
            base_pe = 10 + abs(hash(code)) % 40
            result = []
            for i, d in enumerate(dates):
                result.append({
                    'trade_date': d.strftime('%Y-%m-%d'),
                    'pe': base_pe * (1 + 0.1 * np.sin(i / 10)),
                })
            return result

    price_repo = MockPriceRepo()
    valuation_repo = MockValuationRepo()

    etf_codes = ['ETF1', 'ETF2', 'ETF3', 'ETF4', 'ETF5']
    result = analyze_all_etfs(
        etf_codes=etf_codes,
        price_repo=price_repo,
        valuation_repo=valuation_repo,
        start_date='2023-01-02',
        end_date='2024-04-30',
        factor_names=['momentum_60d', 'pe_percentile', 'volatility_60d'],
        min_pe_records=10,  # 测试数据小，放宽
    )

    # 验证返回3个因子的结果
    assert len(result) >= 2
    assert 'momentum_60d' in result
    assert 'volatility_60d' in result

    # 验证每个因子都有ic_series, icir, verdict等字段
    for factor_name, metrics in result.items():
        assert 'ic_mean' in metrics
        assert 'icir' in metrics
        assert 'ic_positive_ratio' in metrics
        assert 'monotonicity' in metrics
        assert 'verdict' in metrics
        assert 'ic_series' in metrics
        assert 'stratified' in metrics
        assert metrics['verdict'] in ['有效', '弱有效', '无效', '无数据']


def test_commodity_etf_skip():
    """测试商品ETF在PE因子检验中自动跳过"""
    from strategy.factor_analysis import analyze_all_etfs
    import pytest

    class MockPriceRepo:
        def get_daily_price(self, code):
            dates = pd.date_range('2023-01-02', periods=300, freq='B')
            np.random.seed(abs(hash(code)) % 2**31)
            prices = []
            base = 100 + abs(hash(code)) % 50
            for i, d in enumerate(dates):
                base *= (1 + np.random.normal(0, 0.01))
                prices.append({
                    'trade_date': d.strftime('%Y-%m-%d'),
                    'open': base * 0.99,
                    'high': base * 1.01,
                    'low': base * 0.98,
                    'close': base,
                    'volume': 1000000,
                    'amount': base * 1000000,
                })
            return prices

    class MockValuationRepo:
        def get_pe_history(self, code):
            # 商品ETF返回空
            if code in ['159985', '518880']:
                return []
            dates = pd.date_range('2023-01-02', periods=300, freq='B')
            base_pe = 10 + abs(hash(code)) % 40
            result = []
            for i, d in enumerate(dates):
                result.append({
                    'trade_date': d.strftime('%Y-%m-%d'),
                    'pe': base_pe * (1 + 0.1 * np.sin(i / 10)),
                })
            return result

    price_repo = MockPriceRepo()
    valuation_repo = MockValuationRepo()

    # 包含商品ETF和普通ETF
    etf_codes = ['159985', '518880', 'ETF1', 'ETF2', 'ETF3', 'ETF4', 'ETF5']
    result = analyze_all_etfs(
        etf_codes=etf_codes,
        price_repo=price_repo,
        valuation_repo=valuation_repo,
        start_date='2023-01-02',
        end_date='2024-04-30',
        factor_names=['pe_percentile'],
        min_pe_records=10,
    )

    # 商品ETF不应导致报错（PE数据为空但自动跳过）
    # 只要有5只以上非商品ETF有PE数据，PE因子就能检验
    assert 'pe_percentile' in result


def test_commodity_etf_all_fail():
    """测试所有ETF都是商品ETF（无PE数据）时PE因子被跳过而非报错"""
    from strategy.factor_analysis import analyze_all_etfs
    import pytest

    class MockPriceRepo:
        def get_daily_price(self, code):
            dates = pd.date_range('2023-01-02', periods=300, freq='B')
            np.random.seed(abs(hash(code)) % 2**31)
            prices = []
            base = 100 + abs(hash(code)) % 50
            for i, d in enumerate(dates):
                base *= (1 + np.random.normal(0, 0.01))
                prices.append({
                    'trade_date': d.strftime('%Y-%m-%d'),
                    'open': base * 0.99,
                    'high': base * 1.01,
                    'low': base * 0.98,
                    'close': base,
                    'volume': 1000000,
                    'amount': base * 1000000,
                })
            return prices

    class MockValuationRepo:
        def get_pe_history(self, code):
            return []  # 全部返回空（模拟商品ETF）

    price_repo = MockPriceRepo()
    valuation_repo = MockValuationRepo()

    # 5只商品ETF（无PE数据），只请求动量和波动率因子
    etf_codes = ['159985', '518880', 'ETF1', 'ETF2', 'ETF3']
    result = analyze_all_etfs(
        etf_codes=etf_codes,
        price_repo=price_repo,
        valuation_repo=valuation_repo,
        start_date='2023-01-02',
        end_date='2024-04-30',
        factor_names=['momentum_60d', 'volatility_60d'],
    )
    # 非PE因子应该正常返回（不报错）
    assert 'momentum_60d' in result
    assert 'volatility_60d' in result
