from src.experiments.advanced_forecasting_ablations import FEATURE_GROUPS, kept_feature_indices
from src.experiments.advanced_forecasting_candidates import FEATURES


def test_ablation_groups_remove_only_declared_available_features():
    for removed in FEATURE_GROUPS.values():
        kept = kept_feature_indices(removed)
        assert len(kept) == len(FEATURES) - len(set(removed))
        assert not set(removed).intersection(FEATURES[index] for index in kept)


def test_ablation_groups_cover_requested_sources():
    assert "stock_at_cutoff" in FEATURE_GROUPS["no_stock"]
    assert "planned_discount" in FEATURE_GROUPS["no_promotion"]
    assert any(name.startswith("views_") for name in FEATURE_GROUPS["no_web"])
    assert any(name.startswith("cart_") for name in FEATURE_GROUPS["no_web"])
