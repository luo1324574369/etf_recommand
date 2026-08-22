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
