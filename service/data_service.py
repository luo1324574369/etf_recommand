from datetime import date

from config.settings import ETF_UNIVERSE
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.sources.akshare_source import AkshareDataSource
from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor


class DataService:
    def __init__(self, db):
        self.db = db
        self.etf_repo = ETFRepository(db)
        self.price_repo = PriceRepository(db)

    def get_etf(self, code: str):
        return self.etf_repo.get_etf(code)

    def list_etfs(self, active_only: bool = True):
        return self.etf_repo.list_etfs(active_only=active_only)

    def get_daily_price(self, code: str):
        return self.price_repo.get_daily_price(code)

    def get_latest_price(self, code: str):
        return self.price_repo.get_latest_price(code)

    def get_recent_prices(self, code: str, days: int = 30):
        all_prices = self.price_repo.get_daily_price(code)
        return list(reversed(all_prices[-days:]))

    def calculate_factors(self, code: str, as_of_date: str = None):
        all_prices = self.price_repo.get_daily_price(code)
        if not all_prices:
            return {"momentum": None, "trend": None, "volume": None}

        latest_date = as_of_date or all_prices[-1]["trade_date"]

        momentum_factor = MomentumFactor(period=20)
        trend_factor = TrendFactor(period=20)
        volume_factor = VolumeFactor(short_period=5, long_period=20)

        return {
            "momentum": momentum_factor.calculate(code, all_prices, latest_date),
            "trend": trend_factor.calculate(code, all_prices, latest_date),
            "volume": volume_factor.calculate(code, all_prices, latest_date),
        }

    def get_etf_detail(self, code: str):
        etf = self.etf_repo.get_etf(code)
        if not etf:
            return None

        all_prices = self.price_repo.get_daily_price(code)
        recent_prices = list(reversed(all_prices[-30:]))
        latest_date = all_prices[-1]["trade_date"] if all_prices else None

        factors = {"momentum": None, "trend": None, "volume": None}
        if latest_date:
            factors = self.calculate_factors(code, latest_date)

        return {
            "etf": etf,
            "recent_prices": recent_prices,
            "factors": factors,
        }

    def update_etf_info(self) -> int:
        self.etf_repo.batch_insert(ETF_UNIVERSE)
        return len(ETF_UNIVERSE)

    def update_prices(self, codes: list = None, full: bool = False, on_progress=None) -> int:
        data_source = AkshareDataSource()

        if codes:
            etf_list = [self.etf_repo.get_etf(code) for code in codes]
            etf_list = [etf for etf in etf_list if etf]
        else:
            etf_list = self.etf_repo.list_etfs(active_only=True)

        end_date = date.today().isoformat()
        total_inserted = 0

        for idx, etf in enumerate(etf_list, 1):
            code = etf["code"]
            name = etf.get("name", code)

            if full:
                start_date = "2018-01-01"
            else:
                latest = self.price_repo.get_latest_date(code)
                start_date = latest if latest else "2018-01-01"

            if on_progress:
                on_progress(idx, len(etf_list), name, code, start_date, None)

            try:
                price_data = data_source.get_daily_price(code, start_date, end_date)
                inserted = self.price_repo.insert_daily_price(code, price_data)
                total_inserted += inserted
                if on_progress:
                    on_progress(idx, len(etf_list), name, code, start_date, inserted)
            except Exception as e:
                if on_progress:
                    on_progress(idx, len(etf_list), name, code, start_date, e)

        return total_inserted


def ensure_data_ready(
    selected_codes: list,
    start_date: str,
    end_date: str,
    data_source,
    etf_repo,
    price_repo,
    valuation_repo,
    on_progress=None,
) -> dict:
    """检查数据是否完整，不全则报错并返回命令行补充指令。

    注意：本函数只做检查，不自动获取数据。
    数据不全时返回 status='error'/'warn'，message 中包含详情。
    - price 不足: 必须修复，返回 error
    - PE 不足但 ETF 有指数映射（理论上可补）: 返回 warn，回测可继续（PE 因子对该ETF跳过）
    - PE 不足且 ETF 无任何指数映射（无法补）: 返回 error
    """
    from data.sources.hybrid_source import ETF_INDEX_MAP, ETF_CSINDEX_MAP

    # 无PE概念 / 数据源链路不可靠的ETF，跳过PE检查。
    # 商品ETF(豆粕/黄金)和海外QDII(恒生/纳指)无PE概念
    PE_NOT_APPLICABLE = {"159985", "518880", "159920", "513100"}

    result = {
        'status': 'ok',
        'message': '',
        'warnings': [],
        'details': {
            'etf_list': {'status': 'ok', 'count': 0},
            'price_data': {'status': 'ok', 'per_code': {}},
            'pe_history': {'status': 'ok', 'per_code': {}},
        }
    }

    # Step 1: Check ETF list
    try:
        etf_list = etf_repo.list_etfs()
        if not etf_list:
            for etf in ETF_UNIVERSE:
                etf_repo.insert_etf(etf['code'], etf.get('name', etf['code']))
            result['details']['etf_list']['count'] = len(ETF_UNIVERSE)
        else:
            result['details']['etf_list']['count'] = len(etf_list)
    except Exception as e:
        result['status'] = 'error'
        result['message'] = f'ETF list check failed: {str(e)}'
        result['details']['etf_list']['status'] = 'error'
        return result

    # Step 2: Check price data（只检查，不自动获取）
    missing_prices = []
    for idx, code in enumerate(selected_codes, 1):
        if on_progress:
            on_progress(f"检查行情数据: {code} ({idx}/{len(selected_codes)})")
        code_result = {'status': 'ok', 'count': 0, 'inserted': 0}
        try:
            existing = price_repo.get_daily_price(code, start_date, end_date)
            code_result['count'] = len(existing)
            if len(existing) < 20:
                code_result['status'] = 'insufficient'
                missing_prices.append(code)
        except Exception as e:
            code_result['status'] = 'error'
            missing_prices.append(code)
        result['details']['price_data']['per_code'][code] = code_result

    if missing_prices:
        result['status'] = 'error'
        result['details']['price_data']['status'] = 'insufficient'
        codes_str = ' '.join(missing_prices)
        result['message'] = (
            f"行情数据不足: {missing_prices} (各不足20条)\n"
            f"请在命令行运行以下命令补充数据:\n\n"
            f"  .venv/bin/python scripts/prepare_data.py {codes_str} --prices-only\n"
        )
        return result

    # Step 3: Check PE history（只检查，不自动获取）
    PE_MIN_RECORDS = 100
    missing_pe_error = []   # 无法补的，error 级阻塞
    missing_pe_warn = []    # 有指数映射可补的，warn 级不阻塞

    for code in selected_codes:
        if code in PE_NOT_APPLICABLE:
            result['details']['pe_history']['per_code'][code] = {
                'status': 'skip', 'count': 0, 'inserted': 0,
                'message': 'PE not applicable'
            }
            continue

        code_result = {'status': 'ok', 'count': 0, 'inserted': 0}
        has_mapping = (code in ETF_INDEX_MAP) or (code in ETF_CSINDEX_MAP)
        try:
            if not has_mapping:
                code_result['status'] = 'error'
                missing_pe_error.append(code)
            else:
                count = valuation_repo.get_pe_history_count(code)
                code_result['count'] = count
                if count < PE_MIN_RECORDS:
                    code_result['status'] = 'insufficient'
                    missing_pe_warn.append(code)
        except Exception as e:
            code_result['status'] = 'error'
            if has_mapping:
                missing_pe_warn.append(code)
            else:
                missing_pe_error.append(code)
        result['details']['pe_history']['per_code'][code] = code_result

    if missing_pe_error:
        result['status'] = 'error'
        result['details']['pe_history']['status'] = 'insufficient'
        codes_str = ' '.join(missing_pe_error)
        result['message'] = (
            f"PE历史数据不足且无可查映射: {missing_pe_error} (需≥{PE_MIN_RECORDS}条)\n"
            f"请在命令行运行以下命令补充数据:\n\n"
            f"  .venv/bin/python scripts/prepare_data.py {codes_str} --pe-only\n"
        )
        return result

    if missing_pe_warn:
        result['status'] = 'warn'
        result['details']['pe_history']['status'] = 'insufficient'
        codes_str = ' '.join(missing_pe_warn)
        warn_msg = (
            f"PE历史数据不足（可继续回测，PE因子对以下ETF跳过）: {missing_pe_warn} (需≥{PE_MIN_RECORDS}条)\n"
            f"建议后续在命令行补充数据:\n\n"
            f"  .venv/bin/python scripts/prepare_data.py {codes_str} --pe-only\n"
        )
        result['message'] = warn_msg
        result.setdefault('warnings', []).append(f"PE不足: {missing_pe_warn}，PE因子将对这些ETF跳过分打分")

    if result['status'] == 'ok':
        result['message'] = 'All data ready'
    return result
