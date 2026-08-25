"""Intervalles conformes empiriques — deux régimes de calibration.

**Régime V1 (`leave_one_window_out`)** — celui qu'a utilisé la V1
(`reports/23_rapport_final_forecasting.md` §8) : pour évaluer la fenêtre k, on
calibre sur les résidus de toutes les AUTRES fenêtres (avant ET après k).
Conservé ici uniquement pour comparer un candidat à la V1 **à méthode
identique** — sinon on comparerait deux méthodes en croyant comparer deux
modèles.

**Régime V2 strict (`prior_windows_only`)** — pour la fenêtre k, on ne calibre
que sur les fenêtres 1..k-1. C'est la seule variante utilisable en production
(on ne connaît pas l'avenir au moment de prévoir). La fenêtre 1 n'a aucune
fenêtre antérieure : elle est marquée **non calibrable** et conserve
l'intervalle V1 plutôt que d'inventer une calibration.

Les bornes de quantité sont toujours ramenées à ≥ 0.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
import pandas as pd

HORIZON_BUCKETS = (
    ("J+1", 1, 1),
    ("J+2 a J+7", 2, 7),
    ("J+8 a J+14", 8, 14),
    ("J+15 a J+30", 15, 30),
)
NIVEAUX = (0.80, 0.95)
MIN_RESIDUS_CALIBRATION = 30  # en dessous : segment jugé non calibrable, repli sur le niveau supérieur


class CalibrationRegime(str, Enum):
    LEAVE_ONE_WINDOW_OUT = "leave_one_window_out"   # méthode V1, pour comparaison à l'identique
    PRIOR_WINDOWS_ONLY = "prior_windows_only"       # méthode V2 stricte, utilisable en production


def bucket_of(h: int) -> str:
    for label, lo, hi in HORIZON_BUCKETS:
        if lo <= h <= hi:
            return label
    raise ValueError(f"horizon hors bornes : {h}")


def _quantiles(residus: np.ndarray, niveau: float) -> tuple[float, float]:
    alpha = 1 - niveau
    return float(np.quantile(residus, alpha / 2)), float(np.quantile(residus, 1 - alpha / 2))


def compute_intervals(
    frame: pd.DataFrame,
    regime: CalibrationRegime,
    niveau: float = 0.80,
    segment_cols: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Ajoute `borne_basse` / `borne_haute` / `calibrable` à `frame`.

    `frame` doit contenir : unique_id, window, h, y, y_pred (+ les colonnes de
    `segment_cols` si une calibration par segment est demandée).

    La calibration se fait toujours par bucket d'horizon, éventuellement
    croisée avec les colonnes de segment. Si un groupe a moins de
    ``MIN_RESIDUS_CALIBRATION`` résidus, on retombe sur la calibration du
    bucket d'horizon seul (et si celle-ci est elle aussi trop pauvre, le point
    est marqué non calibrable).
    """
    df = frame.copy()
    df["bucket"] = df["h"].map(bucket_of)
    df["residu"] = df["y"] - df["y_pred"]

    df["borne_basse"] = np.nan
    df["borne_haute"] = np.nan
    df["calibrable"] = False
    df["source_calibration"] = "aucune"

    windows = sorted(df["window"].unique())
    for window in windows:
        if regime is CalibrationRegime.LEAVE_ONE_WINDOW_OUT:
            calib_mask = df["window"] != window
        else:
            calib_mask = df["window"] < window
        eval_mask = df["window"] == window

        if not calib_mask.any():
            # Fenêtre 1 en régime strict : aucune donnée antérieure.
            df.loc[eval_mask, "source_calibration"] = "non_calibrable_aucune_fenetre_anterieure"
            continue

        calib = df[calib_mask]
        for bucket, _, _ in HORIZON_BUCKETS:
            bucket_eval = eval_mask & (df["bucket"] == bucket)
            if not bucket_eval.any():
                continue
            bucket_calib = calib[calib["bucket"] == bucket]

            if segment_cols:
                for seg_values, seg_group in df[bucket_eval].groupby(list(segment_cols)):
                    seg_values = seg_values if isinstance(seg_values, tuple) else (seg_values,)
                    sel = bucket_calib
                    for col, val in zip(segment_cols, seg_values):
                        sel = sel[sel[col] == val]
                    if len(sel) >= MIN_RESIDUS_CALIBRATION:
                        lo, hi = _quantiles(sel["residu"].to_numpy("float64"), niveau)
                        source = f"bucket+{'+'.join(segment_cols)}"
                    elif len(bucket_calib) >= MIN_RESIDUS_CALIBRATION:
                        lo, hi = _quantiles(bucket_calib["residu"].to_numpy("float64"), niveau)
                        source = "bucket_seul_effectif_segment_insuffisant"
                    else:
                        continue
                    idx = seg_group.index
                    df.loc[idx, "borne_basse"] = np.maximum(df.loc[idx, "y_pred"] + lo, 0.0)
                    df.loc[idx, "borne_haute"] = np.maximum(df.loc[idx, "y_pred"] + hi, df.loc[idx, "borne_basse"])
                    df.loc[idx, "calibrable"] = True
                    df.loc[idx, "source_calibration"] = source
            else:
                if len(bucket_calib) < MIN_RESIDUS_CALIBRATION:
                    continue
                lo, hi = _quantiles(bucket_calib["residu"].to_numpy("float64"), niveau)
                idx = df[bucket_eval].index
                df.loc[idx, "borne_basse"] = np.maximum(df.loc[idx, "y_pred"] + lo, 0.0)
                df.loc[idx, "borne_haute"] = np.maximum(df.loc[idx, "y_pred"] + hi, df.loc[idx, "borne_basse"])
                df.loc[idx, "calibrable"] = True
                df.loc[idx, "source_calibration"] = "bucket_global"

    return df


def coverage_report(df: pd.DataFrame, segments: pd.DataFrame | None = None, niveau: float = 0.80) -> dict:
    """Couverture empirique, largeur, et part d'intervalles inutilement larges.

    « Inutilement large » = intervalle dont la largeur dépasse 3× la largeur
    médiane observée : une couverture correcte obtenue en élargissant sans
    discernement n'est pas une amélioration (critère explicite du protocole).
    """
    calibrable = df[df["calibrable"]]
    if calibrable.empty:
        return {"niveau_vise": niveau, "n_points_calibrables": 0, "couverture_globale": float("nan")}

    couvert = (calibrable["y"] >= calibrable["borne_basse"]) & (calibrable["y"] <= calibrable["borne_haute"])
    largeur = (calibrable["borne_haute"] - calibrable["borne_basse"]).to_numpy("float64")
    largeur_mediane = float(np.median(largeur))
    trop_large = float((largeur > 3 * largeur_mediane).mean()) if largeur_mediane > 0 else float("nan")

    out = {
        "niveau_vise": niveau,
        "n_points_total": int(len(df)),
        "n_points_calibrables": int(len(calibrable)),
        "part_non_calibrable": float(1 - len(calibrable) / len(df)),
        "couverture_globale": float(couvert.mean()),
        "largeur_moyenne": float(largeur.mean()),
        "largeur_mediane": largeur_mediane,
        "part_intervalles_excessivement_larges": trop_large,
        "par_bucket": {},
        "par_fenetre": {},
    }

    tmp = calibrable.assign(couvert=couvert)
    for bucket, g in tmp.groupby("bucket"):
        w = (g["borne_haute"] - g["borne_basse"]).to_numpy("float64")
        out["par_bucket"][str(bucket)] = {
            "couverture": float(g["couvert"].mean()),
            "largeur_moyenne": float(w.mean()),
            "n_points": int(len(g)),
        }
    for window, g in tmp.groupby("window"):
        out["par_fenetre"][str(int(window))] = {
            "couverture": float(g["couvert"].mean()),
            "n_points": int(len(g)),
        }

    if segments is not None:
        merged = tmp.merge(segments, on=["unique_id", "window"], how="left", suffixes=("", "_seg"))
        for col, label in [("classe_abc", "abc"), ("profil_demande", "profil")]:
            if col not in merged.columns:
                continue
            detail = {}
            for value, g in merged.groupby(col):
                w = (g["borne_haute"] - g["borne_basse"]).to_numpy("float64")
                detail[str(value)] = {
                    "couverture": float(g["couvert"].mean()),
                    "largeur_moyenne": float(w.mean()),
                    "n_points": int(len(g)),
                }
            out[f"par_{label}"] = detail

    return out
