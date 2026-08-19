# ADR-0001：统一正式策略运行时

## 状态

已接受

## 背景

仓库同时存在 `service/strategy_service.py` + `strategy/engine.py` 的旧策略链路，以及 Streamlit 直接调用 `strategy.multi_factor` 的新链路。两条链路使用不同的因子、过滤器、配置和结果模型，已经造成测试、文档和行为漂移。

## 决策

将 `strategy.multi_factor` 作为唯一正式策略运行时。旧 `StrategyEngine` 链路仅作为迁移兼容层，迁移完成后删除。

Streamlit 不直接调用策略实现，而是通过 service 层调用统一运行时，并接收稳定的结果 DTO。

## 影响

- 新功能只允许进入统一运行时。
- 旧链路需要迁移调用方、测试和脚本。
- 迁移期间必须保留行为对照测试，但不再新增旧链路能力。
- `multi_factor.py` 需要按职责拆分，避免继续成为单体模块。
