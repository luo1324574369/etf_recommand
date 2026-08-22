# ETF 模拟交易辅助治理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每日收盘后的 ETF 模拟交易辅助系统建立数据质量阻断、标准化报告归档和因子生命周期治理能力。

**Architecture:** 在现有 `data → service → strategy → presentation` 分层上增加可复现的数据快照与质量报告、统一运行报告生成器、版本化因子注册表。数据门禁先于策略运行，报告由 service 层生成，因子候选在隔离评估环境完成 OOS 和影子运行后才允许季度发布。

**Tech Stack:** Python 3.11+、pandas、SQLite、Backtrader、pytest、Streamlit、标准库 `dataclasses`/`json`/`hashlib`。

**Spec:** `/Users/jianming.luo/Documents/person-project/etf_recommand/docs/superpowers/specs/2026-08-20-etf-live-assistance-governance-design.md`

## Global Constraints

- Tushare Pro 为主数据源，AkShare 用于交叉校验或备用采集。
- 价格跨源差异超过 `1%` 或成交量差异超过 `10%` 时阻断。
- 信号使用复权价格，模拟成交使用原始价格；次日使用开盘价加固定滑点和手续费。
- 质量状态为 `blocked` 时不得生成信号或模拟订单，但必须生成阻断报告。
- 每次运行归档 HTML、Markdown、JSON 和运行清单。
- 因子每月监控、每季度发布；候选统一使用最近24个月回测（前12个月选择期+后12个月最终盲测期）和 1–3 个月影子运行。
- AI 生成因子只能在隔离沙箱中执行，不得直接修改正式策略。
- 所有新行为先写失败测试，再写最小实现；现有全量测试必须保持通过。

## 文件结构

- `data/contracts.py`：行情快照、质量报告和价格栏位的数据契约。
- `data/quality.py`：结构、价格、跨源和可交易性校验。
- `data/storage/market_data_repo.py`：快照和质量报告持久化。
- `service/reporting.py`：运行清单、JSON/Markdown/HTML 报告生成。
- `strategy/factor_registry.py`：版本化因子定义、来源和审批状态。
- `strategy/factor_lifecycle.py`：月度健康、候选评分、OOS 状态和发布状态机。
- `service/application_service.py`：编排质量门禁、策略运行和报告归档。
- `presentation/streamlit_app.py`：展示质量状态、下载报告和历史对比，不执行业务计算。

---

### Task 1: 建立行情快照与质量报告契约

**Files:**
- Create: `data/contracts.py`
- Test: `tests/test_data_contracts.py`

**Interfaces:**
- Produces `PriceBar`, `MarketDataSnapshot`, `ValidationIssue`, `DataQualityReport`。
- `MarketDataSnapshot.from_records(records_by_code, source, as_of_date, fetched_at)` 返回带稳定内容哈希的快照。
- `DataQualityReport.status` 只能是 `passed` 或 `blocked`。

- [ ] **Step 1: Write the failing test**

```python
def test_snapshot_hash_is_stable_and_report_serializes():
    from data.contracts import DataQualityReport, MarketDataSnapshot

    snapshot = MarketDataSnapshot.from_records(
        {"510300": [{"trade_date": "2025-01-02", "close": 4.0}]},
        source="tushare",
        as_of_date="2025-01-02",
        fetched_at="2025-01-02T16:00:00+08:00",
    )
    report = DataQualityReport.passed(snapshot.snapshot_id)
    assert snapshot.content_hash == MarketDataSnapshot.from_records(
        {"510300": [{"trade_date": "2025-01-02", "close": 4.0}]},
        source="tushare", as_of_date="2025-01-02",
        fetched_at="2025-01-02T16:00:00+08:00",
    ).content_hash
    assert report.to_dict()["status"] == "passed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_data_contracts.py::test_snapshot_hash_is_stable_and_report_serializes -q`
Expected: FAIL because `data.contracts` does not exist.

- [ ] **Step 3: Write minimal implementation**

Use frozen dataclasses, sort codes and record keys before hashing, and serialize dates through `default=str`. Keep raw and normalized values separate so later tasks can record both execution and signal prices.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_data_contracts.py -q`
Expected: PASS.

### Task 2: 实现数据质量校验器

**Files:**
- Create: `data/quality.py`
- Test: `tests/test_data_quality.py`

**Interfaces:**
- `validate_price_records(records_by_code, expected_dates, source_name)` 返回 `DataQualityReport`。
- `compare_price_sources(primary, secondary, price_tolerance=0.01, volume_tolerance=0.10)` 返回 `list[ValidationIssue]`。
- 检查重复日期、缺失日期、`low <= open/high/close <= high`、非负价格/成交量和异常空值。

- [ ] **Step 1: Write the failing tests**

```python
def test_price_difference_over_one_percent_blocks():
    from data.quality import compare_price_sources
    issues = compare_price_sources(
        {"510300": [{"trade_date": "2025-01-02", "close": 4.0, "volume": 100}]},
        {"510300": [{"trade_date": "2025-01-02", "close": 4.05, "volume": 100}]},
    )
    assert any(issue.rule == "cross_source_price" for issue in issues)

def test_invalid_ohlc_is_blocked():
    from data.quality import validate_price_records
    report = validate_price_records(
        {"510300": [{"trade_date": "2025-01-02", "open": 5, "high": 4,
                     "low": 3, "close": 4, "volume": 100}]},
        expected_dates=["2025-01-02"], source_name="tushare",
    )
    assert report.status == "blocked"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_data_quality.py -q`
Expected: FAIL because the validator functions do not exist.

- [ ] **Step 3: Implement the validator**

Use explicit rule names and measured values in every issue. Do not replace invalid values with zeros or neutral factor values. A missing expected date is blocking for a required daily run.

- [ ] **Step 4: Run the focused tests**

Run: `.venv/bin/pytest tests/test_data_quality.py -q`
Expected: PASS.

### Task 3: 接入来源溯源与数据门禁

**Files:**
- Modify: `data/sources/base.py`
- Modify: `data/sources/hybrid_source.py`
- Modify: `service/data_service.py`
- Modify: `service/application_service.py`
- Create: `data/storage/market_data_repo.py`
- Modify: `data/storage/db.py`
- Test: `tests/test_market_data_gate.py`

**Interfaces:**
- `DataService.build_market_snapshot(codes, start_date, end_date) -> tuple[MarketDataSnapshot, DataQualityReport]`。
- `ApplicationService.validate_backtest_data(selected_codes, start_date, end_date) -> DataQualityReport`。
- `MarketDataRepository.save_snapshot(snapshot, report) -> str`。
- `ApplicationService.run_backtest(...)` 在调用 `multi_factor.run_backtest` 前拒绝 `blocked` 报告。

- [ ] **Step 1: Write the failing integration tests**

```python
def test_application_service_blocks_invalid_market_data(tmp_path):
    service = make_service_with_price_rows(tmp_path, invalid_ohlc=True)
    report = service.validate_backtest_data(["510300"], "2025-01-02", "2025-01-02")
    assert report.status == "blocked"
    with pytest.raises(ValueError, match="数据质量阻断"):
        service.run_backtest(["510300"], "2025-01-02", "2025-01-02", {}, {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_market_data_gate.py -q`
Expected: FAIL because the application service has no quality gate.

- [ ] **Step 3: Implement the gate and persistence**

Add a `market_data_snapshot` table with snapshot ID, date range, source, content hash, status, report JSON and created timestamp. Keep the gate before strategy execution and make any cross-source fallback explicit in the report.

- [ ] **Step 4: Run focused integration tests**

Run: `.venv/bin/pytest tests/test_market_data_gate.py tests/test_data_quality.py -q`
Expected: PASS.

### Task 4: 建立运行报告生成器

**Files:**
- Create: `service/reporting.py`
- Modify: `service/dto.py`
- Modify: `.gitignore`
- Test: `tests/test_reporting.py`

**Interfaces:**
- `RunManifest.from_result(run_id, result, params, data_report, git_revision)`。
- `ReportArtifact.write(output_root, manifest, result) -> dict[str, Path]`。
- 输出 `run-manifest.json`、`report-data.json`、`report.md`、`report.html`。

- [ ] **Step 1: Write the failing tests**

```python
def test_report_archive_contains_machine_readable_and_human_files(tmp_path):
    from service.reporting import ReportArtifact
    paths = ReportArtifact.write(tmp_path, make_manifest(), make_result())
    assert {path.name for path in paths.values()} == {
        "run-manifest.json", "report-data.json", "report.md", "report.html",
    }
    assert json.loads(paths["data"].read_text())["status"] == "passed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_reporting.py -q`
Expected: FAIL because `service.reporting` does not exist.

- [ ] **Step 3: Implement deterministic report rendering**

Use a stable run ID, JSON with units and source IDs, Markdown with the eight required sections, and HTML generated from the same structured payload. Add `reports/` to `.gitignore`; never store generated reports in source control.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_reporting.py -q`
Expected: PASS.

### Task 5: 把报告接入回测服务和面板

**Files:**
- Modify: `service/application_service.py`
- Modify: `presentation/streamlit_app.py`
- Test: `tests/test_application_reports.py`
- Test: `tests/test_streamlit_cleanup.py`

**Interfaces:**
- `ApplicationService.run_backtest` returns `BacktestResult` with `run_id`, `data_quality`, `report_paths` and `report_status`。
- `ApplicationService.archive_backtest_report(result, params, data_report) -> dict[str, Path]`。

- [ ] **Step 1: Write the failing integration test**

Assert that a successful local backtest creates an archive and a blocked data run creates only a blocked report, never a trade list or simulated order.

- [ ] **Step 2: Run focused test to verify failure**

Run: `.venv/bin/pytest tests/test_application_reports.py -q`
Expected: FAIL because `run_backtest` does not archive reports.

- [ ] **Step 3: Implement service-first integration**

Call the quality gate, run the strategy, build the manifest, archive the artifacts, and expose only paths and structured status to Streamlit. Add download buttons and a short “结论/数据可信度/下一步” summary; do not recompute metrics in the UI.

- [ ] **Step 4: Run focused and startup tests**

Run: `.venv/bin/pytest tests/test_application_reports.py tests/test_streamlit_cleanup.py -q`
Expected: PASS.

### Task 6: 建立版本化因子注册表

**Files:**
- Create: `strategy/factor_registry.py`
- Modify: `strategy/scoring.py`
- Test: `tests/test_factor_registry.py`

**Interfaces:**
- `FactorDefinition(name, version, direction, dependencies, source, status)`。
- `FactorRegistry.register(definition) -> FactorDefinition`。
- `FactorRegistry.activate(name, version, approved_by) -> FactorDefinition`。
- `FactorRegistry.rollback(name, target_version) -> FactorDefinition`。

- [ ] **Step 1: Write the failing tests**

Test duplicate versions, activation without approval, source values `builtin/plugin/ai_generated`, and rollback preserving the previous active version.

- [ ] **Step 2: Run the tests to verify failure**

Run: `.venv/bin/pytest tests/test_factor_registry.py -q`
Expected: FAIL because the registry module does not exist.

- [ ] **Step 3: Implement registry state transitions**

Persist definitions in SQLite or a versioned JSON registry, reject direct activation of `ai_generated`, and expose the active factor list to `compute_all_factors` without changing existing factor math.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_factor_registry.py -q`
Expected: PASS.

### Task 7: 实现因子健康监控与候选评分

**Files:**
- Create: `strategy/factor_lifecycle.py`
- Modify: `strategy/factor_analysis.py`
- Modify: `strategy/diagnostics.py`
- Test: `tests/test_factor_lifecycle.py`

**Interfaces:**
- `FactorHealthMonitor.evaluate(factor_name, observations, window_months=(12, 24)) -> FactorHealthReport`。
- `FactorHealthReport.status` 为 `healthy/attention/warning/failure_candidate`。
- `FactorCandidateEvaluator.score(candidate_report, active_reports) -> CandidateScore`。
- `CandidateScore` 至少包含 ICIR、分层差、成本后收益、稳定性、相关性和边际贡献字段。

- [ ] **Step 1: Write failing tests**

Use deterministic monthly observations to verify single-metric deterioration is `attention`, repeated multi-metric deterioration is `failure_candidate`, and a highly correlated candidate is rejected for no incremental contribution.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_factor_lifecycle.py -q`
Expected: FAIL because the monitor and candidate evaluator do not exist.

- [ ] **Step 3: Implement the monthly monitor**

Reuse `compute_icir`, rolling IC and stratified returns from `strategy/factor_analysis.py`; do not create a second preprocessing path. Require the 12-month screen and 24-month confirmation to be explicit in the report.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_factor_lifecycle.py tests/test_factor_analysis.py -q`
Expected: PASS.

### Task 8: 实现候选审批、沙箱和影子运行状态机

**Files:**
- Modify: `strategy/factor_lifecycle.py`
- Create: `service/factor_governance_service.py`
- Create: `tests/test_factor_governance_service.py`

**Interfaces:**
- `FactorGovernanceService.submit_candidate(definition, evaluation) -> FactorCandidate`。
- `approve_candidate(candidate_id, approver) -> FactorCandidate`。
- `start_shadow_run(candidate_id, start_date, end_date) -> ShadowRun`。
- `complete_shadow_run(shadow_id, metrics) -> ShadowRun`。
- `publish_quarterly(candidate_id, publish_date) -> FactorDefinition`。

- [ ] **Step 1: Write failing state-machine tests**

Cover `submitted → screened → confirmed → approved → shadow → publishable → active`, reject publication before approval or before the 24-month evaluation window (12-month selection plus 12-month final holdout), and reject a non-quarterly publish date.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_factor_governance_service.py -q`
Expected: FAIL because the governance service does not exist.

- [ ] **Step 3: Implement safe transitions**

Run AI-generated candidate evaluation in a subprocess with a temporary working directory and read-only inputs; persist source, code hash, evaluator version, OOS windows, approver and shadow metrics. Do not import candidate code into the production process.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/pytest tests/test_factor_governance_service.py tests/test_factor_registry.py -q`
Expected: PASS.

### Task 9: 接入月度监控、季度发布和历史对比

**Files:**
- Modify: `service/application_service.py`
- Modify: `presentation/streamlit_app.py`
- Modify: `service/reporting.py`
- Test: `tests/test_governance_integration.py`

**Interfaces:**
- `ApplicationService.build_factor_health_report(as_of_date) -> list[FactorHealthReport]`。
- `ApplicationService.list_factor_candidates() -> list[FactorCandidate]`。
- `ApplicationService.compare_runs(current_run_id, previous_run_id, shadow_run_id) -> dict`。

- [ ] **Step 1: Write failing integration tests**

Verify the report includes current-vs-benchmark, current-vs-previous and current-vs-shadow comparisons, factor health states, and a publish/rollback link without changing the formal strategy automatically.

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_governance_integration.py -q`
Expected: FAIL because the service and report fields are not wired.

- [ ] **Step 3: Implement the integration**

Expose health, candidate, shadow and approval status through service DTOs. Streamlit renders status and download links only; all state transitions are explicit user actions.

- [ ] **Step 4: Run focused integration tests**

Run: `.venv/bin/pytest tests/test_governance_integration.py tests/test_streamlit_cleanup.py -q`
Expected: PASS.

### Task 10: 全量验证、文档和发布检查

**Files:**
- Modify: `README.md`
- Modify: `docs/strategy_doc.md`
- Modify: `docs/glossary.md`
- Test: existing full test suite and new governance tests

- [ ] **Step 1: Run targeted regression tests**

Run: `.venv/bin/pytest tests/test_data_quality.py tests/test_market_data_gate.py tests/test_reporting.py tests/test_factor_lifecycle.py tests/test_factor_governance_service.py tests/test_governance_integration.py -q`
Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/pytest -q`
Expected: all collected tests pass; warnings may only be the existing constant-input warnings.

- [ ] **Step 3: Run application smoke checks**

Run: `.venv/bin/streamlit run presentation/streamlit_app.py --server.headless true --server.address 127.0.0.1 --server.port 18501`
Then request `http://127.0.0.1:18501/` and verify HTTP `200`; stop the process after the check.

- [ ] **Step 4: Update user documentation**

Document the data-quality blocked state, report archive location, report field meanings, monthly monitoring cadence, quarterly release window, shadow run workflow and rollback procedure.

- [ ] **Step 5: Review and commit**

Run `git diff --check`, review the final diff, stage only implementation and documentation files, then create one commit per completed workstream with messages such as `feat: add market data quality gate`, `feat: archive simulation reports`, and `feat: add factor lifecycle governance`.
