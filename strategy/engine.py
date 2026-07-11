from strategy.factors.base import FactorBase
from strategy.filters.base import FilterBase
from strategy.factors.trend import TrendFactor


class StrategyEngine:

    def __init__(self, factors, filters, top_n=5, score_weights=None, exit_rules=None):
        self.factors = factors
        self.filters = filters
        self.top_n = top_n
        self.score_weights = score_weights or {}
        self.exit_rules = exit_rules or {}
        self.market_timing = None
        self._ma_break_counts = {}

    def _calculate_factors(self, code, price_data, end_date) -> dict:
        result = {}
        for factor in self.factors:
            value = factor.calculate(code, price_data, end_date)
            result[factor.name] = value
        return result

    def _normalize_scores(self, candidates: list[dict]) -> None:
        if not candidates:
            return

        for factor_name in self.score_weights:
            values = []
            for candidate in candidates:
                factor_values = candidate.get("factor_values", {})
                val = factor_values.get(factor_name)
                if isinstance(val, (int, float)):
                    values.append(val)

            if not values:
                continue

            min_val = min(values)
            max_val = max(values)

            for candidate in candidates:
                factor_values = candidate.get("factor_values", {})
                val = factor_values.get(factor_name)
                if isinstance(val, (int, float)):
                    if max_val == min_val:
                        factor_values[factor_name + "_norm"] = 0.5
                    else:
                        factor_values[factor_name + "_norm"] = (val - min_val) / (max_val - min_val)
                else:
                    factor_values[factor_name + "_norm"] = 0.0

    def run(self, etf_codes, end_date, price_repo) -> list[dict]:
        if self.market_timing:
            filtered = self.market_timing.filter(etf_codes, price_repo, end_date)
            if not filtered:
                return []
            etf_codes = filtered

        all_factor_values = {}
        for code in etf_codes:
            price_data = price_repo.get_daily_price(code, end_date=end_date)
            factor_values = self._calculate_factors(code, price_data, end_date)
            all_factor_values[code] = factor_values

        for f in self.filters:
            if hasattr(f, "set_universe"):
                f.set_universe(all_factor_values)

        candidates = []
        for code, factor_values in all_factor_values.items():
            passed_all = True
            for f in self.filters:
                passed, _ = f.apply(code, factor_values)
                if not passed:
                    passed_all = False
                    break
            if passed_all:
                candidates.append({
                    "code": code,
                    "factor_values": factor_values,
                })

        self._normalize_scores(candidates)

        total_weight = sum(self.score_weights.values())
        for candidate in candidates:
            score = 0.0
            factor_values = candidate["factor_values"]
            for factor_name, weight in self.score_weights.items():
                norm_key = factor_name + "_norm"
                norm_val = factor_values.get(norm_key, 0.0)
                score += norm_val * weight
            if total_weight > 0:
                candidate["score"] = score / total_weight
            else:
                candidate["score"] = 0.0

        candidates.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = candidates[:self.top_n]

        for i, candidate in enumerate(top_candidates):
            candidate["rank"] = i + 1

        return top_candidates

    def check_exit(self, holdings, current_date, price_repo) -> list[dict]:
        sell_signals = []
        ma_period = 20
        max_loss_pct = 0.08
        take_profit_pct = None
        ma_break_days = 1

        if self.exit_rules:
            if self.exit_rules.get("below_ma20", True):
                ma_period = self.exit_rules.get("ma_period", 20)
            max_loss_pct = self.exit_rules.get("max_loss_pct", 0.08)
            take_profit_pct = self.exit_rules.get("take_profit_pct")
            ma_break_days = self.exit_rules.get("ma_break_days", 1)
        else:
            ma_period = 20
            max_loss_pct = 0.08

        trend_factor = TrendFactor(period=ma_period)

        market_down = False
        if self.market_timing:
            filtered = self.market_timing.filter(list(holdings.keys()), price_repo, current_date)
            if not filtered:
                market_down = True

        for code, holding_info in holdings.items():
            price_data = price_repo.get_daily_price(code, end_date=current_date)
            if not price_data:
                continue

            current_price = price_data[-1]["close"]
            cost_basis = holding_info.get("cost_basis", 0)

            reasons = []

            if market_down:
                reasons.append("market_timing_exit")

            below_ma = False
            if self.exit_rules is None or self.exit_rules.get("below_ma20", True):
                trend_value = trend_factor.calculate(code, price_data, current_date)
                if trend_value is not None and trend_value.get("above_ma") is False:
                    below_ma = True

            if below_ma:
                self._ma_break_counts[code] = self._ma_break_counts.get(code, 0) + 1
                if self._ma_break_counts[code] >= ma_break_days:
                    reasons.append(f"below_ma{ma_period}_{ma_break_days}d")
            else:
                self._ma_break_counts[code] = 0

            if cost_basis > 0:
                loss_pct = (cost_basis - current_price) / cost_basis
                if loss_pct >= max_loss_pct:
                    reasons.append(f"stop_loss_{int(max_loss_pct*100)}pct")

            if take_profit_pct and cost_basis > 0:
                profit_pct = (current_price - cost_basis) / cost_basis
                if profit_pct >= take_profit_pct:
                    reasons.append(f"take_profit_{int(take_profit_pct*100)}pct")

            if reasons:
                sell_signals.append({
                    "code": code,
                    "action": "sell",
                    "reasons": reasons,
                    "current_price": current_price,
                })

        return sell_signals
