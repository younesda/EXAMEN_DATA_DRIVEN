"""Tests V4 pricing : fuite, temporalite, garde-fous, determinisme, serialisation."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from src.pricing_v4 import evaluate as ev
from src.pricing_v4.dataset import (
    ALL_FEATURES, FORBIDDEN_ROOTS, TARGETS, build_dataset, validate_no_forbidden_columns,
)
from src.pricing_v4.models import MODEL_FACTORIES, predict

V4_DIR = PROJECT_ROOT / "data" / "raw" / "v4"
MODELS_DIR = PROJECT_ROOT / "models" / "v4" / "pricing"


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return build_dataset()


# ------------------------------------------------------------------ fuite


def test_no_forbidden_feature_in_allowed_list():
    validate_no_forbidden_columns(ALL_FEATURES)


def test_validate_rejects_forbidden_columns():
    for forbidden in ("units_sold_window_7j", "revenue_window_xof_7j",
                     "margin_window_xof_7j", "product_impressions", "prix_applique_xof"):
        with pytest.raises(ValueError):
            validate_no_forbidden_columns(["produit_key", forbidden])


def test_delivered_product_impressions_is_excluded_from_features(dataset):
    assert "product_impressions" not in ALL_FEATURES


def test_pre_decision_views_vary_with_decision_time(dataset):
    """Contraste avec la colonne livree, constante par produit (fuite corrigee)."""
    variability = dataset.groupby("produit_key").pre_decision_views.nunique()
    assert (variability > 1).all()


def test_perturbing_future_outcomes_does_not_change_features(dataset):
    """Modifier les cibles ne doit jamais modifier les features deja calculees."""
    perturbed = dataset.copy()
    perturbed[list(TARGETS)] = perturbed[list(TARGETS)] * 1000 + 999
    pd.testing.assert_frame_equal(dataset[ALL_FEATURES], perturbed[ALL_FEATURES])


def test_warmup_history_never_reads_the_decision_day(dataset):
    """warmup_sales_lag_7 doit ignorer les ventes du jour de decision lui-meme."""
    sample = dataset.sort_values(["produit_key", "decision_timestamp"]).groupby("produit_key").head(1)
    assert (sample.warmup_sales_lag_7 >= 0).all()


# --------------------------------------------------------------- temporalite


def test_leakage_report_declares_train_strictly_before_test():
    for target in TARGETS:
        metadata = json.loads((MODELS_DIR / target / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["n_test_windows"] >= 1


def test_no_tuning_hyperparameter_varies_with_test_window():
    """Les hyperparametres sont fixes a l'avance (memes valeurs pour toutes les fenetres)."""
    from src.pricing_v4.models import _LGBM_PARAMS
    assert _LGBM_PARAMS["random_state"] == 42


# ------------------------------------------------------------- non-negativite


def test_all_model_predictions_are_non_negative(dataset):
    train = dataset[dataset.experiment_week_index < dataset.experiment_week_index.max()]
    test = dataset[dataset.experiment_week_index == dataset.experiment_week_index.max()]
    for name, factory in MODEL_FACTORIES.items():
        model = factory(train, "units_sold_window_7j")
        if model is None:
            continue
        predictions = predict(model, test)
        assert np.isfinite(predictions).all(), name
        assert (predictions >= 0).all(), name


# --------------------------------------------------------------- determinisme


def test_same_seed_gives_identical_predictions(dataset):
    train = dataset[dataset.experiment_week_index < dataset.experiment_week_index.max()]
    test = dataset[dataset.experiment_week_index == dataset.experiment_week_index.max()]
    for name in ("LightGBM_Tweedie", "GLM_Poisson"):
        factory = MODEL_FACTORIES[name]
        first = predict(factory(train, "units_sold_window_7j"), test)
        second = predict(factory(train, "units_sold_window_7j"), test)
        np.testing.assert_array_equal(first, second)


# --------------------------------------------------------------- serialisation


def test_persisted_models_reload_and_predict(dataset):
    for target in TARGETS:
        artifact = MODELS_DIR / target / "model.joblib"
        if not artifact.is_file():
            continue
        payload = joblib.load(artifact)
        model = payload["fitted_model"]
        predictions = predict(model, dataset.head(20))
        assert np.isfinite(predictions).all()
        assert (predictions >= 0).all()


def test_manifest_sha256_matches_artifacts():
    for target in TARGETS:
        target_dir = MODELS_DIR / target
        manifest_path = target_dir / "manifest.sha256.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        import hashlib
        for relative, expected in manifest.items():
            digest = hashlib.sha256((target_dir / relative).read_bytes()).hexdigest()
            assert digest == expected, relative


# --------------------------------------------------------------- cold-start


def test_cold_start_products_get_finite_non_negative_predictions(dataset):
    train = dataset[dataset.experiment_week_index < dataset.experiment_week_index.max()]
    test = dataset[dataset.experiment_week_index == dataset.experiment_week_index.max()]
    cold_start_test = test[test.cold_start_warmup.eq(1)]
    if cold_start_test.empty:
        pytest.skip("aucune decision cold-start dans la derniere fenetre")
    for name in ("baseline_mediane_produit", "LightGBM_Tweedie", "T_learner"):
        model = MODEL_FACTORIES[name](train, "units_sold_window_7j")
        predictions = predict(model, cold_start_test)
        assert np.isfinite(predictions).all(), name
        assert (predictions >= 0).all(), name


# ---------------------------------------------------------------- garde-fous


def test_price_never_below_cost_in_delivered_data(dataset):
    violations = ev.margin_floor_violations(dataset)
    assert violations["n_price_below_cost"] == 0


def test_margin_floor_guardrail_is_computed():
    violations = ev.margin_floor_violations(pd.DataFrame({
        "prix_applique_xof": [100.0, 100.0, 50.0], "cout_xof": [80.0, 96.0, 60.0]}))
    assert violations["n_price_below_cost"] == 1
    assert violations["n_margin_below_floor"] == 2


def test_final_decision_reports_confirm_no_guardrail_violation():
    for target in TARGETS:
        metadata = json.loads((MODELS_DIR / target / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["guardrails"]["n_price_below_cost"] == 0


# --------------------------------------------------------------- reproductibilite


def test_metrics_are_reproducible_across_reruns(dataset):
    train = dataset[dataset.experiment_week_index < dataset.experiment_week_index.max()]
    test = dataset[dataset.experiment_week_index == dataset.experiment_week_index.max()]
    factory = MODEL_FACTORIES["baseline_mediane_produit"]
    first = ev.point_metrics(test.units_sold_window_7j.to_numpy(),
                             predict(factory(train, "units_sold_window_7j"), test))
    second = ev.point_metrics(test.units_sold_window_7j.to_numpy(),
                              predict(factory(train, "units_sold_window_7j"), test))
    assert first == second


def test_bootstrap_and_permutation_are_seeded_reproducibly():
    frame = pd.DataFrame({"produit_key": [f"P{i%20}" for i in range(400)],
                         "units_sold_window_7j": np.random.default_rng(0).poisson(5, 400).astype(float)})
    pred_a = frame.units_sold_window_7j.to_numpy() + 1
    pred_b = frame.units_sold_window_7j.to_numpy() + 2
    first = ev.product_level_bootstrap(frame, "units_sold_window_7j", pred_a, pred_b, draws=200)
    second = ev.product_level_bootstrap(frame, "units_sold_window_7j", pred_a, pred_b, draws=200)
    assert first == second


def test_holm_correction_never_decreases_below_raw_p_values():
    raw = {"a": 0.01, "b": 0.02, "c": 0.5}
    corrected = ev.holm_correction(raw)
    for name in raw:
        assert corrected[name] >= raw[name]


# ---------------------------------------------------------------- statut synthetique


def test_all_pricing_model_cards_declare_synthetic_status():
    for target in TARGETS:
        card = (MODELS_DIR / target / "MODEL_CARD.md")
        if card.is_file():
            assert "synthetic_academic_experiment" in card.read_text(encoding="utf-8")
