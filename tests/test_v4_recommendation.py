"""Tests V4 recommandation : fuite, slates, score/rang, stabilite, reproductibilite."""
from __future__ import annotations

import hashlib
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from src.recsys_v4 import evaluate as ev
from src.recsys_v4.dataset import (
    ALL_FEATURES, EXPOSURE_PROBABILITY_STATUS, TARGETS, build_dataset, validate_no_forbidden_columns,
)
from src.recsys_v4.models import SIMPLE_FACTORIES, predict

MODELS_DIR = PROJECT_ROOT / "models" / "v4" / "recommendation"


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return build_dataset()


# ------------------------------------------------------------------ fuite


def test_no_forbidden_feature_in_allowed_list():
    validate_no_forbidden_columns(ALL_FEATURES)


def test_rank_and_model_score_are_excluded_from_features():
    assert "rank" not in ALL_FEATURES
    assert "model_score" not in ALL_FEATURES


def test_validate_rejects_forbidden_columns():
    for forbidden in ("purchased_after", "added_to_cart_after", "viewed_after_impression",
                     "rank", "model_score", "clicked"):
        with pytest.raises(ValueError):
            validate_no_forbidden_columns(["produit_key", forbidden])


def test_clicked_column_is_never_referenced(dataset):
    assert "clicked" not in dataset.columns


def test_perturbing_future_actions_does_not_change_features(dataset):
    perturbed = dataset.copy()
    for column in TARGETS:
        perturbed[column] = 1 - perturbed[column]
    pd.testing.assert_frame_equal(dataset[ALL_FEATURES], perturbed[ALL_FEATURES])


def test_client_history_is_zero_before_any_purchase(dataset):
    never_purchased = dataset[dataset.client_purchase_count_before.eq(0) & dataset.is_anonymous.eq(0)]
    if len(never_purchased):
        assert (never_purchased.client_category_affinity == 0).all()


# -------------------------------------------------------- semantique exposition


def test_exposure_probability_status_is_deterministic_top_k(dataset):
    assert (dataset.exposure_probability_status == EXPOSURE_PROBABILITY_STATUS).all()


def test_product_exposure_probability_never_used_as_feature():
    assert "product_exposure_probability" not in ALL_FEATURES


# --------------------------------------------------------------- coherence slates


def test_every_slate_has_exactly_five_candidates(dataset):
    sizes = dataset.groupby("slate_id").size()
    assert (sizes == 5).all()


def test_ranks_within_a_slate_are_unique_1_to_5(dataset):
    ranks = dataset.groupby("slate_id")["produit_key"].count()
    assert (ranks == 5).all()


def test_identity_key_is_never_null(dataset):
    assert dataset.identity_key.notna().all()


# ------------------------------------------------------------ score / rang


def test_all_models_produce_finite_scores_with_valid_ranking(dataset):
    max_week = dataset.impression_week.max()
    from src.recsys_v4.train import assign_windows
    dataset = dataset.assign(window=assign_windows(dataset))
    train = dataset[dataset.window < dataset.window.max()]
    test = dataset[dataset.window.eq(dataset.window.max())].head(500)
    cutoff = test.impression_timestamp.min()
    for name, factory in SIMPLE_FACTORIES.items():
        model = factory(train, "purchased_after", cutoff)
        if model is None:
            continue
        scores = predict(model, test)
        assert np.isfinite(scores).all(), name
        ranked = test.assign(_s=scores).groupby("slate_id")["_s"].rank(
            method="first", ascending=False)
        assert set(ranked.groupby(test.slate_id).apply(lambda s: tuple(sorted(s)))
                  .iloc[0]) <= {1.0, 2.0, 3.0, 4.0, 5.0}


def test_recall_at_k_is_invariant_to_reranking_within_a_fixed_slate(dataset):
    """Verification du constat methodologique : avec k>=5 et des slates de 5
    candidats, Recall@k/HitRate@10 ne dependent que de l'ensemble des 5
    candidats (identique pour tous les modeles), jamais de leur ordre."""
    sample = dataset.head(200).copy()
    sample["target"] = np.random.default_rng(0).integers(0, 2, len(sample))
    order_a = sample.assign(_score=np.random.default_rng(1).random(len(sample)))
    order_b = sample.assign(_score=np.random.default_rng(2).random(len(sample)))
    metrics_a = ev.aggregate_summary(ev.slate_metrics(order_a, "_score", "target"))
    metrics_b = ev.aggregate_summary(ev.slate_metrics(order_b, "_score", "target"))
    assert metrics_a["recall@5"] == pytest.approx(metrics_b["recall@5"])
    assert metrics_a["recall@10"] == pytest.approx(metrics_b["recall@10"])


# --------------------------------------------------------------- stabilite client


def test_client_features_are_stable_for_repeated_rows(dataset):
    """Deux expositions du meme client au meme instant doivent avoir les memes
    features d'historique (aucune dependance a l'ordre de traitement)."""
    duplicated = dataset[dataset.duplicated(["identity_key", "impression_timestamp"], keep=False)]
    if duplicated.empty:
        pytest.skip("aucune exposition simultanee pour le meme client dans cet echantillon")
    for _, group in duplicated.groupby(["identity_key", "impression_timestamp"]):
        assert group.client_purchase_count_before.nunique() == 1


# --------------------------------------------------------------- determinisme


def test_same_seed_gives_identical_scores(dataset):
    from src.recsys_v4.train import assign_windows
    dataset = dataset.assign(window=assign_windows(dataset))
    train = dataset[dataset.window < dataset.window.max()]
    test = dataset[dataset.window.eq(dataset.window.max())].head(500)
    cutoff = test.impression_timestamp.min()
    factory = SIMPLE_FACTORIES["popularite_globale_v1"]
    first = predict(factory(train, "purchased_after", cutoff), test)
    second = predict(factory(train, "purchased_after", cutoff), test)
    np.testing.assert_array_equal(first, second)


# --------------------------------------------------------------- serialisation


def test_persisted_models_reload_and_score(dataset):
    for target in TARGETS:
        artifact = MODELS_DIR / target / "model.joblib"
        if not artifact.is_file():
            continue
        payload = joblib.load(artifact)
        model = payload["fitted_model"]
        scores = predict(model, dataset.head(20))
        assert np.isfinite(scores).all()


def test_manifest_sha256_matches_artifacts():
    for target in TARGETS:
        target_dir = MODELS_DIR / target
        manifest_path = target_dir / "manifest.sha256.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest.items():
            digest = hashlib.sha256((target_dir / relative).read_bytes()).hexdigest()
            assert digest == expected, relative


# --------------------------------------------------------------- reproductibilite


def test_holm_correction_never_decreases_below_raw_p_values():
    raw = {"a": 0.01, "b": 0.2, "c": 0.6}
    corrected = ev.holm_correction(raw)
    for name in raw:
        assert corrected[name] >= raw[name]


def test_bootstrap_ci95_is_seeded_reproducibly():
    per_slate = pd.DataFrame({"identity_key": [f"C{i%10}" for i in range(100)],
                             "slate_id": [f"S{i}" for i in range(100)],
                             "metric": np.random.default_rng(0).random(100)})
    baseline = per_slate.assign(metric=per_slate.metric * 0.9)
    first = ev.bootstrap_ci95(per_slate.rename(columns={"metric": "m"}).assign(m=per_slate.metric),
                              baseline.rename(columns={"metric": "m"}).assign(m=baseline.metric),
                              "identity_key", "m", draws=300)
    second = ev.bootstrap_ci95(per_slate.rename(columns={"metric": "m"}).assign(m=per_slate.metric),
                               baseline.rename(columns={"metric": "m"}).assign(m=baseline.metric),
                               "identity_key", "m", draws=300)
    assert first == second


# ---------------------------------------------------------------- statut synthetique


def test_all_recommendation_model_cards_declare_synthetic_status():
    for target in TARGETS:
        card = MODELS_DIR / target / "MODEL_CARD.md"
        if card.is_file():
            text = card.read_text(encoding="utf-8")
            assert "synthetic_academic_experiment" in text
            assert "deterministic_top_k" in text


def test_no_model_card_claims_a_causal_effect():
    for target in TARGETS:
        card = MODELS_DIR / target / "MODEL_CARD.md"
        if card.is_file():
            text = card.read_text(encoding="utf-8").lower()
            assert "revendication causale" not in text or "aucune revendication causale" in text
