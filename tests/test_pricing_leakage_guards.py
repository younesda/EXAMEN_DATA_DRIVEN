"""Garde-fous anti-fuite du pricing.

Ces tests ne documentent plus la fuite : ils empechent sa reapparition.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from src.experiments.advanced_pricing import build_daily_history
from src.experiments.pricing_corrected import OUT as CORRECTED_OUT
from src.pricing import feature_registry as registry

REPORTS = PROJECT_ROOT / "reports" / "advanced"


def _corrected() -> dict:
    return json.loads((REPORTS / "pricing_corrected.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------- registre


def test_registry_marks_every_contemporaneous_variable_as_forbidden():
    for name in ("n_lignes", "ca_xof", "marge_xof", "prix_unitaire_paye_xof",
                 "order_count", "distinct_clients", "avg_basket_quantity",
                 "quantite", "quantite_vendue", "niveau_stock", "y"):
        assert name in registry.REGISTRY, name + " absent du registre"
        assert registry.REGISTRY[name].allowed is False, name + " doit etre interdite"


def test_every_allowed_feature_documents_availability_and_justification():
    for name in registry.allowed_features():
        rule = registry.REGISTRY[name]
        assert rule.availability, name
        assert rule.family in {"statique", "planifie", "historique"}, name
        assert len(rule.justification) > 20, name
        # Aucune feature autorisee ne peut etre datee du jour cible.
        assert not rule.availability.startswith("D "), name


def test_registry_rejects_forbidden_and_unknown_columns():
    registry.validate_matrix(registry.allowed_features())
    for bad in (["sales_lag_1", "n_lignes"], ["ca_xof"], ["marge_xof"],
                ["prix_unitaire_paye_xof"], ["order_count"], ["distinct_clients"]):
        with pytest.raises(ValueError, match="contemporaines"):
            registry.validate_matrix(bad)
    with pytest.raises(ValueError, match="absentes du registre"):
        registry.validate_matrix(["feature_non_declaree"])


def test_registry_rejects_indirect_transformations_of_n_lignes():
    """Une fuite renommee reste une fuite."""
    for bad in ("log_n_lignes", "n_lignes_ratio", "n_lignes_par_client",
                "sqrt_n_lignes", "ca_xof_par_ligne", "marge_xof_norm",
                "prix_unitaire_paye_xof_lag0"):
        with pytest.raises(ValueError, match="contemporaines"):
            registry.validate_matrix(["sales_lag_1", bad])


def test_registry_rejects_duplicated_columns():
    with pytest.raises(ValueError, match="dupliquees"):
        registry.validate_matrix(["sales_lag_1", "sales_lag_1"])


# ------------------------------------------------- matrices reelles du pipeline


def test_n_lignes_is_absent_from_the_delivered_pricing_pipeline():
    """La colonne ne doit plus figurer dans les listes de features du pipeline."""
    from src.pipelines import final_pricing

    assert "n_lignes" not in final_pricing.NUM
    assert "n_lignes" not in final_pricing.CAT
    registry.validate_matrix(final_pricing.CAT + final_pricing.NUM)
    source = (PROJECT_ROOT / "src" / "pipelines" / "final_pricing.py").read_text(encoding="utf-8")
    assert "validate_matrix" in source
    metadata = json.loads((PROJECT_ROOT / "models/pricing/metadata.json").read_text(encoding="utf-8"))
    correction = metadata["leakage_correction"]
    assert correction["removed_features"] == ["n_lignes"]
    assert correction["previous_results_status"] == "invalidated_due_to_target_leakage"


def test_training_and_inference_matrices_use_only_allowed_features():
    payload = _corrected()
    used = [row["feature"] for row in payload["registre_features"]["registre"] if row["autorisee"]]
    registry.validate_matrix(used)
    assert payload["registre_features"]["n_autorisees"] == len(registry.allowed_features())
    predictions = pd.read_parquet(CORRECTED_OUT / "predictions.parquet")
    assert not {"n_lignes", "ca_xof", "marge_xof"} & set(predictions.columns)


def test_invalidated_history_is_preserved_not_deleted():
    archive = json.loads(
        (PROJECT_ROOT / "models/pricing/metadata.invalidated.json").read_text(encoding="utf-8"))
    assert archive["status"] == "invalidated_due_to_target_leakage"
    assert archive["affected_metrics"]["LightGBM_calibre"] == pytest.approx(0.41637, abs=1e-4)
    assert archive["preserved_payload"]["summary"], "la charge historique doit rester lisible"


# ------------------------------------------------------- test de perturbation


def _synthetic_daily(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-02-01", periods=120, freq="D")
    frames = []
    for product in ("PRD000001", "PRD000002"):
        frames.append(pd.DataFrame({
            "produit_key": product, "ds": dates,
            "y": rng.integers(0, 6, len(dates)).astype(float),
            "view": rng.integers(0, 40, len(dates)).astype(float),
            "add_to_cart": rng.integers(0, 8, len(dates)).astype(float),
            "niveau_stock": rng.integers(20, 300, len(dates)).astype(float),
            "quantite_reapprovisionnee": rng.integers(0, 3, len(dates)).astype(float),
        }))
    return pd.concat(frames, ignore_index=True)


def _synthetic_orders(daily: pd.DataFrame, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "produit_key": daily.produit_key, "ds": daily.ds,
        "order_count": rng.integers(0, 5, len(daily)).astype(float),
        "distinct_clients": rng.integers(0, 5, len(daily)).astype(float),
        "avg_basket_quantity": rng.uniform(1, 4, len(daily)),
    })


def test_perturbing_target_day_sales_leaves_every_feature_unchanged():
    """Si une feature du jour D bouge quand on modifie les ventes de D, elle fuit."""
    daily = _synthetic_daily()
    orders = _synthetic_orders(daily)
    baseline = build_daily_history(daily, orders).sort_values(["produit_key", "ds"]).reset_index(drop=True)

    target_day = pd.Timestamp("2025-05-01")
    perturbed_daily = daily.copy()
    perturbed_orders = orders.copy()
    mask_daily = perturbed_daily.ds.eq(target_day)
    mask_orders = perturbed_orders.ds.eq(target_day)
    perturbed_daily.loc[mask_daily, ["y", "view", "add_to_cart", "niveau_stock",
                                     "quantite_reapprovisionnee"]] += 137.0
    perturbed_orders.loc[mask_orders, ["order_count", "distinct_clients",
                                       "avg_basket_quantity"]] += 137.0
    perturbed = (build_daily_history(perturbed_daily, perturbed_orders)
                 .sort_values(["produit_key", "ds"]).reset_index(drop=True))

    columns = [c for c in baseline.columns if c not in ("produit_key", "ds")]
    on_target_day = baseline.ds.eq(target_day)
    pd.testing.assert_frame_equal(
        baseline.loc[on_target_day, columns].reset_index(drop=True),
        perturbed.loc[on_target_day, columns].reset_index(drop=True),
        check_exact=False, atol=1e-12,
        obj="features du jour cible apres perturbation des ventes de ce jour")

    # Controle de sensibilite : les jours POSTERIEURS doivent, eux, bouger,
    # sinon le test passerait meme si les features etaient constantes.
    after = baseline.ds.gt(target_day)
    assert not np.allclose(
        baseline.loc[after, columns].fillna(0).to_numpy(float),
        perturbed.loc[after, columns].fillna(0).to_numpy(float)), (
        "les jours posterieurs doivent refleter la perturbation")


def test_history_features_never_read_the_current_day():
    """lag_1 du jour D doit valoir exactement la valeur de D-1."""
    daily = _synthetic_daily()
    history = build_daily_history(daily, _synthetic_orders(daily))
    merged = history.merge(daily[["produit_key", "ds", "y"]], on=["produit_key", "ds"])
    merged = merged.sort_values(["produit_key", "ds"])
    expected = merged.groupby("produit_key").y.shift(1)
    observed = merged.sales_lag_1
    both = expected.notna() & observed.notna()
    assert both.sum() > 100
    assert np.allclose(observed[both], expected[both])


# --------------------------------------------------------- protocole temporel


def test_train_is_strictly_before_test_in_every_window():
    payload = _corrected()
    for row in payload["per_window"]:
        assert row["train_strictly_before_test"] is True
        assert pd.Timestamp(row["train_end"]) < pd.Timestamp(row["test_start"])
        assert pd.Timestamp(row["test_start"]) < pd.Timestamp(row["test_end"])


def test_bias_calibration_is_learned_on_strictly_prior_data_only():
    payload = _corrected()
    for row in payload["per_window"]:
        if row["model"].startswith("lgbm_l1_calibre"):
            source = row["calibration_source"]
            assert ("anterieur" in source or "repli" in source
                    or source.startswith("moyenne des fenetres")), source
            if source.startswith("moyenne des fenetres"):
                used = json.loads(source.split("moyenne des fenetres ")[1])
                assert max(used) < row["window"], "calibration issue d'une fenetre non anterieure"
            assert row["calibration_factor"] > 0


# ------------------------------------------------------------------ decisions


def test_wape_optimum_and_volume_optimum_stay_separate():
    decisions = _corrected()["decisions"]
    wape_model = decisions["meilleur_predicteur_wape"]
    volume_model = decisions["meilleur_volume_biais_acceptable"]
    assert wape_model["modele"] != volume_model["modele"]
    assert wape_model["utilisable_comme_simulateur"] is False
    assert abs(wape_model["forecast_bias"]) > .03
    assert abs(volume_model["forecast_bias"]) <= .03
    # Le simulateur ne peut venir que de la decision 2.
    assert decisions["simulateur_de_marge"]["modele_de_volume"] == volume_model["modele"]
    assert decisions["simulateur_de_marge"]["garde_fous"]["application_automatique"] is False


def test_no_pricing_model_is_promoted():
    payload = _corrected()
    assert payload["gate_promotion"]["promu"] is False
    assert payload["gate_promotion"]["gain_relatif_du_modele_de_volume"] < .05


def test_corrected_pricing_wape_is_above_the_honest_oracle_floor():
    """Aucun modele honnete ne doit descendre sous le plancher oracle ~0,487."""
    payload = _corrected()
    for row in payload["summary"]:
        assert row["wape"] > .48, row["model"]
