"""Candidat E — variables métier connues à l'avance, par ablations successives.

Contrairement aux candidats A, B et C (qui recombinaient des prédictions V1
figées), E entraîne réellement un modèle. Il réutilise **sans le modifier** le
moteur LightGBM récursif de la V1 (`src/pipelines/backtest_lightgbm.py`), dont
l'absence de fuite multi-horizon a déjà été prouvée par des tests de
perturbation en V1. Seule la **sélection des variables** change ici.

Échelle d'ablation (chaque niveau ajoute un groupe au précédent) :

* **E1** : historique (lags/rolling) + calendrier déterministe
* **E2** : E1 + promotions planifiées (sous l'hypothèse documentée en E0)
* **E3** : E2 + âge de version produit
* **E4** : E3 + état de stock au cutoff

Le niveau E1 inclut toujours les variables historiques (lags, moyennes
mobiles) : sans elles, un modèle d'apprentissage n'aurait aucune information
sur le niveau de la série et la comparaison n'aurait pas de sens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.features.calendar import CALENDAR_FEATURE_COLUMNS
from src.pipelines.backtest_lightgbm import (
    CATEGORICAL_COLS,
    HISTORICAL_COLS,
    build_future_known,
    build_training_matrix,
    recursive_predict,
    _fit_lgbm,
)

# --- Groupes de variables, alignés sur l'audit E0 ---
GROUPE_HISTORIQUE = list(HISTORICAL_COLS)
GROUPE_CALENDRIER = list(CALENDAR_FEATURE_COLUMNS) + ["horizon"]
GROUPE_PROMOTIONS = ["en_promotion", "remise_pct", "n_promotions", "portee_promo", "prix_catalogue", "prix_attendu"]
GROUPE_AGE_VERSION = ["age_produit_jours"]  # renommé "âge de version" dans les rapports (cf. E0)
GROUPE_STOCK_INITIAL = ["stock_disponible_lag1", "indicateur_rupture_lag1", "indicateur_stock_faible_lag1"]
GROUPE_BASE_PRODUIT = ["categorie", "marque"]


@dataclass(frozen=True)
class AblationLevel:
    code: str
    label: str
    groupes: tuple[str, ...]

    @property
    def feature_groups(self) -> list[list[str]]:
        mapping = {
            "historique": GROUPE_HISTORIQUE,
            "base_produit": GROUPE_BASE_PRODUIT,
            "calendrier": GROUPE_CALENDRIER,
            "promotions": GROUPE_PROMOTIONS,
            "age_version": GROUPE_AGE_VERSION,
            "stock_initial": GROUPE_STOCK_INITIAL,
        }
        return [mapping[g] for g in self.groupes]

    def columns(self, available: list[str]) -> list[str]:
        cols: list[str] = []
        for group in self.feature_groups:
            for c in group:
                if c in available and c not in cols:
                    cols.append(c)
        return cols


ABLATION_LEVELS = (
    AblationLevel("E1", "calendrier seul", ("historique", "base_produit", "calendrier")),
    AblationLevel("E2", "+ promotions planifiées", ("historique", "base_produit", "calendrier", "promotions")),
    AblationLevel("E3", "+ âge de version", ("historique", "base_produit", "calendrier", "promotions", "age_version")),
    AblationLevel("E4", "+ stock initial", ("historique", "base_produit", "calendrier", "promotions", "age_version", "stock_initial")),
)


def run_ablation_window(
    table: pd.DataFrame, spec, level: AblationLevel, objective: str = "tweedie",
) -> tuple[pd.DataFrame, dict]:
    """Entraîne et prédit une fenêtre pour un niveau d'ablation donné.

    Réutilise strictement le moteur récursif V1 : entraînement walk-forward sur
    le train seul, prédiction jour par jour ne réinjectant que les prédictions
    déjà produites (jamais les vraies valeurs de validation).
    """
    import time

    train_full = table[table["ds"] <= spec.train_end]
    train_mat = build_training_matrix(train_full)

    feat_cols = level.columns(list(train_mat.columns))
    cat_cols = [c for c in CATEGORICAL_COLS if c in feat_cols]
    cat_categories = {c: train_mat[c].astype("category").cat.categories for c in cat_cols}

    t0 = time.perf_counter()
    model = _fit_lgbm(train_mat.copy(), feat_cols, cat_cols, objective)
    duree_fit = time.perf_counter() - t0

    test_dates = pd.date_range(spec.test_start, spec.test_end, freq="D")
    products = sorted(
        table.loc[(table["ds"] >= spec.test_start) & (table["ds"] <= spec.test_end), "unique_id"].unique()
    )
    fk = build_future_known(table, test_dates, products)

    # Le stock initial est une caractéristique du cutoff : une valeur par
    # produit, constante sur l'horizon en tant qu'ÉTAT INITIAL — jamais
    # présentée comme le stock réel du jour J+k (cf. E0 §3).
    if "stock_initial" in level.groupes:
        stock_cutoff = (
            train_full.sort_values("ds").groupby("unique_id")[GROUPE_STOCK_INITIAL].last().reset_index()
        )
        fk = fk.merge(stock_cutoff, on="unique_id", how="left", suffixes=("", "_cutoff"))

    t0 = time.perf_counter()
    preds = recursive_predict(
        model, train_full, products, spec.train_end, len(test_dates), fk, feat_cols, cat_cols, cat_categories
    )
    duree_predict = time.perf_counter() - t0

    truth = table[(table["ds"] >= spec.test_start) & (table["ds"] <= spec.test_end)][["unique_id", "ds", "y"]]
    out = truth.merge(preds, on=["unique_id", "ds"], how="left")
    out["y_pred"] = out["y_pred"].fillna(0.0)
    out["window"] = spec.index
    out["niveau_ablation"] = level.code

    info = {
        "niveau": level.code,
        "label": level.label,
        "fenetre": spec.index,
        "n_features": len(feat_cols),
        "n_train": int(len(train_mat)),
        "n_produits": len(products),
        "duree_fit_s": round(duree_fit, 2),
        "duree_predict_s": round(duree_predict, 2),
        "n_nan": int(out["y_pred"].isna().sum()),
        "n_negatifs": int((out["y_pred"] < 0).sum()),
    }
    return out[["unique_id", "ds", "window", "y", "y_pred", "niveau_ablation"]], info
