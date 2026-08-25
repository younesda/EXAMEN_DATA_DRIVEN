"""Ablations et sensibilité AIPW observationnelle du pricing avancé."""
from __future__ import annotations

import hashlib
import json
import time

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor

from src.config.settings import PROJECT_ROOT
from src.experiments.advanced_pricing import (
    FEATURE_CACHE, FEATURES, MAX_SECONDS_PER_MODEL, OUT, PROPENSITY_FEATURES,
    SEED, WINDOWS, matrix, score,
)

CHECKPOINTS = PROJECT_ROOT / "checkpoints/advanced_pricing_sensitivity"
LOG = PROJECT_ROOT / "logs/advanced_pricing_sensitivity.jsonl"

GROUPS = {
    "no_web": tuple(name for name in FEATURES if name.startswith(("views_", "carts_"))) + ("historical_view_to_cart_28",),
    "no_stock": ("stock_at_cutoff", "restock_frequency_84"),
    "no_promotion": tuple(name for name in FEATURES if name in {
        "remise_pct", "planned_paid_price_xof", "unit_margin_after_xof", "margin_rate_after",
        "discount_x_category", "discount_x_product", "product_discount_mean_before",
        "product_discount_n_before", "category_discount_mean_before", "category_discount_n_before",
        "product_campaign_active", "category_campaign_active", "category_concurrent_promotions",
        "past_campaign_exposure_90",
    }),
    "no_orders": tuple(name for name in FEATURES if name.startswith(("orders_", "clients_", "basket_", "segment_share_"))),
}


def kept(removed: tuple[str, ...]) -> list[str]:
    unknown = set(removed).difference(FEATURES)
    if unknown: raise ValueError(sorted(unknown))
    return [name for name in FEATURES if name not in removed]


def model() -> LGBMRegressor:
    return LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, num_leaves=15,
                         min_child_samples=80, learning_rate=.05, n_estimators=180,
                         subsample=.85, colsample_bytree=.85, reg_lambda=.2,
                         random_state=SEED, n_jobs=2, verbosity=-1)


def bootstrap_product(frame: pd.DataFrame, draws: int = 2000) -> dict:
    units = [group.tau.to_numpy() for _, group in frame.groupby("produit_key")]
    rng = np.random.default_rng(SEED); estimates = np.empty(draws)
    for draw in range(draws):
        chosen = rng.integers(0, len(units), len(units))
        estimates[draw] = np.concatenate([units[index] for index in chosen]).mean()
    return {"mean_quantity_uplift": float(frame.tau.mean()), "ci95_low": float(np.quantile(estimates, .025)),
            "ci95_high": float(np.quantile(estimates, .975)), "draws": draws,
            "unit": "produit", "n_products": int(frame.produit_key.nunique())}


def aipw(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    treatment = train.remise_pct.gt(0).astype(int).to_numpy()
    propensity = LGBMClassifier(n_estimators=160, learning_rate=.04, num_leaves=15, min_child_samples=120,
                               random_state=SEED, n_jobs=2, verbosity=-1)
    propensity.fit(matrix(train, PROPENSITY_FEATURES), treatment)
    e = np.clip(propensity.predict_proba(matrix(test, PROPENSITY_FEATURES))[:, 1], .02, .98)
    outcomes = []
    for value in (0, 1):
        fitted = model(); subset = train[treatment == value]
        fitted.fit(matrix(subset), subset.quantite)
        outcomes.append(np.maximum(0, fitted.predict(matrix(test))))
    t = test.remise_pct.gt(0).astype(int).to_numpy(); y = test.quantite.to_numpy(float)
    mu0, mu1 = outcomes
    tau = (mu1-mu0) + t*(y-mu1)/e - (1-t)*(y-mu0)/(1-e)
    output = test[["produit_key", "row_id"]].copy(); output["tau"] = tau
    audit = {"treatment": "any observed positive discount versus zero discount",
             "propensity_clipped_to": [.02, .98], "treated_rate": float(t.mean()),
             "claim": "observational sensitivity only; no causal interpretation"}
    return output, audit


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    d = pd.read_parquet(FEATURE_CACHE); d["ds"] = pd.to_datetime(d.ds); max_ds = d.ds.max()
    rows, sensitivity = [], []
    for window, back in enumerate(WINDOWS, 1):
        test_start = max_ds-pd.Timedelta(days=back-1); calibration_start = test_start-pd.Timedelta(days=60)
        fit = d[d.ds < calibration_start]; calibration = d[d.ds.between(calibration_start, test_start-pd.Timedelta(days=1))]
        test = d[d.ds.between(test_start, test_start+pd.Timedelta(days=59))]
        for variant, removed in GROUPS.items():
            checkpoint = CHECKPOINTS / f"window_{window}_{variant}.parquet"
            if checkpoint.exists(): output = pd.read_parquet(checkpoint)
            else:
                columns = kept(removed); start = time.perf_counter(); fitted = model()
                fitted.fit(matrix(fit, columns), fit.quantite)
                cal = np.maximum(0, fitted.predict(matrix(calibration, columns)))
                factor = float(calibration.quantite.mean()/max(cal.mean(),1e-9))
                output = test[["row_id", "quantite"]].copy()
                output["pred"] = np.maximum(0, fitted.predict(matrix(test, columns))*factor)
                output.to_parquet(checkpoint, index=False)
                with LOG.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"window": window, "variant": variant,
                                             "elapsed_seconds": time.perf_counter()-start,
                                             "within_time_budget": time.perf_counter()-start <= MAX_SECONDS_PER_MODEL})+"\n")
            rows.append({"window": window, "variant": variant, **score(output.quantite, output.pred)})
        aipw_checkpoint = CHECKPOINTS / f"window_{window}_aipw.parquet"
        if aipw_checkpoint.exists():
            tau = pd.read_parquet(aipw_checkpoint)
            audit = {"treatment": "any observed positive discount versus zero discount",
                     "propensity_clipped_to": [.02, .98],
                     "treated_rate": float(test.remise_pct.gt(0).mean()),
                     "claim": "observational sensitivity only; no causal interpretation",
                     "checkpoint_reused": True}
        else: tau, audit = aipw(fit, test); tau.to_parquet(aipw_checkpoint, index=False)
        sensitivity.append({"window": window, **audit, **bootstrap_product(tau)})
    frame = pd.DataFrame(rows)
    summary = frame.groupby("variant", as_index=False).agg(wape=("wape", "mean"), bias=("bias", "mean"),
                                                            std=("wape", "std"), n_windows=("window", "nunique"))
    reference = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    full_lgb = next(row for row in reference["summary"] if row["model"] == "LightGBM_enriched")
    payload = {"ablation_model": "LightGBM_enriched fixed configuration", "no_test_retuning": True,
               "reference_full": full_lgb, "removed_features": {k:list(v) for k,v in GROUPS.items()},
               "window_metrics": rows, "summary": summary.to_dict("records"),
               "aipw_observational_sensitivity": sensitivity,
               "causal_claim_allowed": False, "primary_population_filtered": False}
    (OUT / "sensitivity.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in OUT.iterdir()
                if path.is_file() and path.suffix != ".parquet" and path.name != "manifest.sha256.json"}
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"ablations": summary.to_dict("records"), "sensitivity": sensitivity}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
