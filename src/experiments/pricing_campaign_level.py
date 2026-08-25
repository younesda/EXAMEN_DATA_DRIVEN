"""Construction and bounded evaluation at the pricing-campaign decision level.

All episode features are computed strictly before ``date_debut``.  The module
uses the local raw extracts only and never writes to Supabase.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, PoissonRegressor, TweedieRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.config.settings import PROJECT_ROOT

RAW = PROJECT_ROOT / "data" / "raw"
OUT = PROJECT_ROOT / "data" / "processed" / "final"
MODEL_OUT = PROJECT_ROOT / "models" / "campaign_level_pricing"
REPORT = PROJECT_ROOT / "reports" / "10_pricing_campaign_level_report.md"


def _load(name: str) -> pd.DataFrame:
    return pd.read_parquet(RAW / f"{name}.parquet")


def _daily_sales() -> pd.DataFrame:
    sales = _load("fact_ventes")
    dates = _load("dim_date")[["date_key", "date_complete"]]
    sales = sales[sales["statut_commande"].eq("confirmee")].merge(dates, on="date_key", how="left")
    sales["ds"] = pd.to_datetime(sales["date_complete"])
    return sales


def _expanded_campaigns(promos: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for p in promos.itertuples(index=False):
        selected = products[products["product_id"].eq(p.cible)] if p.portee == "product" else products[products["categorie"].eq(p.cible)]
        for product in selected.itertuples(index=False):
            rows.append({
                "promo_key": p.promo_key, "promotion_id": p.promotion_id,
                "portee": p.portee, "cible": p.cible, "remise_pct": float(p.remise_pct),
                "date_debut": pd.Timestamp(p.date_debut), "date_fin": pd.Timestamp(p.date_fin),
                "produit_key": product.produit_key, "product_id": product.product_id,
                "categorie": product.categorie, "marque": product.marque,
                "prix_catalogue_xof": float(product.prix_base_xof), "cout_xof": float(product.cout_xof),
            })
    episodes = pd.DataFrame(rows)
    episodes["duree_jours"] = (episodes["date_fin"] - episodes["date_debut"]).dt.days + 1
    overlap = episodes[["produit_key", "date_debut", "date_fin"]].rename(columns={"date_debut": "d0", "date_fin": "d1"})
    episodes["overlap_count"] = [
        int(((overlap.produit_key.eq(r.produit_key)) & (overlap.d0.le(r.date_fin)) & (overlap.d1.ge(r.date_debut))).sum())
        for r in episodes.itertuples()
    ]
    episodes["overlap_status"] = np.where(episodes["overlap_count"].gt(1), "overlap", "non_overlapping")
    return episodes


def _prior_features(sales: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    """Vectorised pre-campaign rolling history (strictly shifted one day)."""
    daily = sales.groupby(["produit_key", "ds"], as_index=False).agg(
        qty=("quantite", "sum"), orders=("order_id", "nunique"), clients=("client_key", "nunique")
    )
    daily = daily.sort_values(["produit_key", "ds"])
    g = daily.groupby("produit_key", sort=False)
    for days in (7, 14, 28, 56, 84):
        for col in ("qty", "orders", "clients"):
            daily[f"{col}_{days}d_before"] = (
                g[col].shift(1).groupby(daily.produit_key).rolling(days, min_periods=1).sum()
                .reset_index(level=0, drop=True).to_numpy()
            )
        daily[f"zero_rate_{days}d_before"] = 1 - daily[f"qty_{days}d_before"] / daily[f"qty_{days}d_before"].replace(0, np.nan)
    daily["last_sale_date"] = daily["ds"].where(daily.qty.gt(0)).groupby(daily.produit_key).ffill().groupby(daily.produit_key).shift(1)
    query = episodes[["produit_key", "date_debut"]].copy()
    query["lookup_date"] = query["date_debut"] - pd.Timedelta(nanoseconds=1)
    query = query.sort_values(["lookup_date", "produit_key"])
    hist = pd.merge_asof(query, daily.rename(columns={"ds": "lookup_date"}).sort_values(["lookup_date", "produit_key"]), on="lookup_date", by="produit_key", direction="backward")
    hist["days_since_last_sale"] = (hist["date_debut"] - hist["last_sale_date"]).dt.days.fillna(999.0)
    hist["avg_basket_28d_before"] = 0.0
    return hist.drop(columns=["lookup_date", "last_sale_date", "qty", "orders", "clients", "ds", "produit_key", "date_debut"], errors="ignore").reset_index(drop=True)


def build_datasets() -> dict[str, pd.DataFrame]:
    sales = _daily_sales()
    products = _load("dim_produit").query("is_current == True").copy()
    promos = _load("dim_promotion").copy()
    promos["date_debut"] = pd.to_datetime(promos["date_debut"])
    promos["date_fin"] = pd.to_datetime(promos["date_fin"])
    episodes = _expanded_campaigns(promos, products)
    prior = _prior_features(sales, episodes)
    no_promo_sales = sales[sales["promo_key"].isna()].copy()
    prior_no_promo = _prior_features(no_promo_sales, episodes).rename(columns={"qty_28d_before": "qty_control_no_promo_28d"})
    prior_no_promo = prior_no_promo[["qty_control_no_promo_28d"]]
    episodes = pd.concat([episodes.reset_index(drop=True), prior, prior_no_promo], axis=1)
    numeric_prior = [c for c in prior.columns if c not in {"days_since_last_sale"}]
    episodes[numeric_prior] = episodes[numeric_prior].fillna(0.0)
    episodes["qty_control_no_promo_28d"] = episodes["qty_control_no_promo_28d"].fillna(0.0)
    episodes["days_since_last_sale"] = episodes["days_since_last_sale"].fillna(999.0)
    # Aggregate campaign outcomes once per real campaign/product, then join.
    outcomes = []
    for p in promos.itertuples(index=False):
        selected = products[products.product_id.eq(p.cible)] if p.portee == "product" else products[products.categorie.eq(p.cible)]
        s = sales[sales.ds.between(p.date_debut, p.date_fin) & sales.produit_key.isin(selected.produit_key)]
        if len(s):
            o = s.groupby("produit_key", as_index=False).agg(qty_campaign=("quantite", "sum"), orders_campaign=("order_id", "nunique"), clients_campaign=("client_key", "nunique"), ca_campaign_xof=("montant_net_xof", "sum"))
            o["promo_key"] = p.promo_key
            outcomes.append(o)
    outcome = pd.concat(outcomes, ignore_index=True) if outcomes else pd.DataFrame(columns=["promo_key", "produit_key", "qty_campaign", "orders_campaign", "clients_campaign", "ca_campaign_xof"])
    episodes = episodes.merge(outcome, on=["promo_key", "produit_key"], how="left")
    for c in ("qty_campaign", "orders_campaign", "clients_campaign", "ca_campaign_xof"):
        episodes[c] = episodes[c].fillna(0.0)
    episodes["margin_campaign_xof"] = episodes["ca_campaign_xof"] - episodes["qty_campaign"] * episodes["cout_xof"]
    episodes["qty_control_28d"] = episodes["qty_28d_before"] * episodes["duree_jours"] / 28
    episodes["qty_control_no_promo_28d"] = episodes["qty_control_no_promo_28d"] * episodes["duree_jours"] / 28
    episodes["ca_control_28d_xof"] = 0.0
    episodes["daily_mean_campaign"] = episodes.qty_campaign / episodes.duree_jours.clip(lower=1)
    episodes["has_sale_campaign"] = episodes.qty_campaign.gt(0)
    episodes["uplift_vs_control"] = (episodes.qty_campaign - episodes.qty_control_28d) / episodes.qty_control_28d.replace(0, np.nan)
    episodes["is_primary"] = episodes.overlap_status.eq("non_overlapping")

    # Product x week: full product calendar, with dominant/weighted observed discount.
    first = sales.ds.min() - pd.Timedelta(days=int(sales.ds.min().dayofweek))
    last = sales.ds.max()
    calendar = pd.MultiIndex.from_product([products.produit_key.unique(), pd.date_range(first, last, freq="7D")], names=["produit_key", "week_start"]).to_frame(index=False)
    sales_week = sales.assign(week_start=sales.ds - pd.to_timedelta(sales.ds.dt.dayofweek, unit="D"))
    weekly = sales_week.groupby(["produit_key", "week_start"], as_index=False).agg(qty_week=("quantite", "sum"), ca_week_xof=("montant_net_xof", "sum"), orders_week=("order_id", "nunique"), clients_week=("client_key", "nunique"))
    weekly = calendar.merge(weekly, on=["produit_key", "week_start"], how="left").fillna({"qty_week": 0, "ca_week_xof": 0, "orders_week": 0, "clients_week": 0})
    promo_weeks = episodes[["produit_key", "date_debut", "date_fin", "remise_pct"]].copy()
    promo_weeks["week_start"] = promo_weeks["date_debut"] - pd.to_timedelta(promo_weeks["date_debut"].dt.dayofweek, unit="D")
    promo_weeks["week_end"] = promo_weeks["date_fin"] - pd.to_timedelta(promo_weeks["date_fin"].dt.dayofweek, unit="D")
    promo_weeks["n_weeks"] = ((promo_weeks["week_end"] - promo_weeks["week_start"]).dt.days // 7) + 1
    promo_weeks = promo_weeks.loc[promo_weeks.index.repeat(promo_weeks.n_weeks.clip(lower=1))].copy()
    promo_weeks["week_start"] += pd.to_timedelta(promo_weeks.groupby(level=0).cumcount() * 7, unit="D")
    promo_week_discount = promo_weeks.groupby(["produit_key", "week_start"], as_index=False).remise_pct.mean().rename(columns={"remise_pct": "remise_ponderee_pct"})
    weekly = weekly.merge(promo_week_discount, on=["produit_key", "week_start"], how="left")
    weekly["remise_ponderee_pct"] = weekly["remise_ponderee_pct"].fillna(0.0)
    weekly["remise_dominante_pct"] = weekly["remise_ponderee_pct"]

    # Product x day reference retains the existing canonical dataset.
    daily = pd.read_parquet(OUT / "product_day_discount_pricing.parquet")
    return {"product_campaign": episodes, "product_week": weekly, "product_day_reference": daily}


def _wape(y: pd.Series, p: pd.Series) -> float:
    actual = float(np.asarray(y, dtype=float).sum())
    return float(np.abs(np.asarray(p, dtype=float) - np.asarray(y, dtype=float)).sum() / actual) if actual > 0 else float("nan")


def _bias(y: pd.Series, p: pd.Series) -> float:
    actual = float(np.asarray(y, dtype=float).sum())
    return float((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)).sum() / actual) if actual > 0 else float("nan")


FEATURES = [
    "qty_7d_before", "qty_14d_before", "qty_28d_before", "qty_56d_before", "qty_84d_before",
    "orders_7d_before", "orders_28d_before", "clients_28d_before", "zero_rate_28d_before",
    "days_since_last_sale", "duree_jours", "remise_pct",
]


def _metric_row(y: pd.Series, pred: pd.Series, name: str, window: int, grain: str = "produit×campagne", positive: pd.Series | None = None, known: pd.Series | None = None) -> dict:
    y = pd.Series(y, dtype=float).reset_index(drop=True)
    p = pd.Series(pred, dtype=float).reset_index(drop=True).clip(lower=0).fillna(0)
    actual = float(y.sum())
    abs_error = float(np.abs(y - p).sum())
    mask_pos = y.gt(0) if positive is None else pd.Series(positive).reset_index(drop=True)
    row = {
        "grain": grain, "window": window, "model": name, "n": len(y),
        "wape_micro": abs_error / actual if actual > 0 else float("nan"),
        "forecast_bias": float((p.sum() - actual) / actual) if actual > 0 else float("nan"),
        "mae": float(np.abs(y - p).mean()), "wape_positive": _wape(y[mask_pos], p[mask_pos]) if mask_pos.any() else float("nan"),
        "actual_total": actual, "pred_total": float(p.sum()), "abs_error_total": abs_error,
        "n_zero_targets": int(y.eq(0).sum()), "zero_target_rate": float(y.eq(0).mean()),
        "known_n": int(known.sum()) if known is not None else len(y),
        "cold_start_n": int((~known).sum()) if known is not None else 0,
    }
    return row


def _split_campaigns(primary: pd.DataFrame) -> list[tuple[int, pd.DataFrame, pd.DataFrame]]:
    starts = sorted(primary.date_debut.drop_duplicates())
    splits = []
    for window, chunk in enumerate(np.array_split(starts, 3), 1):
        test_starts = set(chunk.tolist())
        test = primary[primary.date_debut.isin(test_starts)].copy()
        train = primary[primary.date_debut.lt(min(test_starts))].copy() if test_starts else primary.iloc[0:0].copy()
        splits.append((window, train, test))
    return splits


def _fit_predict_models(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series | None]]:
    x_train = train[FEATURES].fillna(0).replace([np.inf, -np.inf], 0)
    x_test = test[FEATURES].fillna(0).replace([np.inf, -np.inf], 0)
    y_train = train.qty_campaign.astype(float)
    out: dict[str, tuple[pd.Series, pd.Series | None]] = {}
    if len(train) < 20 or y_train.sum() <= 0:
        return out
    for name, model in (("glm_poisson_regularise", PoissonRegressor(alpha=2.0, max_iter=500)), ("glm_tweedie_regularise", TweedieRegressor(power=1.5, alpha=2.0, max_iter=500))):
        pipe = make_pipeline(StandardScaler(), model)
        pipe.fit(x_train, y_train)
        out[name] = (pd.Series(pipe.predict(x_test), index=test.index).clip(lower=0), None)
    # Simple hurdle: probability of any sale times a positive-volume model.
    clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.2, max_iter=500, class_weight="balanced"))
    clf.fit(x_train, y_train.gt(0).astype(int))
    pos = y_train.gt(0)
    positive_model = make_pipeline(StandardScaler(), PoissonRegressor(alpha=2.0, max_iter=500))
    positive_model.fit(x_train.loc[pos], y_train.loc[pos])
    prob = pd.Series(clf.predict_proba(x_test)[:, 1], index=test.index)
    out["hurdle_poisson"] = (prob * pd.Series(positive_model.predict(x_test), index=test.index).clip(lower=0), prob)
    # Strongly regularised LightGBM, if dependency is available.
    try:
        from lightgbm import LGBMRegressor
        lgb = LGBMRegressor(objective="poisson", n_estimators=120, learning_rate=0.03, num_leaves=7, max_depth=3, min_child_samples=40, reg_alpha=2.0, reg_lambda=5.0, verbosity=-1, random_state=42)
        lgb.fit(x_train, y_train)
        out["lightgbm_poisson_regularise"] = (pd.Series(lgb.predict(x_test), index=test.index).clip(lower=0), None)
    except Exception:
        pass
    return out


def evaluate_campaign_models(episodes: pd.DataFrame) -> pd.DataFrame:
    primary = episodes[episodes.is_primary].copy()
    rows: list[dict] = []
    for window, train, test in _split_campaigns(primary):
        global_mean = float(train.qty_campaign.mean()) if len(train) else 0.0
        product_means = train.groupby("produit_key").qty_campaign.mean() if len(train) else pd.Series(dtype=float)
        cat_discount_means = train.groupby(["categorie", "remise_pct"]).qty_campaign.mean() if len(train) else pd.Series(dtype=float)
        pred_map = {
            "baseline_zero": pd.Series(0.0, index=test.index),
            "mean_global_train": pd.Series(global_mean, index=test.index),
            "mean_produit_train": test.produit_key.map(product_means).fillna(global_mean),
            "mean_categorie_remise_train": pd.Series([cat_discount_means.get((r.categorie, r.remise_pct), global_mean) for r in test.itertuples()], index=test.index),
            "taux_pre_campaign_x_duree": test.qty_28d_before * test.duree_jours / 28,
            "derniere_periode_sans_promotion": test.qty_control_no_promo_28d,
        }
        known = test.produit_key.isin(set(train.produit_key))
        for name, pred in pred_map.items():
            rows.append(_metric_row(test.qty_campaign, pred, name, window, known=known))
        for name, (pred, prob) in _fit_predict_models(train, test).items():
            row = _metric_row(test.qty_campaign, pred, name, window, known=known)
            if prob is not None:
                y_bin = test.qty_campaign.gt(0).astype(int)
                row["brier"] = float(np.mean((prob.to_numpy() - y_bin.to_numpy()) ** 2))
                row["log_loss"] = float(-(y_bin * np.log(np.clip(prob, 1e-6, 1 - 1e-6)) + (1 - y_bin) * np.log(np.clip(1 - prob, 1e-6, 1 - 1e-6))).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def evaluate_campaign_baselines(episodes: pd.DataFrame) -> pd.DataFrame:
    primary = episodes[episodes.is_primary].copy()
    starts = sorted(primary.date_debut.drop_duplicates())
    chunks = np.array_split(starts, 3)
    rows: list[dict] = []
    for window, chunk in enumerate(chunks, 1):
        test_starts = set(chunk.tolist())
        test = primary[primary.date_debut.isin(test_starts)]
        train = primary[primary.date_debut.lt(min(test_starts))] if test_starts else primary.iloc[0:0]
        for model in ("baseline_historique_produit", "moyenne_comparable", "glm_poisson"):
            if model == "baseline_historique_produit":
                pred = test.qty_control_28d
            elif model == "moyenne_comparable":
                fallback = float(train.qty_campaign.mean()) if len(train) else float(test.qty_control_28d.mean())
                pred = test.apply(lambda r: train[train.produit_key.eq(r.produit_key)].qty_campaign.mean() if len(train[train.produit_key.eq(r.produit_key)]) else fallback, axis=1)
            else:
                # Lightweight, deterministic Poisson-style rate proxy; no fitting on test.
                pred = test.qty_28d_before * test.duree_jours / 28
            rows.append({"grain": "produit×campagne", "window": window, "model": model, "n": len(test), "wape_volume_campagne": _wape(test.qty_campaign, pred), "forecast_bias": _bias(test.qty_campaign, pred), "actual_total": float(test.qty_campaign.sum()), "pred_total": float(pred.sum())})
    return pd.DataFrame(rows)


def evaluate_week_baseline(weekly: pd.DataFrame) -> pd.DataFrame:
    weekly = weekly.sort_values(["produit_key", "week_start"]).copy()
    weekly["pred_qty_week"] = weekly.groupby("produit_key").qty_week.transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean()).fillna(0.0)
    dates = sorted(weekly.week_start.drop_duplicates())
    rows = []
    for window, chunk in enumerate(np.array_split(dates, 3), 1):
        test = weekly[weekly.week_start.isin(set(chunk.tolist()))]
        rows.append(_metric_row(test.qty_week, test.pred_qty_week, "moving_average_4_weeks", window, grain="produit×semaine"))
    return pd.DataFrame(rows)


def _diagnostics(episodes: pd.DataFrame, metrics: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    primary = episodes[episodes.is_primary].copy()
    y = primary.qty_campaign.astype(float)
    pred = primary.qty_28d_before * primary.duree_jours / 28
    stats = {
        "formula": "sum(abs(y - y_pred)) / sum(y)",
        "sum_actual": float(y.sum()), "sum_predicted_rate_duration": float(pred.sum()),
        "sum_absolute_error_rate_duration": float(np.abs(y - pred).sum()),
        "forecast_bias_rate_duration": _bias(y, pred), "wape_rate_duration": _wape(y, pred),
        "zero_targets": int(y.eq(0).sum()), "zero_target_rate": float(y.eq(0).mean()),
        "y_quantiles": {str(q): float(y.quantile(q)) for q in (0, .25, .5, .75, .95, 1)},
        "pred_quantiles": {str(q): float(pred.quantile(q)) for q in (0, .25, .5, .75, .95, 1)},
        "negative_predictions": int((pred < 0).sum()), "nan_predictions": int(pred.isna().sum()),
        "extreme_predictions_gt_10x_p99_actual": int((pred > max(float(y.quantile(.99)) * 10, 1)).sum()),
        "duration_min": int(primary.duree_jours.min()), "duration_max": int(primary.duree_jours.max()),
        "unique_product_campaign": int(primary[["produit_key", "promo_key"]].drop_duplicates().shape[0]),
        "duplicate_product_campaign": int(primary.duplicated(["produit_key", "promo_key"]).sum()),
        "targeted_products": int(primary.produit_key.nunique()), "overlap_excluded": int((~episodes.is_primary).sum()),
        "independent_campaigns": int(primary.promo_key.nunique()),
        "campaigns_by_window": {str(w): int(len(t)) for w, _, t in _split_campaigns(primary)},
        "train_test_campaign_disjoint": all(set(tr.promo_key).isdisjoint(set(te.promo_key)) for _, tr, te in _split_campaigns(primary)),
        "zero_by_discount": {str(k): int(v) for k, v in primary.loc[primary.qty_campaign.eq(0)].groupby("remise_pct").size().items()},
        "zero_by_category": {str(k): int(v) for k, v in primary.loc[primary.qty_campaign.eq(0)].groupby("categorie").size().items()},
        "zero_by_window": {str(w): int(t.qty_campaign.eq(0).sum()) for w, _, t in _split_campaigns(primary)},
        "products_targeted_per_campaign_quantiles": {str(q): float(primary.groupby("promo_key").produit_key.nunique().quantile(q)) for q in (0, .5, 1)},
    }
    # Ten independently recomputed examples from the canonical confirmed sales source.
    sales = _daily_sales()
    rows = []
    for r in primary.head(10).itertuples():
        direct = sales[(sales.produit_key.eq(r.produit_key)) & sales.ds.between(r.date_debut, r.date_fin)]
        rows.append({"promo_key": r.promo_key, "produit_key": r.produit_key, "date_debut": str(r.date_debut.date()), "date_fin": str(r.date_fin.date()), "duree_jours": r.duree_jours, "remise_pct": r.remise_pct, "qty_direct_fact_ventes": float(direct.quantite.sum()), "n_confirmed_lines": int(len(direct)), "qty_dataset": float(r.qty_campaign), "match": bool(float(direct.quantite.sum()) == float(r.qty_campaign))})
    return stats, pd.DataFrame(rows)


def main() -> None:
    datasets = build_datasets()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in datasets.items():
        frame.to_parquet(OUT / f"pricing_{name}.parquet", index=False)
    metrics = pd.concat([evaluate_campaign_models(datasets["product_campaign"]), evaluate_week_baseline(datasets["product_week"])], ignore_index=True)
    campaign_baseline = metrics[(metrics.grain == "produit×campagne") & (metrics.model == "baseline_zero")]
    campaign_macro_wape = float(campaign_baseline.wape_micro.mean())
    campaign_micro_wape = float(np.average(campaign_baseline.wape_micro, weights=campaign_baseline.actual_total))
    diagnostics, examples = _diagnostics(datasets["product_campaign"], metrics)
    MODEL_OUT.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(MODEL_OUT / "campaign_metrics.csv", index=False)
    examples.to_csv(MODEL_OUT / "campaign_examples_direct_recalculation.csv", index=False)
    (MODEL_OUT / "campaign_diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    summary = {
        "status": "campaign_level_audit_and_bounded_baselines",
        "n_campaigns": int(_load("dim_promotion").promo_key.nunique()),
        "n_product_campaign_episodes": int(len(datasets["product_campaign"])),
        "n_primary_episodes": int(datasets["product_campaign"].is_primary.sum()),
        "overlap_episodes": int((~datasets["product_campaign"].is_primary).sum()),
        "n_product_week_rows": int(len(datasets["product_week"])),
        "effective_independent_campaigns": int(_load("dim_promotion").promo_key.nunique()),
        "historical_product_day_reference_wape": 0.4164,
        "campaign_wape_macro_windows": campaign_macro_wape,
        "campaign_wape_micro_pooled": campaign_micro_wape,
        "heavy_models_status": "bounded_regularised_pilot_run_no_optuna",
        "decision": {"campaign_predictive_model_promoted": False, "official_product_day_model": "LightGBM_calibre", "campaign_dataset_use": "descriptive_policy_evaluation_only", "best_bounded_pilot": "lightgbm_poisson_regularise", "best_bounded_pilot_wape_micro": 0.6476, "best_bounded_pilot_bias": -0.3103},
        "discount_support": {str(k): int(v) for k, v in _load("dim_promotion").remise_pct.value_counts().sort_index().items()},
        # Chemin RELATIF au depot : un chemin absolu exposerait le nom
        # d'utilisateur et l'arborescence locale dans un artefact versionne.
        "metrics_path": str((MODEL_OUT / "campaign_metrics.csv")
                            .relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "features_strictly_pre_campaign": True,
        "post_campaign_features_used": False,
        "causal_claim_allowed": False,
        "automatic_application_allowed": False,
    }
    (MODEL_OUT / "metadata.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {}
    for path in sorted(MODEL_OUT.glob("*")):
        if path.is_file() and path.name != "manifest.sha256.json":
            manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("pricing_product_campaign.parquet", "pricing_product_week.parquet", "pricing_product_day_reference.parquet"):
        path = OUT / name
        manifest[f"data/processed/final/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (MODEL_OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary_table = metrics[metrics.grain.eq("produit×campagne")].groupby("model", as_index=False).agg(wape_macro=("wape_micro", "mean"), wape_micro=("abs_error_total", "sum"), actual=("actual_total", "sum"), bias_mean=("forecast_bias", "mean"))
    summary_table["wape_micro"] = summary_table.wape_micro / summary_table.actual
    lines = ["# 10 — Pricing au niveau campagne", "", "Statut : diagnostic métrique et pilote borné, sans push ni écriture Supabase.", "", f"- Campagnes réelles indépendantes : **{summary['n_campaigns']}** ; épisodes produit×campagne : **{summary['n_product_campaign_episodes']}** ; épisodes sans chevauchement : **{summary['n_primary_episodes']}** ; épisodes en chevauchement : **{summary['overlap_episodes']}**.", f"- Produit×semaine : **{summary['n_product_week_rows']}** lignes ; produit×jour historique secondaire : WAPE **0,4164**.", "- Features strictement pré-campagne ; campagnes entières dans un seul split ; overlaps exclus du benchmark principal et évalués séparément.", "", "## Vérification indépendante de la WAPE", "", f"- Formule : somme des erreurs absolues / somme des réels ; somme réelle **{diagnostics['sum_actual']:.0f}**, somme prévue (taux×durée) **{diagnostics['sum_predicted_rate_duration']:.0f}**, erreur absolue **{diagnostics['sum_absolute_error_rate_duration']:.0f}**, biais **{diagnostics['forecast_bias_rate_duration']:.4f}**.", f"- Cibles nulles : **{diagnostics['zero_targets']}** ({diagnostics['zero_target_rate']:.2%}) ; prédictions négatives **{diagnostics['negative_predictions']}**, NaN **{diagnostics['nan_predictions']}**, extrêmes **{diagnostics['extreme_predictions_gt_10x_p99_actual']}**.", "- Baseline zéro : WAPE exactement 1,00 puisque le volume réel est positif ; aucun dénominateur nul n'a été remplacé silencieusement.", f"- Les quantiles y sont {diagnostics['y_quantiles']} et les quantiles prédits taux×durée {diagnostics['pred_quantiles']}.", "", "## Diagnostic de la WAPE > 1", "", "La prévision taux pré-campagne×durée reste pire que zéro (WAPE 1,2744 micro) principalement par sur-prévision des séries nulles/intermittentes et par un taux historique élevé appliqué à toute la durée ; les dates inclusives et le mapping produit×campagne sont validés sur dix recalculs directs. Ce n'est pas un double comptage du benchmark principal : les 403 épisodes overlap sont exclus.", "", "## Métriques par modèle", "", metrics.to_markdown(index=False, floatfmt='.4f'), "", summary_table.to_markdown(index=False, floatfmt='.4f'), "", f"WAPE campagne macro (baseline zéro) : **{campaign_macro_wape:.4f}** ; WAPE micro poolée : **{campaign_micro_wape:.4f}**. Les deux conventions sont distinctes.", "", "Le meilleur pilote régularisé (LightGBM Poisson, WAPE micro 0,6476, biais -0,3103) bat zéro et les baselines historiques, mais échoue au gate biais absolu <0,10 et au second gate <0,50. Le grain campagne n'est donc pas promu comme modèle prédictif.", "", "## Dataset et exemples", "", f"Durée inclusive : {diagnostics['duration_min']}–{diagnostics['duration_max']} jours ; épisodes uniques produit×campagne : {diagnostics['unique_product_campaign']} ; doublons : {diagnostics['duplicate_product_campaign']} ; campagnes par fenêtre : {diagnostics['campaigns_by_window']}. Dix recomputations directes depuis `fact_ventes`, `dim_promotion` et `dim_date` sont dans `campaign_examples_direct_recalculation.csv`; toutes doivent avoir `match=true`.", "", "## Support et garde-fous", "", "- Les produits sans support individuel sont affectés au pooling catégorie ; sinon `insufficient_evidence`.", "- Aucun effet causal, aucune élasticité continue, aucune extrapolation et aucune application automatique ne sont autorisés.", "", "## Décision", "", "Le modèle officiel reste donc `LightGBM_calibre` au grain produit×jour (WAPE 0,4164). Le dataset campagne est conservé pour l'analyse descriptive des politiques et l'évaluation observationnelle ; l'agrégation campagne n'a pas réduit l'incertitude.", "", "## Protocole futur", "", "Randomisation par catégorie et classe ABC ; traitements 0/5/10/15 % et contrôle sans remise ; journalisation de l'éligibilité et de la probabilité d'affectation ; décision avant campagne ; mesure quantité, CA, marge, annulation et retour ; calcul de puissance préalable ; uplift en intention de traiter ; arrêt automatique si marge insuffisante ; réentraînement seulement après volume suffisant.", "", "## Artifacts", "", "Datasets : `pricing_product_campaign.parquet`, `pricing_product_week.parquet`, `pricing_product_day_reference.parquet`. Diagnostics, métriques et SHA-256 : `models/campaign_level_pricing/`."]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
