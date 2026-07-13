"""
因子校验器基类和数据结构

每次补充因子后自动运行校验逻辑，
将计算结果与权威数据源（如中证指数官方数据）对比，确保因子准确性。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ValidationStatus(str, Enum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class ValidationMetric:
    name: str
    value: float
    threshold: float = 0.0
    unit: str = ""
    description: str = ""


@dataclass
class ValidationResult:
    etf_code: str
    factor_name: str
    status: ValidationStatus
    message: str = ""
    metrics: List[ValidationMetric] = field(default_factory=list)
    detail_url: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "etf_code": self.etf_code,
            "factor_name": self.factor_name,
            "status": self.status.value,
            "message": self.message,
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "threshold": m.threshold,
                    "unit": m.unit,
                    "description": m.description,
                }
                for m in self.metrics
            ],
            "detail_url": self.detail_url,
        }


class FactorValidator:
    """因子校验器基类

    子类需实现 validate() 方法，返回 ValidationResult。
    """

    factor_name: str = "base"
    description: str = ""

    def validate(self, etf_code: str) -> ValidationResult:
        raise NotImplementedError

    def validate_all(self, etf_codes: List[str]) -> List[ValidationResult]:
        results = []
        for code in etf_codes:
            try:
                result = self.validate(code)
            except Exception as e:
                result = ValidationResult(
                    etf_code=code,
                    factor_name=self.factor_name,
                    status=ValidationStatus.FAIL,
                    message=f"校验异常: {str(e)}",
                )
            results.append(result)
        return results

    def summary(self, results: List[ValidationResult]) -> Dict[str, Any]:
        total = len(results)
        passed = sum(1 for r in results if r.status == ValidationStatus.PASS)
        warned = sum(1 for r in results if r.status == ValidationStatus.WARNING)
        failed = sum(1 for r in results if r.status == ValidationStatus.FAIL)
        skipped = sum(1 for r in results if r.status == ValidationStatus.SKIP)
        return {
            "factor_name": self.factor_name,
            "total": total,
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": passed / total if total > 0 else 0,
        }
