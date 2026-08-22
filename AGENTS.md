# ETF 量化推荐系统协作指引

## 项目边界

- 正式回测入口是 `service.ApplicationService`，策略入口是 `strategy.multi_factor`。
- Streamlit 只负责交互和展示；数据质量、回测、报告和版本治理必须复用 service 层。
- 系统只生成回测/模拟盘信号和静态报告，不连接券商、不下真实订单、不部署或调用外部 AI，也不依赖系统定时调度。
- `$etf-autopilot` 是由 Codex 显式启动的 Skill。它可以读取静态报告、执行候选验证和版本发布，但不能绕过数据质量门禁、OOS、留出集或压力测试。

## 重要入口

- 面板：`presentation/streamlit_app.py`
- 正式回测：`service/application_service.py`
- 候选生成：`scripts/build_autopilot_candidates.py`
- 候选评分与发布：`scripts/run_autopilot.py`
- 自主诊断：`service/autopilot_diagnostics.py`（归因、因子边际贡献、行业/风格暴露、决策树）
- 版本配置：`config/strategy_versions/active-config.json`
- 回测报告：`reports/YYYY-MM-DD/<run-id>/`
- 自主优化报告：`reports/autopilot/YYYY-MM-DD/<run-id>/`
- 仓库级 Skill：`.agents/skills/etf-autopilot/SKILL.md`

## 推荐操作流程

1. 使用项目 `.venv` 安装依赖并启动 Streamlit。
2. 通过面板选择区间并运行正式回测；先查看数据质量，再查看绩效、净值、交易和唯一因子诊断面板。
3. 从报告目录读取 `report.html`、`report.md` 和 `report-data.json`。`report-data.json` 是供 Codex 或人工分析的事实数据，不是交易指令。
4. 需要自主优化时，先用 `build_autopilot_candidates.py` 生成候选，再使用 `$etf-autopilot` 或 `run_autopilot.py` 重新验证。
5. 只有候选通过完整验证才发布；通过后立即发布，不设置冷却期。发布必须写入版本证据并保留回滚目标。
6. 自主优化报告必须阅读 `operation-log.jsonl`、`autopilot-manifest.json` 和 `next-plan.json`，最终说明回测区间、诊断依据、候选淘汰原因和下一步计划。

## 安全约束

- 新因子代码只能通过 `service.factor_sandbox.FactorSandbox` 运行，并记录源码哈希。
- 自动优化只能修改因子组合、因子权重和参数；不得自动修改数据质量门禁、成交模型、风险约束、报告生成器或回测核心。
- 正式发布必须提供 `--start` 和 `--end`，重新执行最近24个月回测（前12个月选择期+后12个月最终盲测期）和四类压力测试。
- `--allow-unverified-input` 只用于离线测试，禁止用于生产发布。
- 禁止插值、前值填充、跨 ETF 借值、猜测复权因子或使用结束日之后的数据。
- 不要直接向 `main` 发布；自动 Git 发布使用 `codex/autopilot/...` 分支。

## 开发与验证

```bash
.venv/bin/python -m pytest -q
git diff --check
```

修改正式回测、数据门禁、因子计算或版本发布逻辑时，必须补充或更新相邻测试，并运行全量测试。不要把运行时生成的 `reports/` 内容当作源码修改提交，除非任务明确要求提交报告证据。

开始工作前先阅读相关 ADR，尤其是：

- `docs/adr/0001-canonical-strategy-runtime.md`
- `docs/adr/0002-backtest-evaluation-integrity.md`
- `docs/adr/0005-market-data-quality-gate.md`
- `docs/adr/0006-standardized-run-reports.md`
- `docs/adr/0008-codex-autonomous-optimization-objective.md`
