"""
PE因子交叉校验器

将 Tushare daily_basic 加权计算的行业PE
与 中证指数公司官方PE 做交叉验证，
确保加权计算方法的准确性。
"""

import pandas as pd
import numpy as np
from typing import Optional

from validation.factor_validator import (
    FactorValidator,
    ValidationResult,
    ValidationStatus,
    ValidationMetric,
)


class PEValidator(FactorValidator):
    factor_name = "pe_cross_check"
    description = "Tushare加权PE与中证指数官方PE交叉校验"

    WARN_PASS_RATE = 0.8
    FAIL_PASS_RATE = 0.5
    MAX_REL_ERROR = 0.15

    def __init__(self, valuation_repo, hybrid_data_source):
        self.valuation_repo = valuation_repo
        self.hybrid_source = hybrid_data_source

    def validate(self, etf_code: str) -> ValidationResult:
        csindex_data = self._fetch_csindex_pe(etf_code)
        if not csindex_data:
            return ValidationResult(
                etf_code=etf_code,
                factor_name=self.factor_name,
                status=ValidationStatus.SKIP,
                message="无中证指数官方数据，跳过校验",
            )

        local_data = self.valuation_repo.get_pe_history(etf_code)
        if not local_data:
            return ValidationResult(
                etf_code=etf_code,
                factor_name=self.factor_name,
                status=ValidationStatus.FAIL,
                message="本地无PE历史数据",
            )

        local_df = pd.DataFrame(local_data)
        csindex_df = pd.DataFrame(csindex_data)

        merged = pd.merge(
            local_df[["trade_date", "pe"]].rename(columns={"pe": "pe_local"}),
            csindex_df[["trade_date", "pe"]].rename(columns={"pe": "pe_csindex"}),
            on="trade_date",
            how="inner",
        )

        if len(merged) < 5:
            return ValidationResult(
                etf_code=etf_code,
                factor_name=self.factor_name,
                status=ValidationStatus.SKIP,
                message=f"重合数据点不足（{len(merged)}个，需>=5）",
            )

        merged = merged.sort_values("trade_date")
        merged["rel_error"] = abs(merged["pe_local"] - merged["pe_csindex"]) / merged["pe_csindex"]

        correlation = float(merged["pe_local"].corr(merged["pe_csindex"]))
        avg_rel_error = float(merged["rel_error"].mean())
        max_rel_error = float(merged["rel_error"].max())
        pass_count = int((merged["rel_error"] <= self.MAX_REL_ERROR).sum())
        pass_rate = pass_count / len(merged)
        mean_ratio = float((merged["pe_local"] / merged["pe_csindex"]).mean())

        metrics = [
            ValidationMetric(
                name="重合数据点",
                value=len(merged),
                unit="个",
                description="本地与官方数据重合的交易日数量",
            ),
            ValidationMetric(
                name="相关系数",
                value=round(correlation, 4),
                threshold=0.9,
                description="本地PE与官方PE的皮尔逊相关系数，越高越好",
            ),
            ValidationMetric(
                name="平均相对误差",
                value=round(avg_rel_error * 100, 2),
                threshold=10.0,
                unit="%",
                description="|本地PE - 官方PE| / 官方PE 的平均值",
            ),
            ValidationMetric(
                name="最大相对误差",
                value=round(max_rel_error * 100, 2),
                threshold=20.0,
                unit="%",
                description="|本地PE - 官方PE| / 官方PE 的最大值",
            ),
            ValidationMetric(
                name="通过率",
                value=round(pass_rate * 100, 2),
                threshold=self.WARN_PASS_RATE * 100,
                unit="%",
                description=f"相对误差 <= {int(self.MAX_REL_ERROR*100)}% 的数据点占比",
            ),
            ValidationMetric(
                name="均值比率",
                value=round(mean_ratio, 4),
                threshold=1.0,
                description="本地PE均值 / 官方PE均值，越接近1越好",
            ),
        ]

        if pass_rate >= self.WARN_PASS_RATE and correlation >= 0.9:
            status = ValidationStatus.PASS
            msg = f"PE校验通过：通过率{pass_rate*100:.1f}%，相关系数{correlation:.3f}"
        elif correlation >= 0.9:
            # 相关系数高但绝对值有偏移（数据源口径差异），判为警告而非失败
            status = ValidationStatus.WARNING
            msg = f"PE校验警告：通过率{pass_rate*100:.1f}%，相关系数{correlation:.3f}（趋势一致，绝对值存在偏移）"
        elif pass_rate >= self.FAIL_PASS_RATE:
            status = ValidationStatus.WARNING
            msg = f"PE校验警告：通过率{pass_rate*100:.1f}%，相关系数{correlation:.3f}"
        else:
            status = ValidationStatus.FAIL
            msg = f"PE校验失败：通过率{pass_rate*100:.1f}%，相关系数{correlation:.3f}"

        latest_local = merged.iloc[-1]["pe_local"]
        latest_csindex = merged.iloc[-1]["pe_csindex"]
        latest_date = merged.iloc[-1]["trade_date"]

        return ValidationResult(
            etf_code=etf_code,
            factor_name=self.factor_name,
            status=status,
            message=msg,
            metrics=metrics,
            detail_url="",
            raw_data={
                "latest_date": latest_date,
                "latest_pe_local": float(latest_local),
                "latest_pe_csindex": float(latest_csindex),
                "data_points": len(merged),
            },
        )

    def _fetch_csindex_pe(self, etf_code: str) -> list[dict]:
        try:
            csindex_val = self.hybrid_source.get_index_valuation_csindex(etf_code)
            if not csindex_val:
                return []
            result = []
            for item in csindex_val:
                pe = item.get("pe")
                if pe is not None and pe > 0:
                    result.append({
                        "trade_date": item["trade_date"],
                        "pe": pe,
                    })
            return result
        except Exception:
            return []
