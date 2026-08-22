---
name: etf-autopilot
description: "运行 ETF 因子与参数自主优化闭环：读取报告、生成候选、执行 OOS、发布或回滚。"
disable-model-invocation: true
---

# ETF 自主优化 Skill

本 Skill 由 Codex 执行，不调用外部 AI，不部署模型，不连接券商，不执行真实交易。

## 执行规则

1. 阅读 `AGENTS.md`、`docs/adr/0008-codex-autonomous-optimization-objective.md` 和 `docs/plans/2026-08-22-codex-autopilot-implementation-plan.md`。
2. 读取 `config/strategy_versions/active-config.json`、最近一次正式报告和最近一次自主优化报告。
3. 先运行数据质量门禁；阻断时只允许重新抓取、已批准源切换、单位转换、字段映射和缓存清理，然后重新校验。禁止插值、猜测或跨 ETF 借值。
4. 使用完整 ETF 宇宙，不使用面板当前手动选择列表。
5. 先验证当前正式版本作为 baseline，再运行候选生成器：

```bash
.venv/bin/python scripts/build_autopilot_candidates.py \
  --start <start-date> --end <end-date> \
  --output reports/autopilot/<run-id>/candidates.json \
  --max-combinations 20
```

   候选生成器会先执行数据门禁和现有 Walk-Forward；门禁失败不得继续评分。
6. 因子健康恶化时生成替换候选；新因子只能使用质量门禁通过的历史字段，在 `service.factor_sandbox.FactorSandbox` 中运行，并记录源码哈希。
7. 所有候选必须执行滚动 Walk-Forward、12 个月 OOS、24 个月 OOS、最终留出集和市场阶段压力测试。
8. 将候选与 baseline 整理为 JSON，格式为：

```json
{
  "baseline_metrics": {},
  "candidates": [{"config": {}, "metrics": {}}]
}
```

9. 调用：

```bash
.venv/bin/python scripts/run_autopilot.py \
  --candidates <candidate-json> \
  --start <start-date> --end <end-date> \
  --version-root config/strategy_versions \
  --report-root reports/autopilot \
  --branch codex/autopilot/<date>-<run-id> \
  --git-release
```

10. 入口会重新校验数据并重跑每个候选的 OOS、最终留出集和压力测试；生产发布不得使用 `--allow-unverified-input`。
11. 只有通过全部硬门槛的候选才能发布；候选通过后立即发布，不设置冷却期；无候选通过时保持当前版本。
12. 发布前检查配置哈希去重、风险约束未被修改和回滚锁；已回滚版本没有新证据不得重新发布。
13. 发布后创建版本分支、提交配置/证据/报告并推送远端；不得直接推送 `main`。
14. 最终输出报告路径、配置哈希、版本 ID、Git commit、OOS 指标、淘汰原因和回滚目标。

正式版本已有运行指标时，先将指标保存为 JSON，通过 `--rollback-metrics` 传给入口；若同时提供最近窗口数组的 `--prior-windows`，入口会检查连续三个恶化窗口。硬风险会立即回滚，回滚失败时停止发布，不得用候选覆盖当前版本。

## 停止条件

- 数据门禁连续失败；
- 未来函数、非法因子代码或沙箱失败；
- 超过 20 轮、100 次候选回测、30 分钟或 200 次数据调用；
- 连续 3 轮没有风险调整后收益改进。

任何停止都必须生成静态决策报告，不得静默结束。
