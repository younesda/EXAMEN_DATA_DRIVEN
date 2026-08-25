"""Garde-fous transversaux de la decision finale corrigee.

Ces tests documentaient initialement l'existence des deux fuites. Les fuites
etant corrigees, ils garantissent desormais :

* qu'aucune des deux ne peut revenir ;
* que les resultats invalides restent etiquetes et conserves ;
* que le forecasting, seul domaine valide, reste reproductible a l'identique.

Les garde-fous detailles par domaine sont dans `test_pricing_leakage_guards.py`
et `test_complement_leakage_guards.py`.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from src.pricing import feature_registry
from src.recsys import complement as complement_core

REPORTS = PROJECT_ROOT / "reports" / "advanced"


def _json(path) -> dict:
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))


# ----------------------------------------------------------- fuite pricing


def test_n_lignes_remains_a_component_of_the_pricing_target():
    """Rappel factuel : c'est ce qui rend la variable interdite."""
    data = pd.read_parquet(PROJECT_ROOT / "data/processed/final/product_day_discount_pricing.parquet")
    ratio = data.quantite / data.n_lignes
    assert ratio.min() >= 1.0, "quantite est bien la somme des lignes confirmees"
    assert data.n_lignes.corr(data.quantite) > .7
    assert feature_registry.REGISTRY["n_lignes"].allowed is False


def test_pricing_pipeline_no_longer_exposes_the_contemporaneous_proxy():
    from src.pipelines import final_pricing

    assert "n_lignes" not in final_pricing.NUM + final_pricing.CAT
    feature_registry.validate_matrix(final_pricing.CAT + final_pricing.NUM)


def test_invalidated_pricing_reference_is_below_the_honest_oracle_floor():
    """0,4164 reste sous le plancher oracle : la fuite est demontree, pas supposee."""
    payload = _json("reports/advanced/pricing_corrected.json")
    floor = min(payload["historique_invalide"].get("oracle_floor", [0.4866, 0.4838, 0.4931]))
    assert payload["historique_invalide"]["status"] == "invalidated_due_to_target_leakage"
    assert payload["historique_invalide"]["wape"] < floor
    for row in payload["summary"]:
        assert row["wape"] > floor, row["model"] + " sous le plancher oracle honnete"


# --------------------------------------------------- fuite recommandation


def test_complement_scoring_cannot_receive_the_masked_target_category():
    import inspect

    parameters = set(inspect.signature(complement_core.candidate_scores).parameters)
    assert "context_categories" in parameters
    assert not parameters & {"target", "target_category", "cible"}


def test_neutral_tiebreak_is_in_force_everywhere():
    products = ["PRD%06d" % index for index in range(300)]
    tiebreak = complement_core.tiebreak_order(products)
    assert sorted(tiebreak.values()) == list(range(300))
    assert abs(np.corrcoef(np.arange(300), [tiebreak[p] for p in products])[0, 1]) < .2


def test_invalidated_recommendation_metrics_stay_labelled():
    honest = _json("reports/advanced/complement_honest_baseline.json")
    invalid = honest["resultats_invalides"]
    assert invalid["leave_one_item_out_F2_F4"]["status"] == "invalidated_due_to_target_category_leakage"
    assert invalid["legacy_end_to_end"]["status"] == (
        "invalidated_due_to_in_sample_evaluation_without_temporal_split")
    archive = _json("models/advanced/recommendation_ranking/invalidated/INVALIDATION.json")
    assert archive["invalidated_headline_metrics"]["ndcg@10"] == pytest.approx(0.21264, abs=1e-5)
    assert archive["removed_from_live_directory"], "les artefacts fuites doivent avoir quitte le vivant"


def test_no_leaky_artifact_remains_in_the_live_ranking_directory():
    live = PROJECT_ROOT / "models/advanced/recommendation_ranking"
    stale = {"complement_lambdarank_metrics.json", "complement_decision_metadata.json",
             "complement_ranker_metadata.json", "complement_ranker_report.md",
             "complement_decision_bootstrap.csv", "complement_lambdarank_predictions_f4.parquet"}
    assert not stale & {p.name for p in live.glob("*")}
    assert (live / "invalidated" / "INVALIDATION.json").exists()


# ------------------------------------------------------------- decisions


def test_no_model_is_promoted_on_any_corrected_perimeter():
    complement = _json("reports/advanced/complement_honest_baseline.json")
    assert complement["modele_promu"] is None
    assert complement["statut_metier"]["basket_complement_model"] == "none_validated"

    pricing = _json("reports/advanced/pricing_corrected.json")
    assert pricing["gate_promotion"]["promu"] is False

    forecasting = _json("reports/advanced/cumulative_l1_pilot.json")
    assert forecasting["gate_pass"]["cumulative_l1"] is False
    assert forecasting["gate_pass"]["cumulative_tweedie"] is False


# ------------------------------------------- forecasting : seul domaine valide


def test_forecasting_reference_metrics_are_unchanged_and_reproducible():
    predictions = pd.read_parquet(
        PROJECT_ROOT / "models/advanced/forecasting/direct_lightgbm_predictions.parquet")
    assert len(predictions) == 54_000
    assert predictions.produit_key.nunique() == 300
    assert predictions.window.nunique() == 6
    assert predictions.horizon.nunique() == 30
    totals = predictions.groupby(["window", "produit_key"])[["y", "pred"]].sum()
    macro = (totals.groupby("window")
             .apply(lambda g: (g.pred - g.y).abs().sum() / g.y.sum(), include_groups=False).mean())
    micro = (totals.pred - totals.y).abs().sum() / totals.y.sum()
    bias = (predictions.pred - predictions.y).sum() / predictions.y.sum()
    assert macro == pytest.approx(0.25831, abs=1e-5)
    assert micro == pytest.approx(0.25743, abs=1e-5)
    assert bias == pytest.approx(-0.02593, abs=1e-5)
    assert predictions.pred.ge(0).all() and np.isfinite(predictions.pred).all()
