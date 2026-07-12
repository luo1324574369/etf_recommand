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
) -> dict:
    from data.sources.hybrid_source import ETF_INDEX_MAP

    result = {
        'status': 'ok',
        'message': '',
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
            source_etfs = data_source.get_etf_list()
            top_50 = source_etfs[:50]
            for etf in top_50:
                etf_repo.insert_etf(etf['code'], etf.get('name', etf['code']))
            result['details']['etf_list']['count'] = len(top_50)
        else:
            result['details']['etf_list']['count'] = len(etf_list)
    except Exception as e:
        result['status'] = 'error'
        result['message'] = f'ETF list check failed: {str(e)}'
        result['details']['etf_list']['status'] = 'error'
        return result

    # Step 2: Check price data
    for code in selected_codes:
        code_result = {'status': 'ok', 'count': 0, 'inserted': 0}
        try:
            existing = price_repo.get_daily_price(code, start_date, end_date)
            code_result['count'] = len(existing)
            if len(existing) < 20:
                price_data = data_source.get_daily_price(code, start_date, end_date)
                inserted = price_repo.insert_daily_price(code, price_data)
                code_result['inserted'] = inserted
                code_result['count'] = len(price_repo.get_daily_price(code, start_date, end_date))
                if code_result['count'] < 20:
                    code_result['status'] = 'error'
                    result['details']['price_data']['status'] = 'error'
                    result['status'] = 'error'
                    result['message'] = f'Price data insufficient for {code}: only {code_result["count"]} bars'
        except Exception as e:
            code_result['status'] = 'error'
            result['details']['price_data']['status'] = 'error'
            result['status'] = 'error'
            result['message'] = f'Price data check failed for {code}: {str(e)}'
        result['details']['price_data']['per_code'][code] = code_result
        if result['status'] == 'error':
            return result

    # Step 3: Check PE history
    # 阈值说明：宽基指数(3000+条)，行业ETF(139条月频)，csindex(20条)
    # 要求 >=100 条，确保行业ETF用加权PE而非csindex的20条
    PE_MIN_RECORDS = 100
    for code in selected_codes:
        code_result = {'status': 'ok', 'count': 0, 'inserted': 0}
        try:
            if code not in ETF_INDEX_MAP:
                code_result['status'] = 'error'
                result['details']['pe_history']['status'] = 'error'
                result['status'] = 'error'
                result['message'] = f'ETF {code} not found in ETF_INDEX_MAP'
                result['details']['pe_history']['per_code'][code] = code_result
                return result

            count = valuation_repo.get_pe_history_count(code)
            code_result['count'] = count
            if count < PE_MIN_RECORDS:
                pe_data = data_source.get_index_pe_history(code)
                valuation_repo.batch_insert_pe_history(code, pe_data)
                new_count = valuation_repo.get_pe_history_count(code)
                code_result['inserted'] = new_count - count
                code_result['count'] = new_count
                if new_count < PE_MIN_RECORDS:
                    code_result['status'] = 'error'
                    result['details']['pe_history']['status'] = 'error'
                    result['status'] = 'error'
                    result['message'] = f'PE history insufficient for {code}: only {new_count} records (need >= {PE_MIN_RECORDS})'
        except Exception as e:
            code_result['status'] = 'error'
            result['details']['pe_history']['status'] = 'error'
            result['status'] = 'error'
            result['message'] = f'PE history check failed for {code}: {str(e)}'
        result['details']['pe_history']['per_code'][code] = code_result
        if result['status'] == 'error':
            return result

    result['message'] = 'All data ready'
    return result
