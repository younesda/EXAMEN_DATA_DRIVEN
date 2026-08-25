"""Construction du jeu de donnees pricing V4, sans fuite.

Grain : une ligne = une decision (`decision_id`), prise chaque lundi a 06:00 UTC
pour un sous-ensemble des 300 produits. Trois cibles evaluees separement :
`units_sold_window_7j`, `revenue_window_xof_7j`, `margin_window_xof_7j`.

Regle de disponibilite : toute feature doit etre connue strictement avant
`decision_timestamp`. Le prix effectivement utilise est toujours
`prix_applique_xof` (jamais `discount_proposed`), mais il n'est PAS une feature
d'entree ici : c'est `discount_proposed`/`discount_applied` (connus avant la
decision) qui servent de features, et `prix_applique_xof` sert uniquement a
verifier la coherence du revenu (cf. `scripts/audit_v4.py`, controle P-16) et a
documenter le prix reellement utilise dans les rapports.

Fuite corrigee : la colonne livree `product_impressions` est constante par
produit sur toute la periode (voir `reports/v4_training/06_leakage_checks.json`,
controle P-12) — ce n'est pas un cumul pre-decision. Elle est exclue des
features et reconstruite ici depuis `fact_evenements_web` (vues, hors bots,
strictement anterieures a `decision_timestamp`).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT

V4_DIR = PROJECT_ROOT / "data" / "raw" / "v4"
LEGACY_DIR = PROJECT_ROOT / "data" / "raw"

#: Racines de colonnes interdites comme features (composants ou consequences
#: des cibles, ou informations posterieures a la decision).
FORBIDDEN_ROOTS = ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j",
                   "fenetre_observation", "product_impressions", "decision_id",
                   "experiment_id", "prix_applique_xof")

CATEGORICAL_FEATURES = ("product_code", "category_code", "abc_code")
NUMERIC_FEATURES = (
    "prix_base_xof", "cout_xof", "discount_proposed", "discount_applied",
    "eligible_for_discount", "cold_start_warmup", "stock_at_decision",
    "pre_decision_views", "pre_decision_views_28d", "pre_decision_carts_28d",
    "dow", "week_of_year", "month", "is_weekend",
    "warmup_sales_mean_28", "warmup_sales_mean_84", "warmup_sales_lag_7",
    "warmup_sales_zero_rate_28", "product_age_days",
    "discount_x_category", "discount_x_abc",
)
ALL_FEATURES = list(CATEGORICAL_FEATURES) + list(NUMERIC_FEATURES)
TARGETS = ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j")


def _load_raw() -> dict[str, pd.DataFrame]:
    pricing = pd.read_parquet(V4_DIR / "fact_experimentation_prix.parquet")
    pricing["decision_timestamp"] = pd.to_datetime(pricing.decision_timestamp, utc=True)
    web = pd.read_parquet(LEGACY_DIR / "fact_evenements_web.parquet")
    web["event_timestamp"] = pd.to_datetime(web.event_timestamp, utc=True)
    web = web[~web.est_bot.astype(bool)]
    ventes = pd.read_parquet(LEGACY_DIR / "fact_ventes.parquet")
    dates = pd.read_parquet(LEGACY_DIR / "dim_date.parquet")
    dates["ds"] = pd.to_datetime(dates.date_complete, utc=True).dt.normalize()
    produits = pd.read_parquet(LEGACY_DIR / "dim_produit.parquet")
    return {"pricing": pricing, "web": web, "ventes": ventes, "dates": dates, "produits": produits}


def _pre_decision_web_features(pricing: pd.DataFrame, web: pd.DataFrame) -> pd.DataFrame:
    """Vues et ajouts panier strictement anterieurs a chaque decision.

    Reconstruit exactement ce que `product_impressions` aurait du etre : un
    cumul pre-decision, different pour chaque decision meme sur un produit
    identique.
    """
    views = web[web.type_event.eq("view")][["produit_key", "event_timestamp"]].sort_values(
        ["produit_key", "event_timestamp"])
    carts = web[web.type_event.eq("add_to_cart")][["produit_key", "event_timestamp"]].sort_values(
        ["produit_key", "event_timestamp"])

    def _naive(series: pd.Series) -> np.ndarray:
        return series.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")

    results = []
    for produit_key, group in pricing.groupby("produit_key"):
        cutoffs = _naive(group.decision_timestamp.sort_values())
        product_views = _naive(views.loc[views.produit_key.eq(produit_key), "event_timestamp"])
        product_carts = _naive(carts.loc[carts.produit_key.eq(produit_key), "event_timestamp"])

        idx_total = np.searchsorted(product_views, cutoffs, side="left")
        window_28 = cutoffs - np.timedelta64(28, "D")
        idx_28_start = np.searchsorted(product_views, window_28, side="left")
        views_28 = idx_total - idx_28_start

        idx_cart_total = np.searchsorted(product_carts, cutoffs, side="left")
        idx_cart_28_start = np.searchsorted(product_carts, window_28, side="left")
        carts_28 = idx_cart_total - idx_cart_28_start

        results.append(pd.DataFrame({
            "decision_id": group.decision_id.to_numpy(),
            "pre_decision_views": idx_total,
            "pre_decision_views_28d": views_28,
            "pre_decision_carts_28d": idx_cart_total - (idx_cart_total - carts_28),
        }))
    out = pd.concat(results, ignore_index=True)
    out["pre_decision_carts_28d"] = out["pre_decision_carts_28d"].clip(lower=0)
    return out


def _warmup_sales_features(pricing: pd.DataFrame, ventes: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    """Historique de ventes confirmees, agrege par jour, strictement anterieur au jour de decision.

    Suit la meme convention shift(1)+rolling que le pipeline forecasting V2 :
    aucune valeur du jour de decision lui-meme n'entre dans le calcul.
    """
    confirmed = ventes[ventes.statut_commande.eq("confirmee")]
    daily = (confirmed.merge(dates[["date_key", "ds"]], on="date_key")
             .groupby(["produit_key", "ds"], as_index=False).quantite.sum())
    full_index = pd.MultiIndex.from_product(
        [pricing.produit_key.unique(), dates.ds.sort_values().unique()], names=["produit_key", "ds"])
    daily = (full_index.to_frame(index=False).merge(daily, on=["produit_key", "ds"], how="left")
             .fillna({"quantite": 0}))
    daily = daily.sort_values(["produit_key", "ds"])
    group = daily.groupby("produit_key", sort=False).quantite
    shifted = group.shift(1)
    daily["sales_mean_28"] = shifted.groupby(daily.produit_key).rolling(28, min_periods=7).mean().reset_index(level=0, drop=True)
    daily["sales_mean_84"] = shifted.groupby(daily.produit_key).rolling(84, min_periods=14).mean().reset_index(level=0, drop=True)
    daily["sales_lag_7"] = group.shift(7)
    daily["sales_zero_rate_28"] = shifted.eq(0).groupby(daily.produit_key).rolling(28, min_periods=7).mean().reset_index(level=0, drop=True)

    decision_day = pricing[["decision_id", "produit_key", "decision_timestamp"]].copy()
    decision_day["ds"] = decision_day.decision_timestamp.dt.normalize()
    merged = decision_day.merge(
        daily[["produit_key", "ds", "sales_mean_28", "sales_mean_84", "sales_lag_7", "sales_zero_rate_28"]],
        on=["produit_key", "ds"], how="left")
    return merged[["decision_id", "sales_mean_28", "sales_mean_84", "sales_lag_7", "sales_zero_rate_28"]].rename(
        columns={"sales_mean_28": "warmup_sales_mean_28", "sales_mean_84": "warmup_sales_mean_84",
                 "sales_lag_7": "warmup_sales_lag_7", "sales_zero_rate_28": "warmup_sales_zero_rate_28"})


def build_dataset() -> pd.DataFrame:
    raw = _load_raw()
    pricing, web, ventes, dates, produits = (raw["pricing"], raw["web"], raw["ventes"],
                                             raw["dates"], raw["produits"])

    catalog = produits.set_index("produit_key")[["prix_base_xof", "cout_xof", "valid_from"]]
    frame = pricing.merge(catalog, on="produit_key", how="left")
    frame["valid_from"] = pd.to_datetime(frame.valid_from, utc=True)
    frame["product_age_days"] = (frame.decision_timestamp - frame.valid_from).dt.days.clip(lower=0)

    web_features = _pre_decision_web_features(pricing, web)
    frame = frame.merge(web_features, on="decision_id", how="left")
    warmup_features = _warmup_sales_features(pricing, ventes, dates)
    frame = frame.merge(warmup_features, on="decision_id", how="left")

    frame["dow"] = frame.decision_timestamp.dt.dayofweek.astype("int8")
    frame["week_of_year"] = frame.decision_timestamp.dt.isocalendar().week.astype("int16")
    frame["month"] = frame.decision_timestamp.dt.month.astype("int8")
    frame["is_weekend"] = (frame.dow >= 5).astype("int8")

    frame["product_code"] = pd.Categorical(frame.produit_key, categories=sorted(frame.produit_key.unique())).codes
    frame["category_code"] = pd.Categorical(frame.categorie, categories=sorted(frame.categorie.dropna().unique())).codes
    frame["abc_code"] = pd.Categorical(frame.classe_abc, categories=sorted(frame.classe_abc.dropna().unique())).codes
    frame["eligible_for_discount"] = frame.eligible_for_discount.astype("int8")
    frame["cold_start_warmup"] = frame.cold_start_warmup.astype("int8")

    frame["discount_x_category"] = frame.discount_proposed * (frame.category_code + 1)
    frame["discount_x_abc"] = frame.discount_proposed * (frame.abc_code + 1)

    frame["experiment_week_index"] = (
        frame.experiment_id.str.extract(r"(\d+)$").astype(int).rank(method="dense").astype(int) - 1
    )

    keep = ["decision_id", "produit_key", "categorie", "classe_abc", "treatment_group",
            "experiment_id", "experiment_week_index", "decision_timestamp",
            "prix_applique_xof"] + ALL_FEATURES + list(TARGETS)
    result = frame[keep].copy()
    for column in NUMERIC_FEATURES:
        result[column] = result[column].replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)
    for column in ("prix_applique_xof",) + TARGETS:
        result[column] = result[column].astype(float)
    return result


def validate_no_forbidden_columns(columns: list[str]) -> None:
    offending = [c for c in columns if any(root in c for root in FORBIDDEN_ROOTS)]
    if offending:
        raise ValueError("Features interdites detectees : " + str(offending))


if __name__ == "__main__":
    dataset = build_dataset()
    validate_no_forbidden_columns(ALL_FEATURES)
    print(dataset.shape)
    print(dataset[list(TARGETS)].describe())
    out = PROJECT_ROOT / "data" / "raw" / "v4" / "pricing_dataset.parquet"
    dataset.to_parquet(out, index=False)
    print("ecrit:", out)
