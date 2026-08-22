import pandas as pd


class _LocalOnlyService:
    def get_daily_price(self, code):
        return [
            {"trade_date": "2023-06-30", "close": 1.0},
            {"trade_date": "2023-07-03", "close": 1.1},
        ]

    def get_validated_source_records(self, code):
        return []


def test_candidate_builder_keeps_local_rows_without_validated_external_source():
    from scripts.build_autopilot_candidates import _build_data_dict

    data = _build_data_dict(
        _LocalOnlyService(),
        ["510300"],
        "2023-07-02",
        "2023-07-03",
    )

    assert list(data["510300"]["trade_date"]) == ["2023-06-30", "2023-07-03"]
    assert isinstance(data["510300"], pd.DataFrame)


def test_autopilot_uses_recent_24_months_with_12_month_selection_and_holdout():
    from scripts.build_autopilot_candidates import _canonical_evaluation_window

    window = _canonical_evaluation_window("2023-01-01", "2026-07-02")

    assert window == {
        "start": "2024-07-02",
        "end": "2026-07-02",
        "selection_start": "2024-07-02",
        "selection_end": "2025-07-01",
        "final_holdout_start": "2025-07-02",
        "final_holdout_end": "2026-07-02",
    }
