"""Vérifie que la V2 travaille exactement sur le même protocole que la V1 :
mêmes fenêtres, mêmes populations, mêmes définitions de métriques.

Sans cette garantie, toute comparaison V1/V2 serait invalide (on comparerait
deux périmètres différents).
"""

from __future__ import annotations

import glob

import numpy as np
import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from src.pipelines.backtest_baselines import H, N_WINDOWS, SEASONALITY, build_windows
from src.pipelines.backtest_postprocess import OPERATIONAL_DIR

TABLE_PATH = PROJECT_ROOT / "data" / "processed" / "table_analytique.parquet"

pytestmark = pytest.mark.skipif(not TABLE_PATH.exists(), reason="Nécessite data/processed/table_analytique.parquet")

# Fenêtres V1 de référence (dates constatées lors de la V1, cf. rapport 23 §6
# et v2/reports/01_forecasting_protocole.md).
EXPECTED_WINDOWS = {
    1: ("2026-02-01", "2026-02-02", "2026-03-03"),
    2: ("2026-03-03", "2026-03-04", "2026-04-02"),
    3: ("2026-04-02", "2026-04-03", "2026-05-02"),
    4: ("2026-05-02", "2026-05-03", "2026-06-01"),
    5: ("2026-06-01", "2026-06-02", "2026-07-01"),
    6: ("2026-07-01", "2026-07-02", "2026-07-31"),
}


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    t = pd.read_parquet(TABLE_PATH)
    t["ds"] = pd.to_datetime(t["ds"])
    return t


def test_parametres_de_backtest_inchanges():
    assert H == 30, "L'horizon de backtest a changé — comparaison V1/V2 invalide"
    assert N_WINDOWS == 6, "Le nombre de fenêtres a changé — comparaison V1/V2 invalide"
    assert SEASONALITY == 7


def test_les_six_fenetres_sont_identiques_a_la_v1(table):
    windows = build_windows(table)
    assert len(windows) == 6
    for w in windows:
        train_end, test_start, test_end = EXPECTED_WINDOWS[w.index]
        assert str(w.train_end.date()) == train_end, f"Fenêtre {w.index} : train_end a changé"
        assert str(w.test_start.date()) == test_start, f"Fenêtre {w.index} : test_start a changé"
        assert str(w.test_end.date()) == test_end, f"Fenêtre {w.index} : test_end a changé"


def test_train_strictement_anterieur_au_test(table):
    for w in build_windows(table):
        assert w.train_end < w.test_start, f"Fenêtre {w.index} : chevauchement train/test"
        train = table[table["ds"] <= w.train_end]
        test = table[(table["ds"] >= w.test_start) & (table["ds"] <= w.test_end)]
        assert train["ds"].max() < test["ds"].min(), (
            f"Fenêtre {w.index} : une ligne de train est postérieure au début du test"
        )
        assert (w.test_end - w.test_start).days + 1 == H


def test_population_eligible_identique_a_la_v1():
    """1662 couples (produit, fenêtre) éligibles au total — le dénominateur
    exact des métriques V1 publiées."""
    frames = [pd.read_parquet(f) for f in sorted(glob.glob(str(OPERATIONAL_DIR / "*.parquet")))]
    op = pd.concat(frames, ignore_index=True)
    eligible = op[op["train_observations"] > 0][["unique_id", "window"]].drop_duplicates()
    assert len(eligible) == 1662, f"Population éligible divergente : {len(eligible)} au lieu de 1662"

    par_fenetre = eligible.groupby("window").size().to_dict()
    assert par_fenetre == {1: 247, 2: 265, 3: 275, 4: 283, 5: 292, 6: 300}, (
        f"Population par fenêtre divergente de la V1 : {par_fenetre}"
    )


def test_definition_wape_cumule_identique_a_la_v1():
    """Recalcule la WAPE cumulée 30 j de la V1 avec une implémentation
    indépendante et vérifie qu'elle reproduit la valeur du snapshot figé."""
    import json

    snapshot = json.loads(
        (PROJECT_ROOT / "reports" / "forecast_final" / "v1_metrics_snapshot.json").read_text(encoding="utf-8")
    )
    attendu = float(snapshot["metriques_cumulees_7_14_30j"]["AutoETS"]["30"]["WAPE"])

    frames = [pd.read_parquet(f) for f in sorted(glob.glob(str(OPERATIONAL_DIR / "*.parquet")))]
    op = pd.concat(frames, ignore_index=True)
    ae = op[(op["model_requested"] == "AutoETS") & (op["train_observations"] > 0)]
    agg = ae.groupby(["unique_id", "window"])[["y", "y_pred_final"]].sum()
    recalcule = float(np.abs(agg["y_pred_final"] - agg["y"]).sum() / agg["y"].sum())

    assert recalcule == pytest.approx(attendu, abs=1e-9), (
        f"La définition de la WAPE cumulée a divergé : snapshot={attendu}, recalcul={recalcule}"
    )
