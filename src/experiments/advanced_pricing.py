"""Pricing observationnel avancé, strictement temporel et checkpointé.

La cible reste la quantité confirmée au grain produit × jour × remise observée.
Les variables contemporaines dérivées de la cible (nombre de lignes, prix payé)
sont exclues. Les scores de propension réduisent le biais de sélection sans
retirer de lignes de la métrique primaire.
"""
from __future__ import annotations

import gc
import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psutil
from catboost import CatBoostRegressor
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor, TweedieRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config.settings import PROJECT_ROOT
from src.data.extract import load_cached

DATA = PROJECT_ROOT / "data/processed/final/product_day_discount_pricing.parquet"
DAILY = PROJECT_ROOT / "data/processed/final/product_daily_forecasting.parquet"
REFERENCE = PROJECT_ROOT / "models/pricing/metadata.json"
FEATURE_CACHE = PROJECT_ROOT / "data/cache/advanced_pricing_features.parquet"
OUT = PROJECT_ROOT / "models/advanced/pricing"
CHECKPOINTS = PROJECT_ROOT / "checkpoints/advanced_pricing"
LOG = PROJECT_ROOT / "logs/advanced_pricing.jsonl"
SEED = 42
FLOOR = .05
WINDOWS = (180, 120, 60)
MAX_SECONDS_PER_MODEL = 300
SEGMENTS = ("nouveau", "occasionnel", "regulier", "vip")

TREE_CONFIGS = (
    {"num_leaves": 15, "min_child_samples": 80, "learning_rate": .05, "n_estimators": 180},
    {"num_leaves": 31, "min_child_samples": 100, "learning_rate": .035, "n_estimators": 260},
    {"num_leaves": 47, "min_child_samples": 140, "learning_rate": .03, "n_estimators": 300},
)
CATBOOST_CONFIGS = (
    {"depth": 6, "iterations": 220, "learning_rate": .045},
    {"depth": 7, "iterations": 280, "learning_rate": .035},
)


def _log(event: str, **payload) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": pd.Timestamp.utcnow().isoformat(), "event": event, **payload}, default=str) + "\n")


def score(y: np.ndarray, pred: np.ndarray) -> dict:
    prediction = np.maximum(0, np.asarray(pred, dtype=float))
    target = np.asarray(y, dtype=float)
    denominator = max(float(target.sum()), 1.0)
    return {
        "wape": float(np.abs(prediction - target).sum() / denominator),
        "bias": float((prediction - target).sum() / denominator),
        "n": int(len(target)),
    }


def price_is_supported_and_eligible(base_price: float, cost: float, discount: float,
                                    supported: set[float], floor: float = FLOOR) -> bool:
    price = base_price * (1 - discount / 100)
    return bool(discount in supported and price >= cost and price > 0 and (price - cost) / price >= floor)


def build_daily_history(daily: pd.DataFrame, order_daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Construit des historiques dont chaque ligne ne dépend que des jours < ds."""
    d = daily.sort_values(["produit_key", "ds"]).copy()
    d["ds"] = pd.to_datetime(d.ds)
    if order_daily is not None:
        d = d.merge(order_daily, on=["produit_key", "ds"], how="left")
    for column in ("order_count", "distinct_clients", "avg_basket_quantity"):
        if column not in d:
            d[column] = 0.0
        d[column] = d[column].fillna(0.0)
    group = d.groupby("produit_key", sort=False)
    for column, prefix in (("y", "sales"), ("view", "views"), ("add_to_cart", "carts"),
                           ("order_count", "orders"), ("distinct_clients", "clients"),
                           ("avg_basket_quantity", "basket")):
        shifted = group[column].shift(1)
        for lag in (1, 7, 28):
            d[f"{prefix}_lag_{lag}"] = group[column].shift(lag)
        for window in (7, 28, 84):
            d[f"{prefix}_mean_{window}"] = (shifted.groupby(d.produit_key)
                                              .rolling(window, min_periods=max(3, window // 4)).mean()
                                              .reset_index(level=0, drop=True))
    prior_views = group.view.shift(1).groupby(d.produit_key).rolling(28, min_periods=7).sum().reset_index(level=0, drop=True)
    prior_carts = group.add_to_cart.shift(1).groupby(d.produit_key).rolling(28, min_periods=7).sum().reset_index(level=0, drop=True)
    d["historical_view_to_cart_28"] = prior_carts / prior_views.replace(0, np.nan)
    d["stock_at_cutoff"] = group.niveau_stock.shift(1)
    d["restock_frequency_84"] = (group.quantite_reapprovisionnee.shift(1).gt(0)
                                  .groupby(d.produit_key).rolling(84, min_periods=14).mean()
                                  .reset_index(level=0, drop=True))
    d["sales_zero_rate_28"] = (group.y.shift(1).eq(0).groupby(d.produit_key)
                                .rolling(28, min_periods=7).mean().reset_index(level=0, drop=True))
    keep = ["produit_key", "ds", "stock_at_cutoff", "restock_frequency_84", "sales_zero_rate_28",
            "historical_view_to_cart_28"]
    keep += [c for c in d if any(c.startswith(f"{prefix}_") for prefix in
             ("sales", "views", "carts", "orders", "clients", "basket")) and c not in keep]
    return d[keep]


def _order_and_segment_history(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sales = load_cached("fact_ventes")
    dates = load_cached("dim_date")[["date_key", "date_complete"]]
    clients = load_cached("dim_client")[["client_key", "segment_fidelite"]].drop_duplicates("client_key")
    sales = sales[sales.statut_commande.eq("confirmee")].merge(dates, on="date_key").merge(clients, on="client_key", how="left")
    sales = sales.rename(columns={"date_complete": "ds"}); sales["ds"] = pd.to_datetime(sales.ds)
    basket = sales.groupby("order_id", as_index=False).quantite.sum().rename(columns={"quantite": "basket_quantity"})
    enriched = sales.merge(basket, on="order_id", how="left")
    orders = enriched.groupby(["produit_key", "ds"], as_index=False).agg(
        order_count=("order_id", "nunique"), distinct_clients=("client_key", "nunique"),
        avg_basket_quantity=("basket_quantity", "mean"))
    segment = enriched.groupby(["produit_key", "ds", "segment_fidelite"], as_index=False).quantite.sum()
    segment = segment.pivot_table(index=["produit_key", "ds"], columns="segment_fidelite", values="quantite", fill_value=0).reset_index()
    base = daily[["produit_key", "ds"]].merge(segment, on=["produit_key", "ds"], how="left")
    for name in SEGMENTS:
        if name not in base: base[name] = 0.0
        base[name] = base[name].fillna(0.0)
    total = sum(base[name] for name in SEGMENTS)
    result = base[["produit_key", "ds"]].copy()
    for name in SEGMENTS:
        numerator = (base.groupby("produit_key")[name].shift(1).groupby(base.produit_key)
                     .rolling(90, min_periods=14).sum().reset_index(level=0, drop=True))
        denominator = (total.groupby(base.produit_key).shift(1).groupby(base.produit_key)
                       .rolling(90, min_periods=14).sum().reset_index(level=0, drop=True))
        result[f"segment_share_{name}_90"] = numerator / denominator.replace(0, np.nan)
    return orders, result


def _promotion_calendar(daily: pd.DataFrame) -> pd.DataFrame:
    promos = load_cached("dim_promotion").copy()
    products = load_cached("dim_produit")[["produit_key", "product_id", "categorie"]].drop_duplicates("produit_key")
    promos["date_debut"] = pd.to_datetime(promos.date_debut); promos["date_fin"] = pd.to_datetime(promos.date_fin)
    rows = []
    for promo in promos.itertuples():
        selected = (products[products.product_id.eq(promo.cible)] if promo.portee == "product"
                    else products[products.categorie.eq(promo.cible)])
        for date in pd.date_range(promo.date_debut, promo.date_fin):
            for product in selected.itertuples():
                rows.append((product.produit_key, date, promo.promo_key, promo.portee, product.categorie))
    expanded = pd.DataFrame(rows, columns=["produit_key", "ds", "promo_key", "portee", "categorie"])
    flags = expanded.assign(active=1).pivot_table(index=["produit_key", "ds"], columns="portee", values="active", aggfunc="max", fill_value=0).reset_index()
    for scope in ("product", "category"):
        if scope not in flags: flags[scope] = 0
    concurrent = expanded.groupby(["categorie", "ds"], as_index=False).promo_key.nunique().rename(columns={"promo_key": "category_concurrent_promotions"})
    out = daily[["produit_key", "categorie", "ds"]].merge(flags, on=["produit_key", "ds"], how="left").merge(concurrent, on=["categorie", "ds"], how="left")
    out[["product", "category", "category_concurrent_promotions"]] = out[["product", "category", "category_concurrent_promotions"]].fillna(0)
    out = out.rename(columns={"product": "product_campaign_active", "category": "category_campaign_active"})
    out["campaign_active"] = out[["product_campaign_active", "category_campaign_active"]].max(axis=1)
    out["past_campaign_exposure_90"] = (out.groupby("produit_key").campaign_active.shift(1)
                                        .groupby(out.produit_key).rolling(90, min_periods=14).sum()
                                        .reset_index(level=0, drop=True))
    return out.drop(columns="categorie")


def _prior_mean(frame: pd.DataFrame, keys: list[str], prefix: str) -> pd.DataFrame:
    daily = frame.groupby(keys + ["ds"], as_index=False).agg(q_sum=("quantite", "sum"), q_n=("quantite", "size"))
    daily = daily.sort_values(keys + ["ds"])
    daily[f"{prefix}_sum_before"] = daily.groupby(keys).q_sum.cumsum() - daily.q_sum
    daily[f"{prefix}_n_before"] = daily.groupby(keys).q_n.cumsum() - daily.q_n
    daily[f"{prefix}_mean_before"] = daily[f"{prefix}_sum_before"] / daily[f"{prefix}_n_before"].replace(0, np.nan)
    return daily[keys + ["ds", f"{prefix}_mean_before", f"{prefix}_n_before"]]


def build_features() -> pd.DataFrame:
    pricing = pd.read_parquet(DATA).copy(); pricing["ds"] = pd.to_datetime(pricing.ds)
    daily = pd.read_parquet(DAILY).copy(); daily["ds"] = pd.to_datetime(daily.ds)
    orders, segments = _order_and_segment_history(daily)
    history = build_daily_history(daily, orders)
    promotions = _promotion_calendar(daily)
    d = pricing.merge(history, on=["produit_key", "ds"], how="left").merge(segments, on=["produit_key", "ds"], how="left").merge(promotions, on=["produit_key", "ds"], how="left")
    for keys, prefix in ((["produit_key"], "product"), (["produit_key", "remise_pct"], "product_discount"),
                         (["categorie", "remise_pct"], "category_discount")):
        d = d.merge(_prior_mean(pricing, keys, prefix), on=keys + ["ds"], how="left")
    for column, output in (("produit_key", "product_code"), ("categorie", "category_code"), ("marque", "brand_code")):
        d[output] = pd.Categorical(d[column], categories=sorted(d[column].unique())).codes
    d["dow"] = d.ds.dt.dayofweek; d["week"] = d.ds.dt.isocalendar().week.astype(int)
    d["month"] = d.ds.dt.month; d["weekend"] = d.dow.ge(5).astype(int)
    d["planned_paid_price_xof"] = d.prix_base_xof * (1 - d.remise_pct / 100)
    d["unit_margin_before_xof"] = d.prix_base_xof - d.cout_xof
    d["unit_margin_after_xof"] = d.planned_paid_price_xof - d.cout_xof
    d["margin_rate_after"] = d.unit_margin_after_xof / d.planned_paid_price_xof.replace(0, np.nan)
    d["discount_x_category"] = d.remise_pct * (d.category_code + 1)
    d["discount_x_product"] = d.remise_pct * (d.product_code + 1)
    d["row_id"] = np.arange(len(d), dtype=np.int64)
    return d


HISTORY_PREFIXES = ("sales_", "views_", "carts_", "orders_", "clients_", "basket_", "segment_share_")
FEATURES = [
    "remise_pct", "prix_base_xof", "cout_xof", "planned_paid_price_xof", "unit_margin_before_xof",
    "unit_margin_after_xof", "margin_rate_after", "discount_x_category", "discount_x_product",
    "product_code", "category_code", "brand_code", "dow", "week", "month", "weekend",
    "historical_view_to_cart_28", "stock_at_cutoff", "restock_frequency_84", "sales_zero_rate_28",
    "product_mean_before", "product_n_before", "product_discount_mean_before", "product_discount_n_before",
    "category_discount_mean_before", "category_discount_n_before", "product_campaign_active",
    "category_campaign_active", "category_concurrent_promotions", "past_campaign_exposure_90",
] + [f"segment_share_{name}_90" for name in SEGMENTS]
for prefix in ("sales", "views", "carts", "orders", "clients", "basket"):
    FEATURES += [f"{prefix}_lag_{lag}" for lag in (1, 7, 28)]
    FEATURES += [f"{prefix}_mean_{window}" for window in (7, 28, 84)]

PROPENSITY_FEATURES = [name for name in FEATURES if name not in {
    "remise_pct", "planned_paid_price_xof", "unit_margin_after_xof", "margin_rate_after",
    "discount_x_category", "discount_x_product", "product_discount_mean_before", "product_discount_n_before",
    "category_discount_mean_before", "category_discount_n_before",
}]


def matrix(frame: pd.DataFrame, columns: list[str] = FEATURES) -> np.ndarray:
    return frame[columns].replace([np.inf, -np.inf], np.nan).fillna(0).to_numpy(np.float32)


def _lgb(params: dict) -> LGBMRegressor:
    return LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, subsample=.85,
                         colsample_bytree=.85, reg_lambda=.2, random_state=SEED, n_jobs=2,
                         verbosity=-1, **params)


def _fit_tree(train: pd.DataFrame, calibration: pd.DataFrame, test: pd.DataFrame,
              model_name: str, sample_weight: np.ndarray | None = None):
    configs = CATBOOST_CONFIGS if model_name == "CatBoost_enriched" else TREE_CONFIGS
    best = None
    for config in configs:
        start = time.perf_counter()
        if model_name == "CatBoost_enriched":
            model = CatBoostRegressor(loss_function="Tweedie:variance_power=1.3", random_seed=SEED,
                                      thread_count=2, verbose=False, allow_writing_files=False, **config)
            model.fit(matrix(train), train.quantite, sample_weight=sample_weight)
        else:
            model = _lgb(config); model.fit(matrix(train), train.quantite, sample_weight=sample_weight)
        raw = np.maximum(0, model.predict(matrix(calibration)))
        factor = float(calibration.quantite.mean() / max(raw.mean(), 1e-9))
        validation_wape = score(calibration.quantite.to_numpy(), raw * factor)["wape"]
        _log("tuning_fit", model=model_name, config=config, elapsed_seconds=time.perf_counter()-start,
             validation_wape=validation_wape)
        if best is None or validation_wape < best[0]: best = (validation_wape, model, factor, config)
    _, model, factor, config = best
    return np.maximum(0, model.predict(matrix(test)) * factor), model, factor, config


def _glm(name: str) -> Pipeline:
    numeric = [feature for feature in FEATURES if feature not in {"product_code", "category_code", "brand_code"}]
    prep = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore"), ["produit_key", "categorie", "marque"]),
        ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
    ])
    if name == "GLM_Tweedie": model = TweedieRegressor(power=1.3, alpha=.1, link="log", max_iter=400)
    else: model = PoissonRegressor(alpha=.02 if name == "FixedEffects_Poisson" else .1, max_iter=400)
    return Pipeline([("prep", prep), ("model", model)])


def _propensity(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, dict]:
    labels = sorted(train.remise_pct.unique())
    mapping = {value: index for index, value in enumerate(labels)}
    y = train.remise_pct.map(mapping).to_numpy()
    classifier = LGBMClassifier(n_estimators=180, learning_rate=.04, num_leaves=21, min_child_samples=100,
                               random_state=SEED, n_jobs=2, verbosity=-1)
    classifier.fit(matrix(train, PROPENSITY_FEATURES), y)
    train_proba = classifier.predict_proba(matrix(train, PROPENSITY_FEATURES))
    observed = np.maximum(train_proba[np.arange(len(train)), y], 1e-4)
    prevalence = train.remise_pct.map(train.remise_pct.value_counts(normalize=True)).to_numpy()
    weights = np.clip(prevalence / observed, .2, 5.0)
    test_proba = classifier.predict_proba(matrix(test, PROPENSITY_FEATURES))
    support = np.zeros(len(test), dtype=float)
    for idx, value in enumerate(test.remise_pct.to_numpy()):
        if value in mapping: support[idx] = test_proba[idx, mapping[value]]
    audit = {"mean_observed_propensity": float(support.mean()), "min_observed_propensity": float(support.min()),
             "common_support_rate_p002": float((support >= .02).mean()), "n_test": len(test),
             "primary_population_filtered": False}
    return weights, audit


def _baselines(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    global_mean = train.quantite.mean()
    product = train.groupby("produit_key").quantite.mean()
    product_discount = train.groupby(["produit_key", "remise_pct"]).quantite.mean()
    no_discount = train[train.remise_pct.eq(0)].groupby("produit_key").quantite.mean()
    return {
        "baseline_produit": np.array([product.get(row.produit_key, global_mean) for row in test.itertuples()]),
        "politique_historique": np.array([product_discount.get((row.produit_key, row.remise_pct), product.get(row.produit_key, global_mean)) for row in test.itertuples()]),
        "aucune_remise_historique": np.array([no_discount.get(row.produit_key, product.get(row.produit_key, global_mean)) for row in test.itertuples()]),
    }


def _segment_scores(test: pd.DataFrame, prediction: np.ndarray) -> dict:
    frame = test[["quantite", "remise_pct", "product_campaign_active", "category_campaign_active"]].copy()
    frame["pred"] = prediction
    masks = {"no_discount": frame.remise_pct.eq(0), "observed_discount": frame.remise_pct.gt(0),
             "product_campaign": frame.product_campaign_active.gt(0), "category_campaign": frame.category_campaign_active.gt(0)}
    return {name: score(frame.loc[mask, "quantite"].to_numpy(), frame.loc[mask, "pred"].to_numpy())
            for name, mask in masks.items() if mask.any()}


def _simulator(d: pd.DataFrame, model, factor: float, selected_model: str) -> tuple[pd.DataFrame, dict]:
    supports = d.groupby(["produit_key", "remise_pct"]).size().rename("n").reset_index()
    rows = []
    for product_key, group in d.groupby("produit_key"):
        base = group.sort_values("ds").iloc[-1:].copy()
        supported = set(supports[(supports.produit_key == product_key) & (supports.n >= 10)].remise_pct.astype(float))
        if not supported: supported = {0.0}
        candidates = []
        for discount in sorted(supported):
            row = base.copy(); row["remise_pct"] = discount
            row["planned_paid_price_xof"] = row.prix_base_xof * (1 - discount / 100)
            row["unit_margin_after_xof"] = row.planned_paid_price_xof - row.cout_xof
            row["margin_rate_after"] = row.unit_margin_after_xof / row.planned_paid_price_xof
            row["discount_x_category"] = discount * (row.category_code + 1)
            row["discount_x_product"] = discount * (row.product_code + 1)
            if not price_is_supported_and_eligible(float(row.prix_base_xof.iloc[0]), float(row.cout_xof.iloc[0]), discount, supported):
                continue
            pred = float(np.maximum(0, model.predict(matrix(row))[0] * factor))
            price = float(row.planned_paid_price_xof.iloc[0]); margin = (price - float(row.cout_xof.iloc[0])) * pred
            candidates.append((margin, discount, price, pred))
        if not candidates: continue
        margin, discount, price, quantity = max(candidates)
        rows.append({"produit_key": product_key, "as_of_observed_row": str(base.ds.iloc[0].date()),
                     "suggested_discount_pct": discount, "simulated_price_xof": price,
                     "predicted_quantity": quantity, "predicted_margin_xof": margin,
                     "historical_support_n": int(supports[(supports.produit_key == product_key) & (supports.remise_pct == discount)].n.iloc[0]),
                     "margin_floor": FLOOR, "model": selected_model,
                     "automatic_application_allowed": False, "causal_effect_estimated": False})
    result = pd.DataFrame(rows)
    latest_cost = d.sort_values("ds").groupby("produit_key").tail(1).set_index("produit_key").cout_xof
    costs = result.produit_key.map(latest_cost) if len(result) else pd.Series(dtype=float)
    margin_rates = (result.simulated_price_xof-costs) / result.simulated_price_xof if len(result) else pd.Series(dtype=float)
    audit = {"n_products": int(result.produit_key.nunique()) if len(result) else 0,
             "nan_rows": int(result.isna().any(axis=1).sum()) if len(result) else 0,
             "negative_quantity": int(result.predicted_quantity.lt(0).sum()) if len(result) else 0,
             "below_cost": int((result.simulated_price_xof < costs).sum()) if len(result) else 0,
             "margin_floor_violations": int((margin_rates < FLOOR-1e-12).sum()) if len(result) else 0,
             "minimum_margin_rate": float(margin_rates.min()) if len(result) else None,
             "discount_distribution": {str(k): int(v) for k,v in result.suggested_discount_pct.value_counts().sort_index().items()} if len(result) else {},
             "automatic_application_allowed": False, "causal_effect_estimated": False,
             "interpretation": "observational scenario on each product's latest observed feature row; not off-policy validation"}
    return result, audit


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True); CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    if FEATURE_CACHE.exists(): d = pd.read_parquet(FEATURE_CACHE)
    else:
        d = build_features(); FEATURE_CACHE.parent.mkdir(parents=True, exist_ok=True); d.to_parquet(FEATURE_CACHE, index=False)
    d["ds"] = pd.to_datetime(d.ds)
    saved_models = OUT / "candidate_models.joblib"
    max_ds = d.ds.max(); rows, segment_rows, support_rows = [], [], []
    last_models = joblib.load(saved_models) if saved_models.exists() else {}
    model_names = ("GLM_Poisson", "GLM_Tweedie", "FixedEffects_Poisson", "LightGBM_enriched", "LightGBM_IPW", "CatBoost_enriched")
    for window, back in enumerate(WINDOWS, 1):
        test_start = max_ds - pd.Timedelta(days=back - 1); test_end = test_start + pd.Timedelta(days=59)
        calibration_start = test_start - pd.Timedelta(days=60)
        fit = d[d.ds < calibration_start].copy(); calibration = d[d.ds.between(calibration_start, test_start-pd.Timedelta(days=1))].copy()
        test = d[d.ds.between(test_start, test_end)].copy()
        for name, prediction in _baselines(pd.concat([fit, calibration]), test).items():
            rows.append({"window": window, "model": name, "test_start": str(test_start.date()), **score(test.quantite, prediction)})
            segment_rows.append({"window": window, "model": name, **_segment_scores(test, prediction)})
        weights, support = _propensity(fit, test); support_rows.append({"window": window, **support})
        for name in model_names:
            checkpoint = CHECKPOINTS / f"window_{window}_{name}.parquet"
            start = time.perf_counter()
            if checkpoint.exists(): output = pd.read_parquet(checkpoint); prediction = output.pred.to_numpy()
            else:
                if name.startswith("GLM") or name == "FixedEffects_Poisson":
                    model = _glm(name); model.fit(fit, fit.quantite)
                    raw_cal = np.maximum(0, model.predict(calibration)); factor = float(calibration.quantite.mean()/max(raw_cal.mean(),1e-9))
                    prediction = np.maximum(0, model.predict(test) * factor); config = {"alpha": model.named_steps["model"].alpha}
                else:
                    sample_weight = weights if name == "LightGBM_IPW" else None
                    prediction, model, factor, config = _fit_tree(fit, calibration, test, name, sample_weight)
                output = test[["row_id", "quantite"]].copy(); output["pred"] = prediction; output.to_parquet(checkpoint, index=False)
                last_models[name] = {"model": model, "factor": factor, "config": config}
            elapsed = time.perf_counter() - start
            metrics = score(test.quantite.to_numpy(), prediction)
            rows.append({"window": window, "model": name, "test_start": str(test_start.date()),
                         "calibration_start": str(calibration_start.date()),
                         "calibration_end": str((test_start-pd.Timedelta(days=1)).date()),
                         "calibration_strictly_prior": True, **metrics})
            segment_rows.append({"window": window, "model": name, **_segment_scores(test, prediction)})
            _log("model_complete", window=window, model=name, elapsed_seconds=elapsed,
                 rss_mb=psutil.Process().memory_info().rss/2**20, success=True,
                 within_time_budget=elapsed <= MAX_SECONDS_PER_MODEL)
        gc.collect()
    metrics = pd.DataFrame(rows)
    summary = metrics.groupby("model", as_index=False).agg(wape=("wape", "mean"), bias=("bias", "mean"),
                                                            std=("wape", "std"), n_windows=("window", "nunique")).sort_values("wape")
    eligible = summary[summary.model.isin(model_names) & summary.bias.abs().lt(.03)]
    selected = eligible.iloc[0].model if len(eligible) else None
    if selected not in last_models:
        selected = next((name for name in summary.model if name in last_models), None)
    simulator, simulator_audit = _simulator(d, last_models[selected]["model"], last_models[selected]["factor"], selected)
    simulator.to_parquet(OUT / "promotion_simulator.parquet", index=False)
    joblib.dump(last_models, OUT / "candidate_models.joblib")
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    feature_importance = []
    if selected in last_models and hasattr(last_models[selected]["model"], "feature_importances_"):
        values = last_models[selected]["model"].feature_importances_.astype(float)
        feature_importance = sorted(({"feature": feature, "importance": float(value), "share": float(value/max(values.sum(),1))}
                                     for feature, value in zip(FEATURES, values)), key=lambda x: -x["importance"])
    payload = {
        "status": "experimental_observational", "selected_experimental_predictor": selected,
        "validated_reference": {"path": "models/pricing/metadata.json", "sha256": hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                                "selected": reference["selected"], "summary": reference["summary"]},
        "target": {"column": "quantite", "grain": "produit_key × ds × remise_pct",
                   "population": "all observed confirmed-order aggregate rows in each test window",
                   "wape": "sum(abs(prediction-quantite))/sum(quantite), pooled over test rows"},
        "excluded_contemporaneous_target_proxies": ["n_lignes", "prix_unitaire_paye_xof", "ca_xof", "marge_xof", "purchase web"],
        "features": FEATURES, "window_metrics": rows, "summary": summary.to_dict("records"),
        "segment_metrics": segment_rows, "propensity_common_support": support_rows,
        "feature_importance": feature_importance, "simulator": simulator_audit,
        "methodology": {"temporal_windows": 3, "test_days": 60, "calibration_days": 60,
                        "tuning_strictly_before_test": True, "test_used_for_tuning": False,
                        "primary_population_filtered_by_common_support": False,
                        "causal_claim_allowed": False, "automatic_application_allowed": False,
                        "margin_floor": FLOOR, "discounts_limited_to_product_support_n_ge_10": True,
                        "max_seconds_per_model": MAX_SECONDS_PER_MODEL, "sequential": True},
    }
    (OUT / "metadata.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in OUT.iterdir()
                if path.is_file() and path.suffix != ".parquet" and path.name != "manifest.sha256.json"}
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.to_json(orient="records"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
