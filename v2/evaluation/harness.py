"""Harnais d'évaluation commun aux candidats Forecasting V2.

Un seul module calcule les métriques pour TOUS les candidats, avec exactement
les mêmes définitions que la V1 — c'est ce qui rend les comparaisons valides.
Aucun candidat ne définit ses propres métriques.

Définitions (identiques à la V1, `reports/23_rapport_final_forecasting.md` §1) :

* **WAPE quotidienne** : chaque ligne (produit, jour) compte individuellement.
* **WAPE cumulée à N jours** : ``SUM(y)`` et ``SUM(y_pred)`` par (produit,
  fenêtre) sur les N premiers jours de l'horizon, PUIS WAPE poolée.
* **Biais normalisé** : ``SUM(y_pred - y) / SUM(y)`` — invariant de grain.
* **Segments** : recalculés PAR FENÊTRE sur le train uniquement (jamais sur
  l'historique complet), comme en V1.
"""

from __future__ import annotations

import glob
import json
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.features.segmentation import SegmentationConfig, classify, compute_series_features
from src.pipelines.backtest_baselines import build_windows
from src.pipelines.backtest_postprocess import OPERATIONAL_DIR

TABLE_PATH = PROJECT_ROOT / "data" / "processed" / "table_analytique.parquet"
V2_REPORTS = PROJECT_ROOT / "v2" / "reports"
V2_EVAL = PROJECT_ROOT / "v2" / "evaluation"
V2_MODELS = PROJECT_ROOT / "v2" / "models"
V2_LOG_PATH = V2_REPORTS / "v2_forecasting_log.jsonl"

CUMUL_HORIZONS = (7, 14, 30)
NOUVEAU_MAX_JOURS_HISTORIQUE = 90  # "produit récent" : <90 j d'historique au cutoff


# =============================================================================
# Journalisation (durée, mémoire, statut) — un événement par étape
# =============================================================================
def log_event(payload: dict, log_path=None) -> None:
    from datetime import datetime, timezone

    path = log_path or V2_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def current_rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        return None


# =============================================================================
# Métriques élémentaires (implémentation unique, réutilisée partout)
# =============================================================================
def wape(y: np.ndarray, y_pred: np.ndarray) -> float:
    denom = y.sum()
    return float(np.abs(y_pred - y).sum() / denom) if denom > 0 else float("nan")


def biais_normalise(y: np.ndarray, y_pred: np.ndarray) -> float:
    denom = y.sum()
    return float((y_pred - y).sum() / denom) if denom > 0 else float("nan")


def mae(y: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.abs(y_pred - y).mean()) if len(y) else float("nan")


def _cumule(frame: pd.DataFrame, days: int) -> pd.DataFrame:
    """Agrège par (produit, fenêtre) sur les `days` premiers jours d'horizon."""
    sub = frame[frame["h"] <= days]
    return sub.groupby(["unique_id", "window"])[["y", "y_pred"]].sum().reset_index()


# =============================================================================
# Segments recalculés par fenêtre sur le TRAIN uniquement
# =============================================================================
@dataclass
class SegmentContext:
    """Segments par (produit, fenêtre), calculés sur le train de la fenêtre."""

    table: pd.DataFrame = field(repr=False)
    _cache: pd.DataFrame | None = field(default=None, repr=False)

    def build(self) -> pd.DataFrame:
        if self._cache is not None:
            return self._cache
        rows = []
        for spec in build_windows(self.table):
            train = self.table[self.table["ds"] <= spec.train_end]
            feats = compute_series_features(train)
            seg = classify(feats, SegmentationConfig())
            seg = seg[["unique_id", "classe_abc", "profil_demande", "statut", "n_jours", "taux_jours_sans_vente", "adi"]].copy()
            seg["window"] = spec.index
            seg["produit_recent"] = seg["n_jours"] < NOUVEAU_MAX_JOURS_HISTORIQUE
            rows.append(seg)
        self._cache = pd.concat(rows, ignore_index=True)
        return self._cache


def load_analytical_table() -> pd.DataFrame:
    table = pd.read_parquet(TABLE_PATH)
    table["ds"] = pd.to_datetime(table["ds"])
    return table


def attach_horizon(frame: pd.DataFrame) -> pd.DataFrame:
    """Ajoute `h` = jours écoulés depuis le cutoff (1..30)."""
    cutoffs = {spec.index: spec.train_end for spec in build_windows(load_analytical_table())}
    out = frame.copy()
    out["cutoff"] = out["window"].map(cutoffs)
    out["h"] = (pd.to_datetime(out["ds"]) - pd.to_datetime(out["cutoff"])).dt.days
    if not out["h"].between(1, 30).all():
        bad = out.loc[~out["h"].between(1, 30), "h"].unique()[:5]
        raise ValueError(f"Horizons hors [1,30] détectés : {bad}")
    return out


# =============================================================================
# Évaluation complète d'un jeu de prédictions
# =============================================================================
def evaluate_predictions(frame: pd.DataFrame, segments: pd.DataFrame, label: str) -> dict:
    """`frame` doit contenir : unique_id, ds, window, y, y_pred.

    Renvoie un dictionnaire complet de métriques, structuré pour être écrit
    tel quel en JSON et rendu en markdown.
    """
    if "h" not in frame.columns:
        frame = attach_horizon(frame)

    y_all = frame["y"].to_numpy("float64")
    p_all = frame["y_pred"].to_numpy("float64")

    resultat: dict = {
        "label": label,
        "n_lignes": int(len(frame)),
        "n_produits_fenetres": int(frame[["unique_id", "window"]].drop_duplicates().shape[0]),
        "qualite": {
            "n_non_finis": int((~np.isfinite(p_all)).sum()),
            "n_negatifs": int((p_all < 0).sum()),
        },
        "quotidien": {
            "WAPE": wape(y_all, p_all),
            "MAE": mae(y_all, p_all),
            "biais_normalise": biais_normalise(y_all, p_all),
        },
        "cumule": {},
        "par_fenetre": [],
        "par_segment": {},
    }

    for days in CUMUL_HORIZONS:
        agg = _cumule(frame, days)
        y, p = agg["y"].to_numpy("float64"), agg["y_pred"].to_numpy("float64")
        resultat["cumule"][str(days)] = {
            "WAPE": wape(y, p),
            "MAE": mae(y, p),
            "biais_normalise": biais_normalise(y, p),
            "n_produits_fenetres": int(len(agg)),
        }

    # --- Par fenêtre (grain cumulé 30 j, métrique de sélection) -------------
    agg30 = _cumule(frame, 30)
    for window, g in agg30.groupby("window"):
        y, p = g["y"].to_numpy("float64"), g["y_pred"].to_numpy("float64")
        resultat["par_fenetre"].append({
            "fenetre": int(window),
            "WAPE_cumule_30j": wape(y, p),
            "biais_normalise": biais_normalise(y, p),
            "n_produits": int(len(g)),
        })

    wapes = [r["WAPE_cumule_30j"] for r in resultat["par_fenetre"]]
    resultat["stabilite"] = {
        "WAPE_30j_moyenne": float(np.mean(wapes)),
        "WAPE_30j_ecart_type": float(np.std(wapes, ddof=1)),
        "WAPE_30j_min": float(np.min(wapes)),
        "WAPE_30j_max": float(np.max(wapes)),
    }

    # --- Par segment (segments train-only, joints sur produit+fenêtre) ------
    agg30_seg = agg30.merge(segments, on=["unique_id", "window"], how="left")
    for seg_col, label_seg in [("classe_abc", "abc"), ("profil_demande", "profil")]:
        detail = {}
        for value, g in agg30_seg.groupby(seg_col):
            y, p = g["y"].to_numpy("float64"), g["y_pred"].to_numpy("float64")
            detail[str(value)] = {
                "WAPE_cumule_30j": wape(y, p),
                "biais_normalise": biais_normalise(y, p),
                "n_produits_fenetres": int(len(g)),
            }
        resultat["par_segment"][label_seg] = detail

    recents = agg30_seg[agg30_seg["produit_recent"] == True]  # noqa: E712
    if len(recents):
        y, p = recents["y"].to_numpy("float64"), recents["y_pred"].to_numpy("float64")
        resultat["par_segment"]["produits_recents"] = {
            "WAPE_cumule_30j": wape(y, p),
            "biais_normalise": biais_normalise(y, p),
            "n_produits_fenetres": int(len(recents)),
            "definition": f"historique < {NOUVEAU_MAX_JOURS_HISTORIQUE} jours au cutoff",
        }

    return resultat


# =============================================================================
# Référence V1 évaluée avec CE harnais (comparaison à définition identique)
# =============================================================================
def load_v1_predictions(model: str = "AutoETS") -> pd.DataFrame:
    frames = [pd.read_parquet(f) for f in sorted(glob.glob(str(OPERATIONAL_DIR / "*.parquet")))]
    op = pd.concat(frames, ignore_index=True)
    op = op[(op["model_requested"] == model) & (op["train_observations"] > 0)]
    out = op[["unique_id", "ds", "window", "y", "y_pred_final"]].rename(columns={"y_pred_final": "y_pred"})
    return out.reset_index(drop=True)


def compare_to_v1(candidate: dict, v1: dict) -> dict:
    """Comparaison chiffrée candidat vs V1, y compris le décompte de fenêtres
    améliorées à l'horizon 30 jours."""
    v1_par_fenetre = {r["fenetre"]: r["WAPE_cumule_30j"] for r in v1["par_fenetre"]}
    ameliorees, detail = 0, []
    for r in candidate["par_fenetre"]:
        ref = v1_par_fenetre[r["fenetre"]]
        gain = ref - r["WAPE_cumule_30j"]
        est_amelioree = gain > 0
        ameliorees += int(est_amelioree)
        detail.append({
            "fenetre": r["fenetre"], "v1": ref, "candidat": r["WAPE_cumule_30j"],
            "gain_absolu": gain, "gain_relatif": gain / ref if ref else float("nan"),
            "amelioree": est_amelioree,
        })

    def _delta(path: list[str]) -> dict:
        cur, ref = candidate, v1
        for k in path:
            cur, ref = cur[k], ref[k]
        return {
            "v1": ref, "candidat": cur,
            "gain_absolu": ref - cur,
            "gain_relatif": (ref - cur) / ref if ref else float("nan"),
        }

    return {
        "wape_quotidien": _delta(["quotidien", "WAPE"]),
        "wape_cumule_7j": _delta(["cumule", "7", "WAPE"]),
        "wape_cumule_14j": _delta(["cumule", "14", "WAPE"]),
        "wape_cumule_30j": _delta(["cumule", "30", "WAPE"]),
        "n_fenetres_ameliorees_30j": ameliorees,
        "detail_par_fenetre": detail,
    }
