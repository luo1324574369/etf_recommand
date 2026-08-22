from scripts.build_autopilot_candidates import build_search_profiles
from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES


def test_search_profiles_cover_complementary_adjustment_directions():
    profiles = build_search_profiles(MULTI_FACTOR_PARAM_RANGES, search_rounds=3)
    keys = [profile[0] for profile in profiles]

    assert keys == ["balanced", "risk_control", "return_recovery"]
    assert profiles[1][2]["rebalance_freq"] == [max(MULTI_FACTOR_PARAM_RANGES["rebalance_freq"])]
    assert profiles[2][2]["rebalance_freq"] == [min(MULTI_FACTOR_PARAM_RANGES["rebalance_freq"])]
    assert profiles[1][2]["top_n"] == [max(MULTI_FACTOR_PARAM_RANGES["top_n"])]
    assert profiles[2][2]["top_n"] == [
        min(MULTI_FACTOR_PARAM_RANGES["top_n"]),
        max(MULTI_FACTOR_PARAM_RANGES["top_n"]),
    ]
