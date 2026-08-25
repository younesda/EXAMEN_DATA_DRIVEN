"""Ablations ciblées du LightGBM global, sans retuning sur les fenêtres test."""
from __future__ import annotations

import gc
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
from lightgbm import LGBMRegressor

from src.config.settings import PROJECT_ROOT
from src.experiments.advanced_forecasting import FEATURE_CACHE, SEED, WINDOWS
from src.experiments.advanced_forecasting_candidates import FEATURES, metrics, stacked_window

OUT = PROJECT_ROOT / "models/advanced/forecasting"
CHECKPOINTS = PROJECT_ROOT / "checkpoints/advanced_forecasting_ablations"
LOG = PROJECT_ROOT / "logs/advanced_forecasting_ablations.jsonl"
MAX_SECONDS_PER_MODEL = 300

FEATURE_GROUPS = {
    "no_web": tuple(name for name in FEATURES if name.startswith(("views_", "cart_")))
    + ("view_to_cart_28",),
    "no_stock": ("stock_at_cutoff", "days_since_restock", "restock_frequency_84"),
    "no_promotion": ("planned_discount",),
}


def kept_feature_indices(removed: tuple[str, ...]) -> list[int]:
    """Indices stables des variables conservées dans la matrice numpy empilée."""
    unknown = set(removed).difference(FEATURES)
    if unknown:
        raise ValueError(f"Unknown ablation features: {sorted(unknown)}")
    return [index for index, name in enumerate(FEATURES) if name not in removed]


def _model() -> LGBMRegressor:
    return LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.3, n_estimators=260,
        learning_rate=.035, num_leaves=31, min_child_samples=100,
        subsample=.85, colsample_bytree=.8, random_state=SEED,
        n_jobs=2, verbosity=-1,
    )


def _log(**payload) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": pd.Timestamp.utcnow().isoformat(), **payload}
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    features = pd.read_parquet(FEATURE_CACHE)
    features["ds"] = pd.to_datetime(features.ds)
    max_ds = features.ds.max()
    rows: list[dict] = []
    predictions: list[pd.DataFrame] = []

    for window, back in enumerate(WINDOWS, 1):
        test_start = max_ds - pd.Timedelta(days=back - 1)
        X_train, y_train, X_test, identity = stacked_window(features, test_start)
        for variant, removed in FEATURE_GROUPS.items():
            checkpoint = CHECKPOINTS / f"window_{window}_{variant}.parquet"
            if checkpoint.exists():
                output = pd.read_parquet(checkpoint)
            else:
                indices = kept_feature_indices(removed)
                start = time.perf_counter()
                model = _model()
                model.fit(X_train[:, indices], y_train)
                elapsed = time.perf_counter() - start
                output = identity.copy()
                output["pred"] = np.maximum(0, model.predict(X_test[:, indices]))
                output["window"] = window
                output["variant"] = variant
                output.to_parquet(checkpoint, index=False)
                _log(event="ablation_complete", window=window, variant=variant,
                     removed=list(removed), elapsed_seconds=elapsed,
                     rss_mb=psutil.Process().memory_info().rss / 2**20,
                     within_time_budget=elapsed <= MAX_SECONDS_PER_MODEL)
            rows.append({"window": window, "variant": variant, **metrics(output)})
            predictions.append(output)
        del X_train, y_train, X_test
        gc.collect()

    frame = pd.DataFrame(rows)
    summary = (frame.groupby("variant", as_index=False)
               .agg(wape_daily=("wape_daily", "mean"),
                    wape_cum_7=("wape_cum_7", "mean"),
                    wape_cum_30=("wape_cum_30", "mean"),
                    bias=("bias", "mean"), n_windows=("window", "nunique")))
    full = json.loads((OUT / "candidate_comparison.json").read_text(encoding="utf-8"))
    full_summary = next(item for item in full["summary"] if item["model"] == "LightGBM_global_tweedie")
    payload = {
        "design": "one feature family removed; same fixed model, train origins, and six outer windows",
        "no_retuning_on_test": True,
        "reference": full_summary,
        "removed_features": {key: list(value) for key, value in FEATURE_GROUPS.items()},
        "window_metrics": rows,
        "summary": summary.to_dict("records"),
        "resource_policy": {"sequential": True, "max_seconds_per_model": MAX_SECONDS_PER_MODEL},
    }
    (OUT / "ablations.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.concat(predictions, ignore_index=True).to_parquet(OUT / "ablation_predictions.parquet", index=False)
    manifest = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in OUT.iterdir()
        if path.is_file() and path.suffix != ".parquet" and path.name != "manifest.sha256.json"
    }
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.to_json(orient="records"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
