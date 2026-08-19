"""应用服务对外返回的数据传输对象。"""
from dataclasses import dataclass
from typing import Any, Dict, Iterator


@dataclass
class BacktestResult:
    """稳定的回测结果访问接口，隐藏策略实现对象。"""
    data: Dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def keys(self) -> Iterator[str]:
        return iter(self.data)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.data)
