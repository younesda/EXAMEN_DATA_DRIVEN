"""Backtest forecasting final à six fenêtres, checkpointé et sans fuite."""
from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.config.settings import PROJECT_ROOT

warnings.filterwarnings("ignore", module=r"statsmodels\..*")

DATA = PROJECT_ROOT / "data/processed/final/product_daily_forecasting.parquet"
OUT = PROJECT_ROOT / "models/forecasting"
REPORT = PROJECT_ROOT / "reports/final"
CHECKPOINTS = PROJECT_ROOT / "checkpoints/final_forecasting_6"
LAGS = (1, 7, 14, 28)
WINDOWS = (180, 150, 120, 90, 60, 30)
H = 30
SEED = 42
MODEL_NAMES = {
    "Naive", "SeasonalNaive7", "MovingAverage28", "AutoETS",
    "CrostonOptimized", "TSB", "LightGBM_Poisson", "LightGBM_Tweedie",
    "Hurdle_LightGBM",
}
CORE_MODELS = {
    "Naive", "SeasonalNaive7", "MovingAverage28", "CrostonOptimized",
    "LightGBM_Tweedie",
}


def features(d: pd.DataFrame, web: bool = True) -> pd.DataFrame:
    x = d.sort_values(["produit_key", "ds"]).copy()
    g = x.groupby("produit_key")
    for lag in LAGS:
        x[f"y_lag{lag}"] = g.y.shift(lag)
    x["y_ma28"] = g.y.transform(lambda z: z.shift(1).rolling(28, min_periods=7).mean())
    x["dow"] = x.ds.dt.dayofweek
    x["month"] = x.ds.dt.month
    x["weekend"] = (x.dow >= 5).astype(int)
    x["promo"] = x.remise_pct
    x["stock_cut"] = g.niveau_stock.shift(1)
    if web:
        x["views_lag1"] = g["view"].shift(1)
        x["cart_lag1"] = g.add_to_cart.shift(1)
        x["views_ma7"] = g["view"].transform(
            lambda z: z.shift(1).rolling(7, min_periods=1).mean()
        )
    return x


def design_cols(web: bool = True) -> list[str]:
    cols = [f"y_lag{lag}" for lag in LAGS] + [
        "y_ma28", "dow", "month", "weekend", "promo", "stock_cut"
    ]
    return cols + (["views_lag1", "cart_lag1", "views_ma7"] if web else [])


def recursive(model, hist, future, web: bool = True, hurdle=None) -> pd.DataFrame:
    h = hist[["produit_key", "ds", "y", "niveau_stock", "view", "add_to_cart", "remise_pct"]].copy()
    rows = []
    last = hist.sort_values("ds").groupby("produit_key").tail(1).set_index("produit_key")
    webstats = hist.groupby("produit_key").tail(7).groupby("produit_key").agg(
        views_lag1=("view", "last"), cart_lag1=("add_to_cart", "last"),
        views_ma7=("view", "mean"),
    )
    global_y = float(hist.y.mean()) if len(hist) else 0.0
    for ds in sorted(future.ds.unique()):
        block = future[future.ds.eq(ds)].copy()
        vals = []
        for product in block.produit_key:
            z = h[h.produit_key.eq(product)].sort_values("ds")
            history = z.y.to_numpy(float)
            fallback = float(history.mean()) if len(history) else global_y
            row = {
                f"y_lag{lag}": history[-lag] if len(history) >= lag else fallback
                for lag in LAGS
            }
            row.update(
                y_ma28=float(np.mean(history[-28:])) if len(history) else global_y,
                dow=pd.Timestamp(ds).dayofweek,
                month=pd.Timestamp(ds).month,
                weekend=int(pd.Timestamp(ds).dayofweek >= 5),
                promo=float(block.loc[block.produit_key.eq(product), "remise_pct"].iloc[0]),
                stock_cut=float(last.loc[product, "niveau_stock"]) if product in last.index else 0.0,
            )
            if web:
                row.update(webstats.loc[product].to_dict() if product in webstats.index else {
                    "views_lag1": 0.0, "cart_lag1": 0.0, "views_ma7": 0.0,
                })
            vals.append(row)
        X = pd.DataFrame(vals)[design_cols(web)].fillna(0)
        pred = np.maximum(0, model.predict(X))
        if hurdle is not None:
            pred *= hurdle.predict_proba(X)[:, 1]
        block["pred"] = pred
        rows.append(block[["produit_key", "ds", "y", "pred"]])
        h = pd.concat([h, pd.DataFrame({
            "produit_key": block.produit_key, "ds": ds, "y": pred,
            "niveau_stock": block.niveau_stock, "view": 0, "add_to_cart": 0,
            "remise_pct": block.remise_pct,
        })], ignore_index=True)
    return pd.concat(rows, ignore_index=True)


def _croston_level(y: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    nz = np.flatnonzero(y > 0)
    if not len(nz):
        return 0.0
    best = None
    for alpha in (.1, .2, .3, .5, .7):
        q = y[nz[0]]
        interval = max(nz[0] + 1, 1)
        fitted = np.zeros(len(y))
        last = nz[0]
        for idx in range(nz[0] + 1, len(y)):
            fitted[idx] = q / max(interval, 1)
            if y[idx] > 0:
                q = alpha * y[idx] + (1 - alpha) * q
                interval = alpha * (idx - last) + (1 - alpha) * interval
                last = idx
        loss = np.abs(fitted - y).mean()
        if best is None or loss < best[0]:
            best = (loss, q / max(interval, 1))
    return float(best[1])


def croston_predictions(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    global_mean = float(train.y.mean()) if len(train) else 0.0
    rows = []
    for product, te in test.groupby("produit_key"):
        y = train.loc[train.produit_key.eq(product)].sort_values("ds").y.to_numpy(float)
        level = _croston_level(y) if len(y) else global_mean
        z = te[["produit_key", "ds", "y"]].copy()
        z["pred"] = np.maximum(0, level)
        z["model"] = "CrostonOptimized"
        rows.append(z)
    return pd.concat(rows, ignore_index=True)


def base_predictions(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    out = []
    global_mean = float(train.y.mean()) if len(train) else 0.0
    for product, te in test.groupby("produit_key"):
        y = train.loc[train.produit_key.eq(product)].sort_values("ds").y.to_numpy(float)
        n = len(te)
        if not len(y):
            candidates = {
                "Naive": np.repeat(global_mean, n),
                "SeasonalNaive7": np.repeat(global_mean, n),
                "MovingAverage28": np.repeat(global_mean, n),
            }
        else:
            candidates = {
                "Naive": np.repeat(y[-1], n),
                "SeasonalNaive7": np.resize(y[-min(7, len(y)):], n),
                "MovingAverage28": np.repeat(y[-min(28, len(y)):].mean(), n),
            }
        for name, pred in candidates.items():
            z = te[["produit_key", "ds", "y"]].copy()
            z["pred"] = np.maximum(0, pred)
            z["model"] = name
            out.append(z)

    for product, te in test.groupby("produit_key"):
        y = train.loc[train.produit_key.eq(product)].sort_values("ds").y.to_numpy(float)
        n = len(te)
        if len(y) < 14:
            fallback = float(y.mean()) if len(y) else global_mean
            ep = cp = tp = np.repeat(max(0, fallback), n)
        else:
            try:
                candidates = [(.1, .05, .1), (.2, .1, .2), (.4, .1, .3)]
                split = max(28, len(y) - 28)
                scored = []
                for a, b, c in candidates:
                    fit = ExponentialSmoothing(
                        y[:split], trend="add", damped_trend=True, seasonal="add",
                        seasonal_periods=7, initialization_method="estimated",
                    ).fit(smoothing_level=a, smoothing_trend=b, smoothing_seasonal=c,
                          damping_trend=.98, optimized=False)
                    scored.append((np.mean(np.abs(fit.forecast(len(y) - split) - y[split:])), a, b, c))
                _, a, b, c = min(scored)
                ets = ExponentialSmoothing(
                    y, trend="add", damped_trend=True, seasonal="add",
                    seasonal_periods=7, initialization_method="estimated",
                ).fit(smoothing_level=a, smoothing_trend=b, smoothing_seasonal=c,
                      damping_trend=.98, optimized=False)
                ep = np.maximum(0, ets.forecast(n))
            except Exception:
                ep = np.resize(y[-min(7, len(y)):], n)
            cp = np.repeat(_croston_level(y), n)
            nz = np.flatnonzero(y > 0)
            if len(nz):
                best = None
                for a in (.1, .3, .5):
                    for b in (.1, .3, .5):
                        q = y[nz[0]]
                        prob = 1.0
                        fitted = []
                        for val in y:
                            fitted.append(q * prob)
                            occurrence = float(val > 0)
                            prob = b * occurrence + (1 - b) * prob
                            if occurrence:
                                q = a * val + (1 - a) * q
                        loss = np.mean(np.abs(np.asarray(fitted) - y))
                        if best is None or loss < best[0]:
                            best = (loss, q * prob)
                tp = np.repeat(best[1], n)
            else:
                tp = np.zeros(n)
        for name, pred in (("AutoETS", ep), ("CrostonOptimized", cp), ("TSB", tp)):
            z = te[["produit_key", "ds", "y"]].copy()
            z["pred"] = np.maximum(0, pred)
            z["model"] = name
            out.append(z)
    return pd.concat(out, ignore_index=True)


def metrics(z: pd.DataFrame, train: pd.DataFrame) -> dict[str, float]:
    error = z.pred - z.y
    denominator = z.y.sum()
    scale = train.groupby("produit_key").y.apply(
        lambda x: np.mean(np.diff(x.tail(180)) ** 2) if len(x) > 1 else 1
    ).replace(0, 1)
    scaled = z.assign(se=z.apply(
        lambda row: (row.pred - row.y) ** 2 / scale.get(row.produit_key, 1), axis=1
    ))
    result = {
        "wape_daily": float(np.abs(error).sum() / max(denominator, 1)),
        "bias": float(error.sum() / max(denominator, 1)),
        "rmsse": float(np.sqrt(scaled.se.mean())),
        "asym_cost": float(np.where(error < 0, -1.5 * error, error).sum() / max(denominator, 1)),
    }
    for horizon in (7, 14, 30):
        cumulative = (z.sort_values("ds").groupby("produit_key").head(horizon)
                      .groupby("produit_key")[["y", "pred"]].sum())
        result[f"wape_cum_{horizon}"] = float(
            (cumulative.pred - cumulative.y).abs().sum() / max(cumulative.y.sum(), 1)
        )
    return result


def _fit_ml_models(train: pd.DataFrame, test: pd.DataFrame) -> list[pd.DataFrame]:
    outputs = []
    for name, objective, web, hurdle in (
        ("LightGBM_Poisson", "poisson", False, False),
        ("LightGBM_Tweedie", "tweedie", True, False),
        ("Hurdle_LightGBM", "tweedie", True, True),
    ):
        training = features(train, web).dropna(subset=[f"y_lag{max(LAGS)}"])
        cols = design_cols(web)
        reg = LGBMRegressor(
            objective=objective, n_estimators=250, learning_rate=.05, num_leaves=31,
            min_child_samples=40, subsample=.85, colsample_bytree=.85,
            random_state=SEED, n_jobs=2, verbosity=-1,
        )
        if hurdle:
            classifier = LGBMClassifier(
                n_estimators=180, learning_rate=.05, num_leaves=31,
                random_state=SEED, n_jobs=2, verbosity=-1,
            )
            classifier.fit(training[cols].fillna(0), (training.y > 0).astype(int))
            reg.fit(training.loc[training.y > 0, cols].fillna(0), training.loc[training.y > 0, "y"])
        else:
            classifier = None
            reg.fit(training[cols].fillna(0), training.y)
        z = recursive(reg, train, test, web, classifier)
        z["model"] = name
        outputs.append(z)
    return outputs


def targeted_predictions(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """Extension courte : deux modèles décisionnels et trois baselines simples."""
    rows = []
    global_mean = float(train.y.mean()) if len(train) else 0.0
    for product, future in test.groupby("produit_key"):
        y = train.loc[train.produit_key.eq(product)].sort_values("ds").y.to_numpy(float)
        fallback = float(y.mean()) if len(y) else global_mean
        candidates = {
            "Naive": np.repeat(y[-1] if len(y) else fallback, len(future)),
            "SeasonalNaive7": np.resize(y[-min(7, len(y)):] if len(y) else [fallback], len(future)),
            "MovingAverage28": np.repeat(y[-min(28, len(y)):].mean() if len(y) else fallback, len(future)),
            "CrostonOptimized": np.repeat(_croston_level(y) if len(y) else fallback, len(future)),
        }
        for name, pred in candidates.items():
            z = future[["produit_key", "ds", "y"]].copy()
            z["pred"] = np.maximum(0, pred)
            z["model"] = name
            rows.append(z)
    training = features(train, True).dropna(subset=["y_lag28"])
    cols = design_cols(True)
    model = LGBMRegressor(
        objective="tweedie", n_estimators=250, learning_rate=.05, num_leaves=31,
        min_child_samples=40, subsample=.85, colsample_bytree=.85,
        random_state=SEED, n_jobs=2, verbosity=-1,
    )
    model.fit(training[cols].fillna(0), training.y)
    lightgbm = recursive(model, train, test, True)
    lightgbm["model"] = "LightGBM_Tweedie"
    rows.append(lightgbm)
    return pd.concat(rows, ignore_index=True)


def _complete_prediction_set(predictions: pd.DataFrame, test: pd.DataFrame) -> bool:
    if predictions.empty or not CORE_MODELS <= set(predictions.model.unique()):
        return False
    expected = len(test)
    return predictions[predictions.model.isin(CORE_MODELS)].groupby("model").size().eq(expected).all()


def conformal_quantile(residuals: np.ndarray, level: float) -> float:
    residuals = np.asarray(residuals, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    if not len(residuals):
        raise ValueError("La calibration conforme requiert des résidus antérieurs.")
    corrected = min(1.0, np.ceil((len(residuals) + 1) * level) / len(residuals))
    return float(np.quantile(np.abs(residuals), corrected, method="higher"))


def _segments(train: pd.DataFrame) -> pd.DataFrame:
    stats = train.groupby("produit_key").y.agg(["sum", "count", lambda x: int((x > 0).sum())])
    stats.columns = ["volume", "days", "nonzero_days"]
    stats = stats.sort_values("volume", ascending=False)
    total = max(float(stats.volume.sum()), 1.0)
    stats["share_before"] = stats.volume.cumsum().shift(fill_value=0) / total
    stats["abc_a"] = stats.share_before < .80
    stats["adi"] = stats.days / stats.nonzero_days.replace(0, np.nan)
    stats["intermittent"] = stats.adi.fillna(np.inf) > 1.32
    return stats[["abc_a", "intermittent"]]


def evaluate_intervals(predictions: pd.DataFrame, data: pd.DataFrame) -> tuple[list[dict], dict]:
    starts = {window: group.ds.min() for window, group in predictions.groupby("window")}
    first_start = min(starts.values())
    calibration_start = first_start - pd.Timedelta(days=H)
    calibration_train = data[data.ds < calibration_start]
    calibration_test = data[data.ds.between(calibration_start, first_start - pd.Timedelta(days=1))]
    prior = croston_predictions(calibration_train, calibration_test)
    prior["residual"] = prior.y - prior.pred
    rows = []
    checks = []
    for window in sorted(starts, key=starts.get):
        start = starts[window]
        current = predictions[
            predictions.window.eq(window) & predictions.model.eq("CrostonOptimized")
        ].copy()
        segment = _segments(data[data.ds < start])
        current = current.join(segment, on="produit_key")
        max_calibration_ds = prior.ds.max()
        if not max_calibration_ds < start:
            raise AssertionError("Fuite temporelle dans la calibration conforme.")
        for level in (.80, .95):
            q = conformal_quantile(prior.residual.to_numpy(), level)
            lower = np.maximum(0, current.pred.to_numpy() - q)
            upper = current.pred.to_numpy() + q
            covered = (current.y.to_numpy() >= lower) & (current.y.to_numpy() <= upper)
            for segment_name, mask in (
                ("global", np.ones(len(current), dtype=bool)),
                ("abc_a", current.abc_a.fillna(False).to_numpy(bool)),
                ("intermittent", current.intermittent.fillna(False).to_numpy(bool)),
            ):
                rows.append({
                    "window": int(window), "test_start": str(start.date()),
                    "level": level, "segment": segment_name,
                    "coverage": float(covered[mask].mean()),
                    "mean_width": float((upper[mask] - lower[mask]).mean()),
                    "n": int(mask.sum()), "quantile": q,
                    "calibration_max_ds": str(max_calibration_ds.date()),
                })
        checks.append(max_calibration_ds < start)
        addition = current[["produit_key", "ds", "y", "pred"]].copy()
        addition["residual"] = addition.y - addition.pred
        prior = pd.concat([prior, addition], ignore_index=True)
    frame = pd.DataFrame(rows)
    aggregate = (frame.groupby(["level", "segment"])
                 .apply(lambda z: pd.Series({
                     "coverage": np.average(z.coverage, weights=z.n),
                     "mean_width": np.average(z.mean_width, weights=z.n),
                     "n": int(z.n.sum()),
                 }), include_groups=False).reset_index())
    return rows, {
        "strictly_prior_for_every_window": bool(all(checks)),
        "calibration_initial_start": str(calibration_start.date()),
        "per_window": rows,
        "aggregate": aggregate.to_dict("records"),
    }


def _write_manifest(directory: Path) -> None:
    manifest_name = "manifest.sha256.json"
    manifest = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.iterdir()
        if path.is_file() and path.name != manifest_name and path.suffix != ".parquet"
    }
    (directory / manifest_name).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    data = pd.read_parquet(DATA)
    data["ds"] = pd.to_datetime(data.ds)
    max_ds = data.ds.max()
    legacy_path = OUT / "backtest_predictions.parquet"
    legacy = pd.read_parquet(legacy_path) if legacy_path.exists() else pd.DataFrame()
    if not legacy.empty:
        legacy["ds"] = pd.to_datetime(legacy.ds)

    result_rows = []
    prediction_parts = []
    reused = []
    computed = []
    for window, back in enumerate(WINDOWS, 1):
        start = max_ds - pd.Timedelta(days=back - 1)
        end = start + pd.Timedelta(days=H - 1)
        train = data[data.ds < start]
        test = data[data.ds.between(start, end)]
        checkpoint = CHECKPOINTS / f"back_{back}.parquet"
        if checkpoint.exists():
            predictions = pd.read_parquet(checkpoint)
            reused.append(back)
        else:
            reusable = legacy[legacy.ds.between(start, end)].drop(columns=["window"], errors="ignore")
            if _complete_prediction_set(reusable, test):
                predictions = reusable
                reused.append(back)
            else:
                predictions = targeted_predictions(train, test)
                computed.append(back)
            predictions.to_parquet(checkpoint, index=False)
        if not _complete_prediction_set(predictions, test):
            raise AssertionError(f"Checkpoint incomplet pour back={back}.")
        predictions = predictions.assign(window=window, back_days=back)
        prediction_parts.append(predictions)
        for model, group in predictions.groupby("model"):
            result_rows.append({
                "window": window, "back_days": back,
                "train_start": str(train.ds.min().date()),
                "train_end": str(train.ds.max().date()),
                "test_start": str(start.date()), "test_end": str(end.date()),
                "model": model, **metrics(group, train),
            })

    predictions = pd.concat(prediction_parts, ignore_index=True)
    results = pd.DataFrame(result_rows)
    summary_all = (results.groupby("model").agg(
        wape=("wape_daily", "mean"), std=("wape_daily", "std"),
        daily_wins=("wape_daily", lambda x: 0), bias=("bias", "mean"),
        wape30=("wape_cum_30", "mean"), n_windows=("window", "nunique"),
    ).reset_index())
    core_results = results[results.model.isin(CORE_MODELS)]
    winners = core_results.loc[core_results.groupby("window").wape_daily.idxmin(), "model"].value_counts()
    summary_all["daily_wins"] = summary_all.model.map(winners).fillna(0).astype(int)
    summary_all = summary_all.sort_values(["n_windows", "wape", "std"], ascending=[False, True, True])
    summary = summary_all[summary_all.n_windows.eq(len(WINDOWS))].copy()
    interval_rows, interval_summary = evaluate_intervals(predictions, data)

    finite = np.isfinite(predictions.pred.to_numpy())
    quality = {
        "nan_or_infinite_predictions": int((~finite).sum()),
        "negative_predictions": int((predictions.pred < 0).sum()),
        "cold_start_product_windows": int(sum(
            len(set(data[data.ds.between(
                max_ds - pd.Timedelta(days=back - 1),
                max_ds - pd.Timedelta(days=back - 1) + pd.Timedelta(days=H - 1),
            )].produit_key) - set(data[data.ds < max_ds - pd.Timedelta(days=back - 1)].produit_key))
            for back in WINDOWS
        )),
        "history_under_28_product_windows": int(sum(
            (data[data.ds < max_ds - pd.Timedelta(days=back - 1)]
             .groupby("produit_key").size() < 28).sum() for back in WINDOWS
        )),
        "cold_start_fallback": "moyenne globale du train",
        "insufficient_history_fallback": "moyenne disponible puis SeasonalNaive7",
    }
    if quality["nan_or_infinite_predictions"] or quality["negative_predictions"]:
        raise AssertionError(f"Prédictions invalides : {quality}")

    predictions.to_parquet(legacy_path, index=False)
    pd.DataFrame(interval_rows).to_parquet(OUT / "interval_evaluation.parquet", index=False)
    payload = {
        "decisions": {
            "daily": "CrostonOptimized",
            "planning_cumulative_30d": "LightGBM_Tweedie",
            "global_winner": None,
        },
        "window_policy": {
            "count": 6, "horizon_days": H, "back_days": list(WINDOWS),
            "initial_train_days": int((max_ds - pd.Timedelta(days=WINDOWS[0] - 1) - data.ds.min()).days),
            "reason_previous_three": "choix initial de coût sur les 90 derniers jours, non imposé par les données",
            "preexisting_back_days": [90, 60, 30],
            "additional_checkpointed_back_days": [180, 150, 120],
            "reused_back_days": reused, "computed_back_days": computed,
        },
        "windows": result_rows,
        "summary": summary.to_dict("records"),
        "legacy_three_window_challengers": summary_all[summary_all.n_windows.lt(len(WINDOWS))].to_dict("records"),
        "intervals": interval_summary,
        "quality": quality,
        "usage": "planification supervisée",
        "forbidden": "vainqueur global ou pilotage automatique",
    }
    (OUT / "metadata.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    training = features(data, True).dropna(subset=["y_lag28"])
    final = LGBMRegressor(
        objective="tweedie", n_estimators=250, learning_rate=.05, num_leaves=31,
        random_state=SEED, n_jobs=2, verbosity=-1,
    ).fit(training[design_cols(True)].fillna(0), training.y)
    joblib.dump(final, OUT / "lightgbm_tweedie.joblib")
    _write_manifest(OUT)

    interval_table = pd.DataFrame(interval_summary["aggregate"])
    lines = [
        "# 02 — Forecasting final", "",
        "Deux décisions séparées, sans vainqueur global :", "",
        "- **Prévision quotidienne : `CrostonOptimized`.**",
        "- **Planification cumulée à 30 jours : `LightGBM_Tweedie`.**", "",
        summary.to_markdown(index=False), "",
        "## Fenêtres", "",
        "Six fenêtres non chevauchantes de 30 jours sont évaluées. Les 546 jours disponibles laissent 366 jours avant la première fenêtre. Les trois fenêtres précédentes étaient un compromis de coût sur les 90 derniers jours; elles ont été réutilisées par checkpoint et seules les trois fenêtres supplémentaires ont été calculées.", "",
        "## Intervalles conformes de CrostonOptimized", "",
        interval_table.to_markdown(index=False), "",
        "Chaque quantile utilise exclusivement un bloc de calibration ou des fenêtres strictement antérieurs à la fenêtre évaluée. Les bornes inférieures sont tronquées à zéro.", "",
        "## Garde-fous", "",
        f"- NaN ou infinis : {quality['nan_or_infinite_predictions']}.",
        f"- Prédictions négatives : {quality['negative_predictions']}.",
        f"- Cold-start observés : {quality['cold_start_product_windows']}; repli défini : moyenne globale du train.",
        f"- Historiques de moins de 28 jours observés : {quality['history_under_28_product_windows']}; repli défini : moyenne disponible puis SeasonalNaive7.", "",
        "Commande : `python -m src.pipelines.final_forecasting`.",
    ]
    (REPORT / "02_forecasting.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decisions": payload["decisions"], "computed": computed, "reused": reused}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
