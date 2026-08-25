"""Candidat P1 — recalibration des prédictions Pricing V1.

Le modèle V1 (`challenger_ml_lightgbm`) n'est **pas** modifié : on conserve ses
prédictions et on leur applique un facteur multiplicatif estimé **uniquement
sur les fenêtres strictement antérieures**.

Trois variantes, fixées a priori :

* ``P1a_global``            — un seul facteur, tous produits confondus ;
* ``P1b_categorie``         — un facteur par catégorie, repli sur le global
  quand le support est insuffisant ;
* ``P1c_categorie_regularisee`` — facteur par catégorie tiré vers le global
  par un shrinkage dépendant du support.

**Contrainte absolue** : la fenêtre évaluée ne contribue jamais à son propre
facteur. La fenêtre 1 n'a aucune fenêtre antérieure et reçoit donc le facteur
neutre 1,0 — cette absence d'information est comptée telle quelle, jamais
masquée. C'est précisément ce qui a fait échouer le candidat A du forecasting,
dont tout le gain venait du poids par défaut de la fenêtre 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# --- Hyperparamètres fixés AVANT toute évaluation ---
MIN_SUPPORT_CATEGORIE = 500   # lignes minimales, sur les fenêtres antérieures, pour un facteur propre
K_REGULARISATION = 1000.0     # poids du facteur global dans le shrinkage (en lignes équivalentes)
FACTEUR_NEUTRE = 1.0          # appliqué quand aucune fenêtre antérieure n'existe
FACTEUR_MIN, FACTEUR_MAX = 0.5, 2.0  # bornes de sécurité : au-delà, le facteur n'est plus une calibration


@dataclass(frozen=True)
class CalibrationFactors:
    """Facteurs applicables à UNE fenêtre, estimés sur les fenêtres antérieures."""

    global_: float
    par_categorie: dict[str, float]
    source: str
    fenetres_utilisees: tuple[int, ...]
    supports: dict[str, int]

    def apply(self, y_pred: np.ndarray, categories: pd.Series | None = None) -> np.ndarray:
        if categories is None:
            return y_pred * self.global_
        f = categories.map(self.par_categorie).fillna(self.global_).to_numpy(dtype="float64")
        return y_pred * f


def _ratio(y: np.ndarray, y_pred: np.ndarray) -> float:
    """Facteur = SUM(y) / SUM(yhat).

    C'est le facteur qui annule exactement le biais normalisé sur les données
    d'estimation. On le borne : un facteur hors [0,5 ; 2,0] signalerait un
    problème de modèle, pas un défaut de calibration.
    """
    s_pred = float(np.sum(y_pred))
    if not np.isfinite(s_pred) or s_pred <= 0:
        return FACTEUR_NEUTRE
    return float(np.clip(float(np.sum(y)) / s_pred, FACTEUR_MIN, FACTEUR_MAX))


def estimate_factors(
    historique: dict[int, pd.DataFrame], fenetre_courante: int, variante: str
) -> CalibrationFactors:
    """Estime les facteurs pour ``fenetre_courante`` à partir des fenêtres
    **strictement antérieures** uniquement.

    ``historique[w]`` doit contenir les colonnes ``y``, ``y_pred`` et
    ``categorie`` du test de la fenêtre *w*.
    """
    prior = {w: df for w, df in historique.items() if w < fenetre_courante}
    if not prior:
        return CalibrationFactors(
            global_=FACTEUR_NEUTRE, par_categorie={}, fenetres_utilisees=(),
            source="facteur_neutre_aucune_fenetre_anterieure", supports={},
        )

    hist = pd.concat(prior.values(), ignore_index=True)
    f_global = _ratio(hist["y"].to_numpy(float), hist["y_pred"].to_numpy(float))
    fenetres = tuple(sorted(prior))

    if variante == "P1a_global":
        return CalibrationFactors(f_global, {}, "fenetres_anterieures", fenetres, {})

    par_cat: dict[str, float] = {}
    supports: dict[str, int] = {}
    for cat, g in hist.groupby("categorie"):
        n = len(g)
        supports[str(cat)] = int(n)
        f_cat = _ratio(g["y"].to_numpy(float), g["y_pred"].to_numpy(float))

        if variante == "P1b_categorie":
            # Repli franc sur le global si le support est insuffisant.
            par_cat[str(cat)] = f_cat if n >= MIN_SUPPORT_CATEGORIE else f_global
        elif variante == "P1c_categorie_regularisee":
            # Shrinkage vers le global : plus le support est faible, plus le
            # facteur de catégorie est tiré vers le facteur global.
            w = n / (n + K_REGULARISATION)
            par_cat[str(cat)] = float(np.clip(w * f_cat + (1 - w) * f_global, FACTEUR_MIN, FACTEUR_MAX))
        else:
            raise ValueError(f"variante inconnue : {variante}")

    return CalibrationFactors(f_global, par_cat, "fenetres_anterieures", fenetres, supports)


VARIANTES = ("P1a_global", "P1b_categorie", "P1c_categorie_regularisee")
