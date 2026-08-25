"""Preuves anti-fuite et de déterminisme pour le candidat A (combinaison
pondérée AutoETS / WindowAverage28).

Le risque de fuite propre à ce candidat n'est PAS dans les features (il n'en
construit aucune) mais dans le **choix du poids** : si le poids appliqué à la
fenêtre k était choisi en regardant la fenêtre k elle-même, la WAPE
rapportée serait optimiste et invalide. Ces tests le vérifient directement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from v2.forecasting.candidate_a_blend import (
    DEFAULT_WEIGHT,
    WEIGHT_GRID,
    BlendSpec,
    SelectionMode,
    blended_prediction,
    build_blend_frame,
    choose_weight_from_previous_windows,
    load_v1_operational_predictions,
    run_candidate_a,
)


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    try:
        predictions = load_v1_operational_predictions()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    return build_blend_frame(predictions)


# =============================================================================
# Anti-fuite : le poids ne doit dépendre que des fenêtres antérieures
# =============================================================================
def test_le_poids_nutilise_que_des_fenetres_strictement_anterieures(frame):
    for window in sorted(frame["window"].unique()):
        _, detail = choose_weight_from_previous_windows(frame, window)
        used = detail["fenetres_utilisees"]
        assert all(w < window for w in used), (
            f"Fuite : la fenêtre {window} utilise les fenêtres {used} pour choisir son poids."
        )


def test_la_premiere_fenetre_utilise_le_poids_par_defaut(frame):
    first = min(frame["window"].unique())
    weight, detail = choose_weight_from_previous_windows(frame, first)
    assert weight == DEFAULT_WEIGHT
    assert detail["fenetres_utilisees"] == []
    assert detail["source"] == "defaut_aucune_fenetre_anterieure"


def test_perturber_la_fenetre_courante_ne_change_pas_son_poids(frame):
    """LE test décisif : on remplace toutes les vraies valeurs `y` de la
    fenêtre évaluée par du bruit absurde. Si le poids de cette fenêtre
    changeait, c'est que la sélection regarde le test — fuite caractérisée."""
    rng = np.random.default_rng(1234)
    for window in sorted(frame["window"].unique()):
        weight_before, _ = choose_weight_from_previous_windows(frame, window)

        perturbed = frame.copy()
        mask = perturbed["window"] == window
        perturbed.loc[mask, "y"] = rng.uniform(9000, 9999, size=int(mask.sum()))
        perturbed.loc[mask, "pred_autoets"] = rng.uniform(9000, 9999, size=int(mask.sum()))
        perturbed.loc[mask, "pred_wa28"] = rng.uniform(9000, 9999, size=int(mask.sum()))

        weight_after, _ = choose_weight_from_previous_windows(perturbed, window)
        assert weight_before == weight_after, (
            f"Fuite : perturber la fenêtre {window} change son poids "
            f"({weight_before} -> {weight_after})."
        )


def test_perturber_une_fenetre_future_ne_change_aucun_poids_anterieur(frame):
    """Symétrique : une fenêtre postérieure ne doit influencer aucune fenêtre
    antérieure (sinon l'information circulerait à rebours dans le temps)."""
    rng = np.random.default_rng(99)
    windows = sorted(frame["window"].unique())
    last = windows[-1]

    perturbed = frame.copy()
    mask = perturbed["window"] == last
    perturbed.loc[mask, "y"] = rng.uniform(9000, 9999, size=int(mask.sum()))

    for window in windows[:-1]:
        w_before, _ = choose_weight_from_previous_windows(frame, window)
        w_after, _ = choose_weight_from_previous_windows(perturbed, window)
        assert w_before == w_after, (
            f"Fuite rétroactive : perturber la fenêtre {last} change le poids de la fenêtre {window}."
        )


# =============================================================================
# Cohérence : les bornes du mélange reproduisent exactement les modèles V1
# =============================================================================
def test_poids_1_reproduit_exactement_autoets_v1(frame):
    np.testing.assert_array_equal(
        blended_prediction(frame, 1.0), np.clip(frame["pred_autoets"].to_numpy("float64"), 0, None)
    )


def test_poids_0_reproduit_exactement_windowaverage28_v1(frame):
    np.testing.assert_array_equal(
        blended_prediction(frame, 0.0), np.clip(frame["pred_wa28"].to_numpy("float64"), 0, None)
    )


def test_le_melange_reste_entre_les_deux_modeles(frame):
    lo = np.minimum(frame["pred_autoets"], frame["pred_wa28"]).to_numpy("float64")
    hi = np.maximum(frame["pred_autoets"], frame["pred_wa28"]).to_numpy("float64")
    for w in WEIGHT_GRID:
        blended = blended_prediction(frame, w)
        assert np.all(blended >= lo - 1e-9) and np.all(blended <= hi + 1e-9), (
            f"Le mélange (w={w}) sort de l'enveloppe des deux modèles — combinaison non convexe."
        )


# =============================================================================
# Qualité des sorties
# =============================================================================
def test_aucune_valeur_non_finie_ni_negative(frame):
    for w in WEIGHT_GRID:
        blended = blended_prediction(frame, w)
        assert np.isfinite(blended).all(), f"NaN/Inf produit avec w={w}"
        assert (blended >= 0).all(), f"Valeur négative produite avec w={w}"


def test_le_perimetre_est_identique_a_la_v1(frame):
    """1662 couples (produit, fenêtre) — exactement le périmètre principal V1
    sur lequel WAPE 30 j = 0,2772 a été publiée."""
    n_pairs = frame[["unique_id", "window"]].drop_duplicates().shape[0]
    assert n_pairs == 1662, f"Périmètre divergent de la V1 : {n_pairs} couples au lieu de 1662"
    assert sorted(frame["window"].unique()) == [1, 2, 3, 4, 5, 6]


def test_poids_hors_bornes_rejete(frame):
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            blended_prediction(frame, bad)


# =============================================================================
# Déterminisme
# =============================================================================
def test_deux_executions_donnent_un_resultat_identique(frame):
    spec = BlendSpec(mode=SelectionMode.EXPANDING)
    first = run_candidate_a(spec, frame=frame)
    second = run_candidate_a(spec, frame=frame)
    pd.testing.assert_frame_equal(first, second)


def test_le_mode_fixe_applique_le_meme_poids_partout(frame):
    spec = BlendSpec(mode=SelectionMode.FIXED, fixed_weight=0.5)
    out = run_candidate_a(spec, frame=frame)
    assert out["poids_autoets"].nunique() == 1
    assert float(out["poids_autoets"].iloc[0]) == 0.5
