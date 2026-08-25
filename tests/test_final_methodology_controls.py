"""Contrôles actifs de la livraison reconstruite, sans artefact V1 obsolète."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.pipelines.final_forecasting import base_predictions
from src.pipelines.final_pricing import price_is_eligible
from src.pipelines.final_recommendation import (
    eligible_historical_web,
    paired_bootstrap,
    top,
)
from v2.data.builders.order_baskets import build_order_baskets
from v2.data.builders.session_sequences import build_session_sequences


def _metadata(domain: str) -> dict:
    return json.loads((PROJECT_ROOT / "models" / domain / "metadata.json").read_text(encoding="utf-8"))


def test_forecasting_calibration_strictement_anterieure_aux_six_fenetres():
    metadata = _metadata("forecasting")
    assert metadata["window_policy"]["count"] == 6
    assert metadata["intervals"]["strictly_prior_for_every_window"] is True
    for row in metadata["intervals"]["per_window"]:
        assert pd.Timestamp(row["calibration_max_ds"]) < pd.Timestamp(row["test_start"])


def test_forecasting_decisions_separees_et_aucun_vainqueur_global():
    decisions = _metadata("forecasting")["decisions"]
    assert decisions == {
        "daily": "CrostonOptimized",
        "planning_cumulative_30d": "LightGBM_Tweedie",
        "global_winner": None,
    }


def test_forecasting_cold_start_sans_nan_ni_negatif():
    train = pd.DataFrame(columns=["produit_key", "ds", "y"])
    test = pd.DataFrame({"produit_key": ["NEW"], "ds": [pd.Timestamp("2026-01-01")], "y": [0.0]})
    predictions = base_predictions(train, test)
    assert len(predictions) == 6
    assert np.isfinite(predictions.pred).all()
    assert predictions.pred.ge(0).all()


def test_pricing_calibration_lightgbm_strictement_anterieure():
    metadata = _metadata("pricing")
    assert metadata["lightgbm_calibration"]["strictly_prior_all_windows"] is True
    rows = [row for row in metadata["windows"] if row["model"] == "LightGBM_calibre"]
    assert len(rows) == 3
    assert all(pd.Timestamp(row["calibration_end"]) < pd.Timestamp(row["test_start"]) for row in rows)


def test_pricing_cible_et_grain_confirmes_explicitement():
    target = _metadata("pricing")["target"]
    assert target["column"] == "quantite"
    assert target["grain"] == "produit_key × ds × remise_pct"
    assert "confirm" in target["scope"]


def test_pricing_bornes_cout_et_marge():
    assert price_is_eligible(100, 80, 10, .05)
    assert not price_is_eligible(100, 95, 10, .05)
    assert not price_is_eligible(100, 100, 10, .05)


def test_paniers_grain_et_cible_confirmee_uniquement():
    sales = pd.DataFrame({
        "order_id": ["O1", "O1", "O1", "O2"],
        "produit_key": ["P1", "P1", "P2", "P3"],
        "client_key": ["C1", "C1", "C1", "C2"],
        "quantite": [1, 2, 1, 9],
        "montant_net_xof": [10, 20, 15, 99],
        "statut_commande": ["confirmee", "confirmee", "confirmee", "annulee"],
        "date_commande": pd.to_datetime(["2026-01-01"] * 4),
    })
    baskets = build_order_baskets(sales)
    assert not baskets.duplicated(["order_id", "produit_key"]).any()
    assert set(baskets.order_id) == {"O1"}
    assert baskets.loc[baskets.produit_key.eq("P1"), "quantite"].item() == 3


def test_sessions_deterministes_a_horodatage_egal():
    web = pd.DataFrame({
        "session_id": ["S", "S"], "event_id": ["E2", "E1"],
        "event_timestamp": pd.to_datetime(["2026-01-01T10:00:00Z"] * 2, utc=True),
        "event_type": ["view", "view"], "produit_key": ["P2", "P1"],
        "client_key": ["C", "C"], "anonymous_id": ["A", "A"], "est_bot": [False, False],
    })
    first = build_session_sequences(web)
    second = build_session_sequences(web.sample(frac=1, random_state=7))
    assert first.event_id.tolist() == second.event_id.tolist() == ["E1", "E2"]


def test_candidats_recommandation_exclus_et_deterministes():
    scores = np.array([1.0, 1.0, .5, np.nan])
    first = top(scores, 3, {0})
    second = top(scores, 3, {0})
    assert first.tolist() == second.tolist()
    assert 0 not in first
    assert 3 not in first


def test_achats_web_non_doubles_et_futur_exclu_du_signal_hybride():
    interactions = pd.DataFrame({
        "event_timestamp": pd.to_datetime([
            "2026-01-01T09:00:00Z", "2026-01-01T09:30:00Z", "2026-01-01T11:00:00Z"
        ], utc=True),
        "type_identite": ["client", "client", "client"],
        "event_type": ["view", "purchase", "add_to_cart"],
    })
    eligible = eligible_historical_web(interactions, pd.Timestamp("2026-01-01T10:00:00Z"))
    assert eligible.event_type.tolist() == ["view"]


def test_bootstrap_recommandation_deterministe():
    frame = pd.DataFrame({"recall_diff": [-.1, 0, .1], "ndcg_diff": [-.05, .01, .04]})
    assert paired_bootstrap(frame, draws=200) == paired_bootstrap(frame, draws=200)


def test_sessionnel_explicitement_non_utilisable():
    metadata = _metadata("recommendation")
    diagnostic = metadata["session_diagnostic"]
    assert diagnostic["usable_model"] is False
    assert diagnostic["temporal_violations"] == 0
    assert diagnostic["targets_outside_candidates"] == 0


def test_complementaires_panier_reste_un_systeme_separe():
    metadata = _metadata("recommendation")
    assert metadata["complementaires_panier"]["status"] == "systeme_metier_separe"


def test_audit_promotions_produit_et_categorie_sans_mismatch():
    audit = _metadata("pricing")["promotion_scope_audit"]
    assert {"product", "category"} <= set(audit)
    assert all(scope["target_mismatches"] == 0 for scope in audit.values())
    assert all(scope["date_mismatches"] == 0 for scope in audit.values())
