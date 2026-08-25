"""Forecasting direct multi-horizons, isolé des artefacts validés.

Chaque prévision J+h est produite par un modèle distinct depuis un unique
cutoff. La cible de test, le stock futur et les événements web contemporains
ne sont jamais présents dans les features. Le tuning utilise un pseudo-cutoff
strictement antérieur à la fenêtre externe.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psutil
from lightgbm import LGBMRegressor

from src.config.settings import PROJECT_ROOT
from src.data.extract import load_cached

DATA = PROJECT_ROOT / "data/processed/final/product_daily_forecasting.parquet"
REFERENCE = PROJECT_ROOT / "models/forecasting/metadata.json"
OUT = PROJECT_ROOT / "models/advanced/forecasting"
CHECKPOINTS = PROJECT_ROOT / "checkpoints/advanced_forecasting"
LOG = PROJECT_ROOT / "logs/advanced_forecasting.jsonl"
FEATURE_CACHE = PROJECT_ROOT / "data/cache/advanced_forecasting_features.parquet"
WINDOWS = (180, 150, 120, 90, 60, 30)
HORIZONS = tuple(range(1, 31))
SEED = 42
MAX_SECONDS_PER_MODEL = 180
LAGS = (1, 2, 3, 7, 14, 21, 28, 35, 56, 84, 364)
ROLLS = (7, 14, 28, 56, 84)
TUNING_HORIZONS = (1, 7, 14, 30)
PARAM_GRID = (
    {"num_leaves": 15, "min_child_samples": 60, "learning_rate": .05, "n_estimators": 160},
    {"num_leaves": 31, "min_child_samples": 80, "learning_rate": .035, "n_estimators": 220},
    {"num_leaves": 47, "min_child_samples": 120, "learning_rate": .03, "n_estimators": 240},
)


def _log(event: str, **payload) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": pd.Timestamp.utcnow().isoformat(), "event": event, **payload}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _days_since_positive(values: pd.Series) -> pd.Series:
    last = -10**6
    result = np.empty(len(values), dtype=np.int32)
    for idx, value in enumerate(values.to_numpy()):
        if value > 0:
            last = idx
        result[idx] = idx - last if last > -10**6 else idx + 1
    return pd.Series(result, index=values.index)


def build_feature_table(data: pd.DataFrame) -> pd.DataFrame:
    """Features disponibles au cutoff; aucune cible future n'est construite ici."""
    d = data.sort_values(["produit_key", "ds"]).copy()
    d["ds"] = pd.to_datetime(d.ds)
    products = load_cached("dim_produit")[["produit_key", "valid_from"]].drop_duplicates("produit_key")
    products["valid_from"] = pd.to_datetime(products.valid_from)
    d = d.merge(products, on="produit_key", how="left")
    group = d.groupby("produit_key", sort=False)

    # La ligne représente le cutoff en fin de journée : lag1 = dernière vente connue.
    for lag in LAGS:
        d[f"sales_lag_{lag}"] = group.y.shift(lag - 1)
    for window in ROLLS:
        rolling = group.y.rolling(window, min_periods=max(3, window // 4))
        d[f"sales_mean_{window}"] = rolling.mean().reset_index(level=0, drop=True)
        d[f"sales_median_{window}"] = rolling.median().reset_index(level=0, drop=True)
        d[f"sales_std_{window}"] = rolling.std().reset_index(level=0, drop=True)
        d[f"sales_min_{window}"] = rolling.min().reset_index(level=0, drop=True)
        d[f"sales_max_{window}"] = rolling.max().reset_index(level=0, drop=True)
        d[f"sales_zero_rate_{window}"] = rolling.apply(lambda x: np.mean(x == 0), raw=True).reset_index(level=0, drop=True)

    d["sales_cumulative"] = group.y.cumsum()
    d["active_days_cumulative"] = group.y.transform(lambda x: (x > 0).cumsum())
    d["observed_days"] = group.cumcount() + 1
    d["adi"] = d.observed_days / d.active_days_cumulative.replace(0, np.nan)
    mean84 = d["sales_mean_84"].replace(0, np.nan)
    d["cv2_84"] = (d["sales_std_84"] / mean84) ** 2
    d["intermittent"] = (d.adi > 1.32).astype("int8")
    d["abc_share_before"] = d.groupby("ds").sales_cumulative.transform(
        lambda x: x.rank(method="first", ascending=False).sub(1).div(max(len(x), 1))
    )
    d["abc_a"] = (d.abc_share_before < .2).astype("int8")

    for lag in (1, 3, 7, 14, 28):
        d[f"views_lag_{lag}"] = group["view"].shift(lag - 1)
        d[f"cart_lag_{lag}"] = group.add_to_cart.shift(lag - 1)
    views28 = group["view"].rolling(28, min_periods=7).sum().reset_index(level=0, drop=True)
    carts28 = group.add_to_cart.rolling(28, min_periods=7).sum().reset_index(level=0, drop=True)
    d["view_to_cart_28"] = carts28 / views28.replace(0, np.nan)
    d["views_trend_7_28"] = (
        group["view"].rolling(7, min_periods=3).mean().reset_index(level=0, drop=True)
        - group["view"].rolling(28, min_periods=7).mean().reset_index(level=0, drop=True)
    )

    d["stock_at_cutoff"] = d.niveau_stock
    d["days_since_restock"] = group.quantite_reapprovisionnee.apply(_days_since_positive).reset_index(level=0, drop=True)
    d["restock_frequency_84"] = group.quantite_reapprovisionnee.transform(
        lambda x: (x > 0).rolling(84, min_periods=14).mean()
    )
    d["version_age_days"] = (d.ds - d.valid_from).dt.days.clip(lower=0)

    for column, output in (("produit_key", "product_code"), ("categorie", "category_code"), ("marque", "brand_code")):
        d[output] = pd.Categorical(d[column]).codes.astype("int16")

    # Statistiques hiérarchiques connues au cutoff.
    for key, prefix in (("categorie", "category"), ("marque", "brand")):
        daily = d.groupby([key, "ds"], as_index=False).y.sum().sort_values([key, "ds"])
        daily[f"{prefix}_mean_28"] = daily.groupby(key).y.transform(
            lambda x: x.rolling(28, min_periods=7).mean()
        )
        daily[f"{prefix}_cumulative_mean"] = daily.groupby(key).y.transform(lambda x: x.expanding().mean())
        d = d.merge(daily[[key, "ds", f"{prefix}_mean_28", f"{prefix}_cumulative_mean"]], on=[key, "ds"], how="left")

    d["cutoff_dow"] = d.ds.dt.dayofweek.astype("int8")
    d["cutoff_month"] = d.ds.dt.month.astype("int8")
    return d


BASE_FEATURES = (
    [f"sales_lag_{lag}" for lag in LAGS]
    + [f"sales_{stat}_{window}" for window in ROLLS for stat in ("mean", "median", "std", "min", "max", "zero_rate")]
    + ["sales_cumulative", "active_days_cumulative", "observed_days", "adi", "cv2_84", "intermittent", "abc_a"]
    + [f"views_lag_{lag}" for lag in (1, 3, 7, 14, 28)]
    + [f"cart_lag_{lag}" for lag in (1, 3, 7, 14, 28)]
    + ["view_to_cart_28", "views_trend_7_28", "stock_at_cutoff", "days_since_restock", "restock_frequency_84"]
    + ["prix_base_xof", "cout_xof", "version_age_days", "product_code", "category_code", "brand_code"]
    + ["category_mean_28", "category_cumulative_mean", "brand_mean_28", "brand_cumulative_mean"]
    + ["target_dow", "target_weekend", "target_month", "target_week", "target_month_start", "target_month_end", "planned_discount"]
)


def horizon_frame(features: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Associe features au cutoff et cible J+h; promo future supposée planifiée."""
    d = features.copy()
    group = d.groupby("produit_key", sort=False)
    d["target"] = group.y.shift(-horizon)
    d["target_ds"] = d.ds + pd.Timedelta(days=horizon)
    target_date = d.target_ds
    d["target_dow"] = target_date.dt.dayofweek.astype("int8")
    d["target_weekend"] = (d.target_dow >= 5).astype("int8")
    d["target_month"] = target_date.dt.month.astype("int8")
    d["target_week"] = target_date.dt.isocalendar().week.astype("int16")
    d["target_month_start"] = target_date.dt.is_month_start.astype("int8")
    d["target_month_end"] = target_date.dt.is_month_end.astype("int8")
    # Hypothèse métier : le calendrier promotionnel est gelé au cutoff.
    d["planned_discount"] = group.remise_pct.shift(-horizon)
    return d


def _model(params: dict) -> LGBMRegressor:
    return LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.3,
        subsample=.85, colsample_bytree=.8, reg_lambda=.2,
        random_state=SEED, n_jobs=2, verbosity=-1, **params,
    )


def _fit_predict(frame: pd.DataFrame, train_target_end: pd.Timestamp,
                 origin: pd.Timestamp, params: dict) -> tuple[np.ndarray, np.ndarray, float]:
    train = frame[(frame.target_ds <= train_target_end) & frame.target.notna()]
    test = frame[frame.ds.eq(origin)]
    X_train = train[BASE_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0)
    X_test = test[BASE_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0)
    start = time.perf_counter()
    model = _model(params)
    model.fit(X_train, train.target)
    elapsed = time.perf_counter() - start
    prediction = np.maximum(0, model.predict(X_test))
    return prediction, test.target.to_numpy(float), elapsed


def tune_on_previous_window(features: pd.DataFrame, external_start: pd.Timestamp) -> tuple[dict, list[dict]]:
    validation_origin = external_start - pd.Timedelta(days=31)
    scores = []
    for param_id, params in enumerate(PARAM_GRID):
        actual_parts, pred_parts = [], []
        elapsed_total = 0.0
        for horizon in TUNING_HORIZONS:
            frame = horizon_frame(features, horizon)
            pred, actual, elapsed = _fit_predict(frame, validation_origin, validation_origin, params)
            actual_parts.append(actual)
            pred_parts.append(pred)
            elapsed_total += elapsed
        actual = np.concatenate(actual_parts)
        pred = np.concatenate(pred_parts)
        wape = float(np.abs(pred - actual).sum() / max(actual.sum(), 1))
        scores.append({"param_id": param_id, "params": params, "wape": wape, "elapsed_seconds": elapsed_total})
    best = min(scores, key=lambda row: row["wape"])
    return best["params"], scores


def _metrics(predictions: pd.DataFrame) -> dict:
    error = predictions.pred - predictions.y
    daily_wape = float(np.abs(error).sum() / max(predictions.y.sum(), 1))
    bias = float(error.sum() / max(predictions.y.sum(), 1))
    by_product = predictions.groupby("produit_key")[["y", "pred"]].sum()
    wape30 = float((by_product.pred - by_product.y).abs().sum() / max(by_product.y.sum(), 1))
    first7 = predictions[predictions.horizon <= 7].groupby("produit_key")[["y", "pred"]].sum()
    wape7 = float((first7.pred - first7.y).abs().sum() / max(first7.y.sum(), 1))
    return {"wape_daily": daily_wape, "wape_cum_7": wape7, "wape_cum_30": wape30, "bias": bias}


def _reference_snapshot() -> dict:
    raw = REFERENCE.read_bytes()
    metadata = json.loads(raw)
    return {
        "path": str(REFERENCE.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "decisions": metadata["decisions"],
        "summary": metadata["summary"],
        "windows": metadata["windows"],
    }


def paired_bootstrap_forecast(direct: pd.DataFrame, reference: pd.DataFrame,
                              model: str, cumulative: bool, draws: int = 3000) -> dict:
    ref = reference[reference.model.eq(model)][["window", "produit_key", "ds", "y", "pred"]].rename(columns={"pred": "ref_pred"})
    paired = direct.merge(ref, on=["window", "produit_key", "ds", "y"], how="inner", validate="one_to_one")
    if len(paired) != len(direct):
        raise AssertionError(f"Périmètre incomplet pour le bootstrap {model}: {len(paired)}/{len(direct)}")
    if cumulative:
        units = paired.groupby(["window", "produit_key"], as_index=False).agg(
            y=("y", "sum"), direct=("pred", "sum"), reference=("ref_pred", "sum"))
        units["direct_error"] = (units.direct - units.y).abs()
        units["reference_error"] = (units.reference - units.y).abs()
    else:
        units = paired.groupby(["window", "produit_key"], as_index=False).agg(
            y=("y", "sum"), direct_error=("pred", lambda x: 0.0),
            reference_error=("ref_pred", lambda x: 0.0))
        direct_error = paired.assign(e=(paired.pred - paired.y).abs()).groupby(["window", "produit_key"]).e.sum()
        ref_error = paired.assign(e=(paired.ref_pred - paired.y).abs()).groupby(["window", "produit_key"]).e.sum()
        units["direct_error"] = direct_error.to_numpy()
        units["reference_error"] = ref_error.to_numpy()
    rng = np.random.default_rng(SEED)
    samples = np.empty(draws)
    n = len(units)
    for idx in range(draws):
        draw = units.iloc[rng.integers(0, n, n)]
        denominator = max(draw.y.sum(), 1)
        samples[idx] = (draw.direct_error.sum() - draw.reference_error.sum()) / denominator
    observed = float((units.direct_error.sum() - units.reference_error.sum()) / max(units.y.sum(), 1))
    return {"reference_model": model, "unit": "produit_fenetre", "draws": draws,
            "wape_difference": observed, "ci95_low": float(np.quantile(samples, .025)),
            "ci95_high": float(np.quantile(samples, .975)), "n_units": n}


def direct_conformal_intervals(predictions: pd.DataFrame, features: pd.DataFrame) -> dict:
    """Conformal mondrien horizon×ABC×intermittence, passé uniquement."""
    labelled_parts = []
    for window in range(1, 7):
        part = predictions[predictions.window.eq(window)].copy()
        origin = pd.Timestamp(part.origin.iloc[0])
        origin_features = features[features.ds.eq(origin)][["produit_key", "sales_cumulative", "intermittent"]].copy()
        ranked = origin_features.sort_values("sales_cumulative", ascending=False)
        ranked["share_before"] = ranked.sales_cumulative.cumsum().shift(fill_value=0) / max(ranked.sales_cumulative.sum(), 1)
        ranked["abc_a"] = ranked.share_before < .80
        part = part.merge(ranked[["produit_key", "abc_a", "intermittent"]], on="produit_key", how="left")
        labelled_parts.append(part)
    labelled = pd.concat(labelled_parts, ignore_index=True)
    rows = []
    for window in range(2, 7):
        current = labelled[labelled.window.eq(window)].copy()
        previous = labelled[labelled.window.lt(window)].copy()
        for level in (.80, .95):
            lower_parts, upper_parts = [], []
            for (horizon, abc_a, intermittent), group in current.groupby(["horizon", "abc_a", "intermittent"], sort=True):
                calibration = previous[
                    previous.horizon.eq(horizon) & previous.abc_a.eq(abc_a)
                    & previous.intermittent.eq(intermittent)
                ]
                if len(calibration) < 30:
                    calibration = previous[previous.horizon.eq(horizon)]
                residuals = (calibration.y - calibration.pred).abs().to_numpy()
                corrected = min(1.0, np.ceil((len(residuals) + 1) * level) / len(residuals))
                quantile = float(np.quantile(residuals, corrected, method="higher"))
                lower_parts.append(pd.Series(np.maximum(0, group.pred.to_numpy() - quantile), index=group.index))
                upper_parts.append(pd.Series(group.pred.to_numpy() + quantile, index=group.index))
            lower = pd.concat(lower_parts).sort_index()
            upper = pd.concat(upper_parts).sort_index()
            covered = current.y.between(lower, upper)
            for segment, mask in (("global", pd.Series(True, index=current.index)),
                                  ("abc_a", current.abc_a.fillna(False)),
                                  ("intermittent", current.intermittent.fillna(False).astype(bool))):
                rows.append({"window": window, "level": level, "segment": segment,
                             "coverage": float(covered[mask].mean()),
                             "mean_width": float((upper[mask] - lower[mask]).mean()),
                             "n": int(mask.sum()), "calibration_windows": list(range(1, window))})
    frame = pd.DataFrame(rows)
    aggregate = (frame.groupby(["level", "segment"])
                 .apply(lambda z: pd.Series({"coverage": np.average(z.coverage, weights=z.n),
                                             "mean_width": np.average(z.mean_width, weights=z.n),
                                             "n": int(z.n.sum())}), include_groups=False)
                 .reset_index())
    return {"method": "mondrian_horizon_abc_intermittence", "first_window_evaluated": 2, "strictly_previous_windows_only": True,
            "per_window": rows, "aggregate": aggregate.to_dict("records")}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    reference = _reference_snapshot()
    if FEATURE_CACHE.exists():
        features = pd.read_parquet(FEATURE_CACHE)
        features["ds"] = pd.to_datetime(features.ds)
    else:
        data = pd.read_parquet(DATA)
        features = build_feature_table(data)
        FEATURE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        features.to_parquet(FEATURE_CACHE, index=False)
    max_ds = features.ds.max()
    all_predictions, tuning_records, window_metrics = [], [], []

    for window, back in enumerate(WINDOWS, 1):
        test_start = max_ds - pd.Timedelta(days=back - 1)
        origin = test_start - pd.Timedelta(days=1)
        params_path = CHECKPOINTS / f"window_{window}_params.json"
        if params_path.exists():
            params = json.loads(params_path.read_text(encoding="utf-8"))["params"]
        else:
            params, tuning = tune_on_previous_window(features, test_start)
            params_path.write_text(json.dumps({"params": params, "tuning": tuning}, indent=2), encoding="utf-8")
            tuning_records.extend({"window": window, **row} for row in tuning)

        window_parts = []
        for horizon in HORIZONS:
            checkpoint = CHECKPOINTS / f"window_{window}_h{horizon:02d}.parquet"
            if checkpoint.exists():
                part = pd.read_parquet(checkpoint)
            else:
                frame = horizon_frame(features, horizon)
                train_end = test_start - pd.Timedelta(days=1)
                pred, actual, elapsed = _fit_predict(frame, train_end, origin, params)
                rows = frame[frame.ds.eq(origin)][["produit_key", "target_ds"]].copy()
                rows = rows.rename(columns={"target_ds": "ds"})
                rows["horizon"] = horizon
                rows["y"] = actual
                rows["pred"] = pred
                rows["window"] = window
                rows["test_start"] = test_start
                rows["origin"] = origin
                rows["elapsed_seconds"] = elapsed
                rows["peak_rss_mb"] = psutil.Process().memory_info().rss / 2**20
                rows.to_parquet(checkpoint, index=False)
                part = rows
                _log("model_complete", window=window, horizon=horizon, elapsed_seconds=elapsed,
                     success=True, fallback=None, peak_rss_mb=float(rows.peak_rss_mb.iloc[0]))
                if elapsed > MAX_SECONDS_PER_MODEL:
                    _log("model_timeout_budget_exceeded", window=window, horizon=horizon,
                         elapsed_seconds=elapsed, configured_limit=MAX_SECONDS_PER_MODEL)
            window_parts.append(part)
        window_prediction = pd.concat(window_parts, ignore_index=True)
        metrics = _metrics(window_prediction)
        metrics.update(window=window, test_start=str(test_start.date()), params=params)
        window_metrics.append(metrics)
        all_predictions.append(window_prediction)

    predictions = pd.concat(all_predictions, ignore_index=True)
    if not np.isfinite(predictions.pred).all() or predictions.pred.lt(0).any():
        raise AssertionError("Prédiction directe non finie ou négative.")
    predictions.to_parquet(OUT / "direct_lightgbm_predictions.parquet", index=False)
    summary = {
        key: float(np.mean([row[key] for row in window_metrics]))
        for key in ("wape_daily", "wape_cum_7", "wape_cum_30", "bias")
    }
    reference_predictions = pd.read_parquet(PROJECT_ROOT / "models/forecasting/backtest_predictions.parquet")
    bootstrap = {
        "daily_vs_croston": paired_bootstrap_forecast(predictions, reference_predictions, "CrostonOptimized", False),
        "cumulative_30d_vs_validated_lightgbm": paired_bootstrap_forecast(predictions, reference_predictions, "LightGBM_Tweedie", True),
    }
    intervals = direct_conformal_intervals(predictions, features)
    reference_windows = pd.DataFrame(reference["summary"])
    ref_daily = float(reference_windows.loc[reference_windows.model.eq("CrostonOptimized"), "wape"].iloc[0])
    ref_30 = float(reference_windows.loc[reference_windows.model.eq("LightGBM_Tweedie"), "wape30"].iloc[0])
    outer = pd.DataFrame(window_metrics)
    detailed_reference = pd.DataFrame(reference["windows"])
    croston_windows = detailed_reference[detailed_reference.model.eq("CrostonOptimized")].set_index("window")
    lightgbm_windows = detailed_reference[detailed_reference.model.eq("LightGBM_Tweedie")].set_index("window")
    metadata = {
        "status": "challenger_pending_comparison",
        "model": "LightGBM_direct_per_horizon",
        "reference": reference,
        "window_metrics": window_metrics,
        "summary": summary,
        "comparison": {
            "daily_relative_gain_vs_croston": (ref_daily - summary["wape_daily"]) / ref_daily,
            "cumulative_30d_relative_gain_vs_validated_lightgbm": (ref_30 - summary["wape_cum_30"]) / ref_30,
            "daily_windows_won_vs_croston": int(sum(
                row.wape_daily < croston_windows.loc[row.window, "wape_daily"] for row in outer.itertuples())),
            "cumulative_30d_windows_won_vs_validated_lightgbm": int(sum(
                row.wape_cum_30 < lightgbm_windows.loc[row.window, "wape_cum_30"] for row in outer.itertuples())),
        },
        "bootstrap": bootstrap,
        "intervals": intervals,
        "methodology": {
            "direct_non_recursive": True, "horizons": list(HORIZONS),
            "outer_windows": 6, "nested_tuning": True,
            "tuning_horizons": list(TUNING_HORIZONS),
            "test_used_for_tuning": False, "future_stock_used": False,
            "contemporary_purchase_web_used": False,
            "promotion_assumption": "calendrier de remise planifiée connu et gelé au cutoff",
            "max_seconds_per_model": MAX_SECONDS_PER_MODEL,
        },
        "quality": {
            "nan_or_infinite": int((~np.isfinite(predictions.pred)).sum()),
            "negative": int(predictions.pred.lt(0).sum()),
            "rows": len(predictions),
        },
        "tuning_records": tuning_records,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    # Un seul modèle reproductible pour le dernier cutoff/horizon 30.
    final_frame = horizon_frame(features, 30)
    final_train = final_frame[final_frame.target.notna()]
    final_model = _model(window_metrics[-1]["params"])
    final_model.fit(final_train[BASE_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0), final_train.target)
    importance = pd.DataFrame({"feature": BASE_FEATURES, "gain": final_model.booster_.feature_importance(importance_type="gain")})
    importance["share"] = importance.gain / max(importance.gain.sum(), 1)
    metadata["feature_importance_h30"] = importance.sort_values("gain", ascending=False).head(40).to_dict("records")
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    joblib.dump({"model": final_model, "features": BASE_FEATURES, "horizon": 30}, OUT / "lightgbm_direct_h30.joblib")
    manifest = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in OUT.iterdir() if path.is_file() and path.suffix != ".parquet" and path.name != "manifest.sha256.json"
    }
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"model": metadata["model"], "summary": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
