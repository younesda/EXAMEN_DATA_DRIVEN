import json
import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.experiments.advanced_pricing import (
    FEATURES, build_daily_history, price_is_supported_and_eligible, score,
)
from src.experiments.advanced_pricing_sensitivity import GROUPS, kept


def _daily() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=40)
    return pd.DataFrame({"produit_key": "P", "ds": dates, "y": np.arange(40, dtype=float),
                         "view": np.arange(40), "add_to_cart": np.arange(40),
                         "niveau_stock": 100-np.arange(40), "quantite_reapprovisionnee": 0})


def test_pricing_features_exclude_contemporary_target_proxies():
    forbidden = {"n_lignes", "prix_unitaire_paye_xof", "ca_xof", "marge_xof", "purchase"}
    assert not forbidden.intersection(FEATURES)


def test_daily_history_is_strictly_prior_under_future_perturbation():
    original = build_daily_history(_daily())
    changed = _daily(); changed.loc[changed.ds > "2026-01-20", ["y", "view", "add_to_cart", "niveau_stock"]] = 9999
    perturbed = build_daily_history(changed)
    columns = [column for column in original if column not in {"produit_key", "ds"}]
    pd.testing.assert_frame_equal(original.loc[original.ds <= "2026-01-20", columns].reset_index(drop=True),
                                  perturbed.loc[perturbed.ds <= "2026-01-20", columns].reset_index(drop=True))


def test_score_is_pooled_quantity_wape_and_deterministic():
    expected = 2 / 6
    assert score(np.array([1, 5]), np.array([2, 4]))["wape"] == expected
    assert score(np.array([1, 5]), np.array([2, 4])) == score(np.array([1, 5]), np.array([2, 4]))


def test_pricing_bounds_and_observed_support():
    assert price_is_supported_and_eligible(100, 80, 10, {0.0, 10.0}, .05)
    assert not price_is_supported_and_eligible(100, 80, 15, {0.0, 10.0}, .05)
    assert not price_is_supported_and_eligible(100, 95, 10, {0.0, 10.0}, .05)


def test_pricing_ablation_groups_are_explicit_and_valid():
    assert set(GROUPS) == {"no_web", "no_stock", "no_promotion", "no_orders"}
    for removed in GROUPS.values():
        assert len(kept(removed)) == len(FEATURES) - len(set(removed))


def test_advanced_pricing_calibration_and_population_are_strict():
    metadata = json.loads((PROJECT_ROOT / "models/advanced/pricing/metadata.json").read_text(encoding="utf-8"))
    model_rows = [row for row in metadata["window_metrics"] if "calibration_end" in row]
    assert model_rows
    assert all(pd.Timestamp(row["calibration_end"]) < pd.Timestamp(row["test_start"]) for row in model_rows)
    assert metadata["methodology"]["primary_population_filtered_by_common_support"] is False
    assert all(row["primary_population_filtered"] is False for row in metadata["propensity_common_support"])


def test_advanced_pricing_simulator_is_bounded_and_non_automatic():
    audit = json.loads((PROJECT_ROOT / "models/advanced/pricing/metadata.json").read_text(encoding="utf-8"))["simulator"]
    assert audit["nan_rows"] == audit["negative_quantity"] == 0
    assert audit["below_cost"] == audit["margin_floor_violations"] == 0
    assert audit["automatic_application_allowed"] is False
    assert audit["causal_effect_estimated"] is False
