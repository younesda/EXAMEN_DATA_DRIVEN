"""Challengers globaux directs du forecasting avancé, séquentiels et checkpointés."""
from __future__ import annotations

import gc
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
from catboost import CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from xgboost import XGBRegressor

from src.config.settings import PROJECT_ROOT
from src.experiments.advanced_forecasting import (
    BASE_FEATURES, FEATURE_CACHE, HORIZONS, SEED, WINDOWS, horizon_frame,
)

OUT = PROJECT_ROOT / "models/advanced/forecasting"
CHECKPOINTS = PROJECT_ROOT / "checkpoints/advanced_forecasting_candidates"
LOG = PROJECT_ROOT / "logs/advanced_forecasting_candidates.jsonl"
MAX_SECONDS_PER_MODEL = 300
FEATURES = list(BASE_FEATURES) + ["horizon"]
MODEL_NAMES = (
    "LightGBM_global_tweedie", "CatBoost_poisson", "CatBoost_tweedie",
    "XGBoost_count_poisson", "Hurdle_global", "LightGBM_global_quantile_p50",
)


def _log(event: str, **values) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": pd.Timestamp.utcnow().isoformat(), "event": event, **values}, default=str) + "\n")


def stacked_window(features: pd.DataFrame, test_start: pd.Timestamp, stride: int = 14):
    origin = test_start - pd.Timedelta(days=1)
    minimum = features.ds.min()
    train_parts, test_parts = [], []
    for horizon in HORIZONS:
        frame = horizon_frame(features, horizon)
        eligible = frame[(frame.target_ds < test_start) & frame.target.notna()].copy()
        day_number = (eligible.ds - minimum).dt.days
        eligible = eligible[day_number.mod(stride).eq(0)]
        eligible["horizon"] = horizon
        train_parts.append(eligible[FEATURES + ["target"]])
        test = frame[frame.ds.eq(origin)].copy()
        test["horizon"] = horizon
        test_parts.append(test[["produit_key", "target_ds", "target", *FEATURES]])
    train = pd.concat(train_parts, ignore_index=True)
    test = pd.concat(test_parts, ignore_index=True).rename(columns={"target_ds": "ds", "target": "y"})
    X_train = train[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy(np.float32)
    y_train = train.target.to_numpy(np.float32)
    X_test = test[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy(np.float32)
    return X_train, y_train, X_test, test[["produit_key", "ds", "y", "horizon"]]


def _fit_candidate(name: str, X_train, y_train, X_test):
    if name == "LightGBM_global_tweedie":
        model = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, n_estimators=260,
                              learning_rate=.035, num_leaves=31, min_child_samples=100,
                              subsample=.85, colsample_bytree=.8, random_state=SEED, n_jobs=2, verbosity=-1)
        model.fit(X_train, y_train); return np.maximum(0, model.predict(X_test)), {}
    if name.startswith("CatBoost"):
        loss = "Poisson" if name.endswith("poisson") else "Tweedie:variance_power=1.3"
        model = CatBoostRegressor(loss_function=loss, iterations=220, depth=7, learning_rate=.04,
                                  random_seed=SEED, thread_count=2, verbose=False, allow_writing_files=False)
        model.fit(X_train, y_train); return np.maximum(0, model.predict(X_test)), {}
    if name == "XGBoost_count_poisson":
        model = XGBRegressor(objective="count:poisson", n_estimators=240, learning_rate=.04,
                             max_depth=7, min_child_weight=20, subsample=.85, colsample_bytree=.8,
                             reg_lambda=.2, random_state=SEED, n_jobs=2, tree_method="hist")
        model.fit(X_train, y_train); return np.maximum(0, model.predict(X_test)), {}
    if name == "Hurdle_global":
        classifier = LGBMClassifier(n_estimators=180, learning_rate=.04, num_leaves=31,
                                    min_child_samples=100, random_state=SEED, n_jobs=2, verbosity=-1)
        regressor = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, n_estimators=220,
                                  learning_rate=.04, num_leaves=31, min_child_samples=80,
                                  random_state=SEED, n_jobs=2, verbosity=-1)
        classifier.fit(X_train, (y_train > 0).astype(np.int8))
        regressor.fit(X_train[y_train > 0], y_train[y_train > 0])
        return np.maximum(0, classifier.predict_proba(X_test)[:, 1] * regressor.predict(X_test)), {}
    if name == "LightGBM_global_quantile_p50":
        predictions, extra = {}, {}
        for quantile in (.1, .5, .9):
            model = LGBMRegressor(objective="quantile", alpha=quantile, n_estimators=220,
                                  learning_rate=.04, num_leaves=31, min_child_samples=100,
                                  random_state=SEED, n_jobs=2, verbosity=-1)
            model.fit(X_train, y_train)
            predictions[quantile] = np.maximum(0, model.predict(X_test))
        extra["p10"] = predictions[.1]; extra["p90"] = predictions[.9]
        return predictions[.5], extra
    raise KeyError(name)


def metrics(frame: pd.DataFrame) -> dict:
    error = frame.pred - frame.y
    daily = float(np.abs(error).sum() / max(frame.y.sum(), 1))
    cumulative = frame.groupby("produit_key")[["y", "pred"]].sum()
    first7 = frame[frame.horizon.le(7)].groupby("produit_key")[["y", "pred"]].sum()
    return {"wape_daily": daily,
            "wape_cum_7": float((first7.pred - first7.y).abs().sum() / max(first7.y.sum(), 1)),
            "wape_cum_30": float((cumulative.pred - cumulative.y).abs().sum() / max(cumulative.y.sum(), 1)),
            "bias": float(error.sum() / max(frame.y.sum(), 1))}


def expanding_ensemble(per_horizon: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Choisit candidat et poids sur les fenêtres strictement précédentes."""
    rows, decisions = [], []
    grid = (0.0, .25, .5, .75, 1.0)
    for window in range(1, 7):
        if window == 1:
            candidate, weight = "LightGBM_global_tweedie", .5
        else:
            best = None
            for candidate_name in MODEL_NAMES:
                for weight_value in grid:
                    left = per_horizon[per_horizon.window.lt(window)]
                    right = candidates[candidates.window.lt(window) & candidates.model.eq(candidate_name)]
                    merged = left.merge(right, on=["window", "produit_key", "ds", "y", "horizon"], suffixes=("_direct", "_candidate"))
                    pred = weight_value * merged.pred_direct + (1 - weight_value) * merged.pred_candidate
                    agg = merged.assign(pred=pred).groupby(["window", "produit_key"])[["y", "pred"]].sum()
                    score = float((agg.pred - agg.y).abs().sum() / max(agg.y.sum(), 1))
                    if best is None or score < best[0]: best = (score, candidate_name, weight_value)
            _, candidate, weight = best
        left = per_horizon[per_horizon.window.eq(window)]
        right = candidates[candidates.window.eq(window) & candidates.model.eq(candidate)]
        merged = left.merge(right, on=["window", "produit_key", "ds", "y", "horizon"], suffixes=("_direct", "_candidate"))
        merged["pred"] = weight * merged.pred_direct + (1 - weight) * merged.pred_candidate
        rows.append(merged[["window", "produit_key", "ds", "y", "horizon", "pred"]])
        decisions.append({"window": window, "candidate": candidate, "direct_weight": weight,
                          "selection_windows": list(range(1, window))})
    return pd.concat(rows, ignore_index=True), decisions


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True); CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    features = pd.read_parquet(FEATURE_CACHE); features["ds"] = pd.to_datetime(features.ds)
    max_ds = features.ds.max(); result_rows, prediction_parts, quantile_rows = [], [], []
    for window, back in enumerate(WINDOWS, 1):
        test_start = max_ds - pd.Timedelta(days=back - 1)
        X_train, y_train, X_test, identity = stacked_window(features, test_start)
        for name in MODEL_NAMES:
            checkpoint = CHECKPOINTS / f"window_{window}_{name}.parquet"
            if checkpoint.exists():
                output = pd.read_parquet(checkpoint)
            else:
                start = time.perf_counter()
                try:
                    prediction, extra = _fit_candidate(name, X_train, y_train, X_test)
                    elapsed = time.perf_counter() - start
                    output = identity.copy(); output["pred"] = prediction; output["window"] = window; output["model"] = name
                    if extra:
                        output["p10"] = extra["p10"]; output["p90"] = extra["p90"]
                    output.to_parquet(checkpoint, index=False)
                    _log("model_complete", window=window, model=name, elapsed_seconds=elapsed,
                         peak_rss_mb=psutil.Process().memory_info().rss / 2**20, success=True)
                    if elapsed > MAX_SECONDS_PER_MODEL:
                        _log("model_timeout_budget_exceeded", window=window, model=name,
                             elapsed_seconds=elapsed, configured_limit=MAX_SECONDS_PER_MODEL)
                except Exception as exc:
                    _log("model_failed", window=window, model=name, error_type=type(exc).__name__, success=False)
                    continue
            prediction_parts.append(output[["window", "produit_key", "ds", "y", "horizon", "pred", "model"]])
            result_rows.append({"window": window, "model": name, **metrics(output)})
            if {"p10", "p90"} <= set(output):
                quantile_rows.append({"window": window, "coverage_p10_p90": float(output.y.between(output.p10, output.p90).mean()),
                                      "mean_width_p10_p90": float((output.p90-output.p10).mean())})
        del X_train, y_train, X_test
        gc.collect()
    candidates = pd.concat(prediction_parts, ignore_index=True)
    direct = pd.read_parquet(OUT / "direct_lightgbm_predictions.parquet")
    ensemble, decisions = expanding_ensemble(direct, candidates)
    ensemble_metrics = [{"window": window, "model": "ExpandingEnsemble", **metrics(group)} for window, group in ensemble.groupby("window")]
    results = pd.DataFrame(result_rows + ensemble_metrics)
    summary = results.groupby("model").agg(wape_daily=("wape_daily", "mean"), wape_cum_7=("wape_cum_7", "mean"),
        wape_cum_30=("wape_cum_30", "mean"), bias=("bias", "mean"), n_windows=("window", "nunique")).reset_index().sort_values("wape_cum_30")
    metadata = {"models": list(MODEL_NAMES), "fixed_hyperparameters": True, "test_used_for_tuning": False,
                "training_origin_stride_days": 14, "window_metrics": result_rows + ensemble_metrics,
                "summary": summary.to_dict("records"), "ensemble_decisions": decisions,
                "native_quantile_80": quantile_rows,
                "resource_policy": {"sequential": True, "max_seconds_per_model": MAX_SECONDS_PER_MODEL}}
    (OUT / "candidate_comparison.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    candidates.to_parquet(OUT / "global_candidate_predictions.parquet", index=False)
    ensemble.to_parquet(OUT / "ensemble_predictions.parquet", index=False)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()
                if p.is_file() and p.suffix != ".parquet" and p.name != "manifest.sha256.json"}
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.to_json(orient="records"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
