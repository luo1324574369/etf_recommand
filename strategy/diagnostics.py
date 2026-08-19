"""因子快照、观察和诊断报告的稳定数据契约。"""
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional


@dataclass(frozen=True)
class FactorSnapshot:
    date: Optional[str]
    raw_values: Dict[str, Dict[str, float]]
    normalized_values: Dict[str, Dict[str, Optional[float]]]
    missing_factors: Dict[str, list[str]] = field(default_factory=dict)
    etf_names: Dict[str, str] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Any]:
        """兼容旧的四元组解包接口。"""
        yield self.raw_values
        yield self.normalized_values
        factor_names = sorted({
            factor_name
            for values in self.raw_values.values()
            for factor_name in values
        })
        yield factor_names
        yield self.etf_names


@dataclass(frozen=True)
class FactorObservation:
    observation_date: Any
    code: str
    factor_value: Optional[float]
    close_price: Optional[float]

    def __iter__(self) -> Iterator[Any]:
        yield self.observation_date
        yield self.code
        yield self.factor_value
        yield self.close_price

    def __getitem__(self, index: int) -> Any:
        return tuple(self)[index]


@dataclass
class FactorDiagnosticReport:
    data: Dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data
