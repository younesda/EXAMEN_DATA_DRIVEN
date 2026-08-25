"""Forecasting cumulatif 30 jours, perte alignee sur la metrique.

Constat qui motive l'experience : la reference `LightGBM_direct_per_horizon`
entraine 30 modeles journaliers sous perte Tweedie (esperance conditionnelle
journaliere) alors que la metrique de decision est
`WAPE30 = somme_produits |somme_h pred - somme_h y| / somme y`,
c'est-a-dire une perte L1 sur le TOTAL 30 jours. L'optimum de cette metrique
est la mediane conditionnelle du total, pas la somme des moyennes
journalieres.

Ce module apprend directement `y30 = somme(y[J+1..J+30])` avec une perte L1.
Perimetre, fenetres, population et definition de la WAPE sont identiques a la
reference. Les seules features ajoutees sont des agregats de calendrier et de
remise PLANIFIEE sur la fenetre cible : c'est exactement l'hypothese deja
retenue par la reference (`planned_discount`), transposee au grain cumulatif.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from src.config.settings import PROJECT_ROOT
from src.experiments.advanced_forecasting import BASE_FEATURES, WINDOWS

FEATURE_CACHE = PROJECT_ROOT / "data/cache/advanced_forecasting_features.parquet"
REFERENCE_PREDICTIONS = PROJECT_ROOT / "models/advanced/forecasting/direct_lightgbm_predictions.parquet"
OUT = PROJECT_ROOT / "reports" / "advanced"
CHECKPOINTS = PROJECT_ROOT / "checkpoints" / "cumulative_l1"
SEED = 42
HORIZON = 30
PARAM_GRID = (
    {"num_leaves": 15, "min_child_samples": 60, "learning_rate": .05, "n_estimators": 300},
    {"num_leaves": 31, "min_child_samples": 80, "learning_rate": .035, "n_estimators": 400},
    {"num_leaves": 47, "min_child_samples": 120, "learning_rate": .03, "n_estimators": 500},
)
# Features au cutoff, communes avec la reference, moins les champs propres a
# un horizon unique (target_dow, planned_discount d'un seul jour, ...).
CUTOFF_FEATURES = [c for c in BASE_FEATURES if not c.startswith("target_") and c != "planned_discount"]
HORIZON_FEATURES = ["h_weekend_days", "h_month_start_days", "h_month_end_days", "h_start_month",
                    "h_planned_discount_mean", "h_planned_discount_max", "h_planned_discount_days"]
FEATURES = CUTOFF_FEATURES + HORIZON_FEATURES


def _forward_sum(series: pd.Series, how: str = "sum") -> pd.Series:
    """Agregat sur [t+1, t+30] : rolling() est arriere, shift(-30) la ramene en avant."""
    shifted = series.shift(-HORIZON)
    rolling = shifted.rolling(HORIZON, min_periods=HORIZON)
    return getattr(rolling, how)()


def build_cumulative_frame(features: pd.DataFrame) -> pd.DataFrame:
    """Cible = somme des 30 jours suivant le cutoff ; agregats de fenetre cible
    strictement issus du calendrier et du calendrier promotionnel gele."""
    d = features.sort_values(["produit_key", "ds"]).copy()
    group = d.groupby("produit_key", sort=False)
    d["target"] = group.y.transform(_forward_sum)
    d["target_end_ds"] = d.ds + pd.Timedelta(days=HORIZON)

    calendar = pd.DataFrame({"ds": pd.Index(sorted(d.ds.unique()))})
    calendar["is_weekend"] = (calendar.ds.dt.dayofweek >= 5).astype(float)
    calendar["is_month_start"] = calendar.ds.dt.is_month_start.astype(float)
    calendar["is_month_end"] = calendar.ds.dt.is_month_end.astype(float)
    calendar["h_weekend_days"] = _forward_sum(calendar.is_weekend)
    calendar["h_month_start_days"] = _forward_sum(calendar.is_month_start)
    calendar["h_month_end_days"] = _forward_sum(calendar.is_month_end)
    calendar["h_start_month"] = (calendar.ds + pd.Timedelta(days=1)).dt.month.astype(float)
    d = d.merge(calendar[["ds", "h_weekend_days", "h_month_start_days",
                          "h_month_end_days", "h_start_month"]], on="ds", how="left")

    # Remise planifiee sur la fenetre cible : meme hypothese que la reference.
    d = d.sort_values(["produit_key", "ds"])
    group = d.groupby("produit_key", sort=False)
    d["h_planned_discount_mean"] = group.remise_pct.transform(lambda x: _forward_sum(x, "mean"))
    d["h_planned_discount_max"] = group.remise_pct.transform(lambda x: _forward_sum(x, "max"))
    d["h_planned_discount_days"] = group.remise_pct.transform(
        lambda x: _forward_sum((x > 0).astype(float)))
    return d


def _model(params: dict, objective: str) -> LGBMRegressor:
    kwargs = dict(subsample=.85, colsample_bytree=.8, reg_lambda=.2,
                  random_state=SEED, n_jobs=2, verbosity=-1, **params)
    if objective == "l1":
        return LGBMRegressor(objective="regression_l1", **kwargs)
    return LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, **kwargs)


def _fit_predict(frame: pd.DataFrame, train_target_end: pd.Timestamp,
                 origin: pd.Timestamp, params: dict, objective: str):
    train = frame[(frame.target_end_ds <= train_target_end) & frame.target.notna()]
    test = frame[frame.ds.eq(origin)]
    x_train = train[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0)
    x_test = test[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0)
    start = time.perf_counter()
    model = _model(params, objective)
    model.fit(x_train, train.target)
    elapsed = time.perf_counter() - start
    prediction = np.maximum(0, model.predict(x_test))
    return test.produit_key.to_numpy(), prediction, test.target.to_numpy(float), elapsed, len(train)


def tune(frame: pd.DataFrame, external_start: pd.Timestamp, objective: str):
    """Pseudo-cutoff strictement anterieur a la fenetre externe."""
    validation_origin = external_start - pd.Timedelta(days=HORIZON + 1)
    scores = []
    for params in PARAM_GRID:
        _, pred, actual, elapsed, n_train = _fit_predict(
            frame, validation_origin, validation_origin, params, objective)
        wape = float(np.abs(pred - actual).sum() / max(actual.sum(), 1))
        scores.append({"params": params, "wape": wape, "elapsed_seconds": elapsed, "n_train": n_train})
    best = min(scores, key=lambda row: row["wape"])
    return best["params"], scores


def main(windows: tuple[int, ...] = (1, 2)) -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    features = pd.read_parquet(FEATURE_CACHE)
    features["ds"] = pd.to_datetime(features.ds)
    frame = build_cumulative_frame(features)
    max_ds = features.ds.max()

    reference = pd.read_parquet(REFERENCE_PREDICTIONS)
    reference_totals = (reference.groupby(["window", "produit_key"])[["y", "pred"]].sum()
                        .rename(columns={"pred": "ref_pred"}).reset_index())

    rows, tuning_log = [], []
    for window in windows:
        back = WINDOWS[window - 1]
        test_start = max_ds - pd.Timedelta(days=back - 1)
        origin = test_start - pd.Timedelta(days=1)
        for objective in ("l1", "tweedie"):
            params, tuning = tune(frame, test_start, objective)
            tuning_log.append({"window": window, "objective": objective, "tuning": tuning})
            keys, pred, actual, elapsed, n_train = _fit_predict(
                frame, origin, origin, params, objective)
            rows.append(pd.DataFrame({"window": window, "produit_key": keys, "y": actual,
                                      "pred": pred, "model": "cumulative_" + objective,
                                      "elapsed_seconds": elapsed, "n_train": n_train,
                                      "params": json.dumps(params), "origin": origin,
                                      "test_start": test_start}))
    predictions = pd.concat(rows, ignore_index=True)

    # Controle de perimetre : memes 300 produits, memes totaux reels que la reference.
    merged = predictions.merge(reference_totals, on=["window", "produit_key"],
                               suffixes=("", "_ref"), validate="many_to_one")
    if len(merged) != len(predictions):
        raise AssertionError("Perimetre non identique a la reference.")
    if not np.allclose(merged.y, merged.y_ref):
        raise AssertionError("Totaux reels divergents de la reference.")

    # Melange predefini 50/50 avec la reference (poids fixe a priori, non ajuste).
    blend = merged[merged.model.eq("cumulative_l1")].copy()
    blend["pred"] = .5 * blend.pred + .5 * blend.ref_pred
    blend["model"] = "blend_50_50_l1_reference"
    ref_rows = merged[merged.model.eq("cumulative_l1")].copy()
    ref_rows["pred"] = ref_rows.ref_pred
    ref_rows["model"] = "reference_direct_per_horizon"
    merged = pd.concat([merged, blend, ref_rows], ignore_index=True)

    summary = (merged.groupby(["model", "window"])
               .apply(lambda g: pd.Series({
                   "wape30": float((g.pred - g.y).abs().sum() / g.y.sum()),
                   "bias": float((g.pred - g.y).sum() / g.y.sum()),
                   "n_products": int(g.produit_key.nunique())}), include_groups=False)
               .reset_index())
    mean_by_model = summary.groupby("model").wape30.mean()
    reference_mean = float(mean_by_model["reference_direct_per_horizon"])
    gate = reference_mean * .95
    payload = {
        "protocole": "cible = somme(y[J+1..J+30]) ; perte L1 alignee sur WAPE30",
        "fenetres_pilote": list(windows),
        "reference_mean_wape30": reference_mean,
        "gate_5pct": gate,
        "per_window": summary.to_dict("records"),
        "mean_wape30": {k: float(v) for k, v in mean_by_model.items()},
        "gate_pass": {k: bool(v <= gate) for k, v in mean_by_model.items()},
        "n_features": len(FEATURES),
        "horizon_features": HORIZON_FEATURES,
        "tuning": tuning_log,
        "controls": {"population_identique": True, "grain_identique": "produit x fenetre",
                     "tuning_sur_test": False, "negatifs": int((merged.pred < 0).sum()),
                     "nan": int(merged.pred.isna().sum())},
    }
    (OUT / "cumulative_l1_pilot.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    merged.to_parquet(CHECKPOINTS / "pilot_predictions.parquet", index=False)
    print(summary.to_string(index=False))
    print()
    print("reference mean:", round(reference_mean, 5), "| gate <=", round(gate, 5))
    print(json.dumps({k: round(float(v), 5) for k, v in mean_by_model.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
