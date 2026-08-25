"""Candidat A — combinaison pondérée AutoETS / WindowAverage28.

Idée : la V1 a montré que les deux modèles ont des forces complémentaires
(AutoETS meilleur en WAPE globale, WindowAverage28 nettement plus stable
entre fenêtres et moins biaisé — cf. `reports/23_rapport_final_forecasting.md`
§6). Une combinaison convexe simple peut capter les deux.

    y_pred = w * AutoETS + (1 - w) * WindowAverage28

**Aucun réentraînement** : ce candidat recombine les prédictions
opérationnelles V1 déjà produites et figées, exactement sur le même périmètre
(mêmes 6 fenêtres, mêmes produits éligibles, mêmes replis). C'est ce qui rend
la comparaison V1/V2 rigoureusement à périmètre constant, et le coût de
calcul négligeable.

## Anti-fuite : comment le poids est choisi

Le poids appliqué à la fenêtre *k* est déterminé **uniquement** sur les
fenêtres strictement antérieures (1..k-1) :

* fenêtre 1 : aucune fenêtre antérieure → poids neutre par défaut
  (``DEFAULT_WEIGHT``, fixé a priori, jamais ajusté sur les données de test) ;
* fenêtre k>1 : parmi une grille de poids **fixée à l'avance**
  (``WEIGHT_GRID``), celui qui minimise la WAPE cumulée 30 j sur les fenêtres
  1..k-1.

Aucune optimisation n'est faite sur la fenêtre évaluée. Le mode
``SelectionMode.FIXED`` (poids constant sur toutes les fenêtres) est aussi
disponible pour mesurer séparément l'apport de l'adaptation du poids.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.pipelines.backtest_postprocess import OPERATIONAL_DIR

MODEL_A = "AutoETS"
MODEL_B = "WindowAverage28"

# Grille de poids fixée AVANT toute évaluation (aucun réglage fin a posteriori).
WEIGHT_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
DEFAULT_WEIGHT = 0.5  # fenêtre 1 : aucune information antérieure disponible


class SelectionMode(str, Enum):
    FIXED = "poids_fixe"                     # même poids sur toutes les fenêtres
    EXPANDING = "poids_fenetres_anterieures"  # poids choisi sur les fenêtres 1..k-1


@dataclass(frozen=True)
class BlendSpec:
    mode: SelectionMode
    fixed_weight: float | None = None  # utilisé seulement si mode == FIXED

    @property
    def name(self) -> str:
        if self.mode is SelectionMode.FIXED:
            return f"candidat_a_blend_fixe_w{self.fixed_weight:.2f}"
        return "candidat_a_blend_poids_anterieurs"


def load_v1_operational_predictions() -> pd.DataFrame:
    """Prédictions opérationnelles V1 (figées), périmètre principal uniquement.

    Périmètre principal = produits présents dans le train au cutoff
    (``train_observations > 0``), cold-start exclu — exactement le périmètre
    sur lequel la V1 a publié WAPE 30 j = 0,2772.
    """
    paths = sorted(glob.glob(str(OPERATIONAL_DIR / "*.parquet")))
    if not paths:
        raise FileNotFoundError(
            "Prédictions opérationnelles V1 absentes : ce candidat historique "
            f"requiert les Parquet non versionnés dans {OPERATIONAL_DIR}."
        )
    frames = [pd.read_parquet(f) for f in paths]
    op = pd.concat(frames, ignore_index=True)
    op = op[op["train_observations"] > 0]
    keep = op["model_requested"].isin([MODEL_A, MODEL_B])
    return op.loc[keep, ["model_requested", "unique_id", "ds", "window", "y", "y_pred_final"]]


def build_blend_frame(op: pd.DataFrame) -> pd.DataFrame:
    """Aligne les deux modèles côte à côte sur (unique_id, ds, window)."""
    a = op[op["model_requested"] == MODEL_A].rename(columns={"y_pred_final": "pred_autoets"})
    b = op[op["model_requested"] == MODEL_B].rename(columns={"y_pred_final": "pred_wa28"})
    merged = a.drop(columns=["model_requested"]).merge(
        b.drop(columns=["model_requested", "y"]), on=["unique_id", "ds", "window"], how="inner",
    )
    if len(merged) != len(a) or len(merged) != len(b):
        raise ValueError(
            f"Alignement incomplet entre {MODEL_A} ({len(a)}) et {MODEL_B} ({len(b)}) : "
            f"{len(merged)} lignes appariées — les deux modèles doivent couvrir exactement "
            "le même périmètre pour une comparaison valide."
        )
    return merged


def blended_prediction(frame: pd.DataFrame, weight: float) -> np.ndarray:
    """y = w * AutoETS + (1-w) * WindowAverage28, borné à 0."""
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"poids hors [0,1] : {weight}")
    blended = weight * frame["pred_autoets"].to_numpy("float64") + (1 - weight) * frame["pred_wa28"].to_numpy("float64")
    return np.clip(blended, 0.0, None)


def _wape_cumule_30j(frame: pd.DataFrame, preds: np.ndarray) -> float:
    """WAPE au grain cumulé 30 j (somme par produit×fenêtre, puis WAPE poolée)
    — même définition que la V1 (`reports/23_rapport_final_forecasting.md` §1)."""
    tmp = frame[["unique_id", "window", "y"]].copy()
    tmp["pred"] = preds
    agg = tmp.groupby(["unique_id", "window"])[["y", "pred"]].sum()
    denom = agg["y"].sum()
    if denom <= 0:
        return float("nan")
    return float(np.abs(agg["pred"] - agg["y"]).sum() / denom)


def choose_weight_from_previous_windows(frame: pd.DataFrame, current_window: int) -> tuple[float, dict]:
    """Poids optimal sur les fenêtres STRICTEMENT antérieures à `current_window`.

    Renvoie (poids, détail) ; le détail journalise la WAPE de chaque poids
    candidat sur l'historique utilisé, pour audit.
    """
    history = frame[frame["window"] < current_window]
    if history.empty:
        return DEFAULT_WEIGHT, {
            "source": "defaut_aucune_fenetre_anterieure",
            "fenetres_utilisees": [],
            "wape_par_poids": {},
        }

    scores = {}
    for w in WEIGHT_GRID:
        scores[w] = _wape_cumule_30j(history, blended_prediction(history, w))
    best = min(scores, key=scores.get)
    return best, {
        "source": "fenetres_anterieures",
        "fenetres_utilisees": sorted(int(x) for x in history["window"].unique()),
        "wape_par_poids": {f"{k:.2f}": round(v, 6) for k, v in scores.items()},
    }


def run_candidate_a(spec: BlendSpec, frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Produit les prédictions du candidat A, fenêtre par fenêtre.

    Retourne un DataFrame au même grain que les prédictions V1
    (unique_id, ds, window, y, y_pred), directement comparable.
    """
    frame = build_blend_frame(load_v1_operational_predictions()) if frame is None else frame

    parts = []
    for window in sorted(frame["window"].unique()):
        sub = frame[frame["window"] == window].copy()
        if spec.mode is SelectionMode.FIXED:
            weight = spec.fixed_weight if spec.fixed_weight is not None else DEFAULT_WEIGHT
            detail = {"source": "poids_fixe", "fenetres_utilisees": [], "wape_par_poids": {}}
        else:
            weight, detail = choose_weight_from_previous_windows(frame, window)
        sub["y_pred"] = blended_prediction(sub, weight)
        sub["poids_autoets"] = weight
        sub["poids_source"] = detail["source"]
        sub["poids_fenetres_utilisees"] = str(detail["fenetres_utilisees"])
        parts.append(sub[["unique_id", "ds", "window", "y", "y_pred", "poids_autoets", "poids_source", "poids_fenetres_utilisees"]])

    out = pd.concat(parts, ignore_index=True)
    out["modele"] = spec.name
    return out
