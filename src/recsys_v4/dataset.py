"""Construction du jeu de donnees recommandation V4, sans fuite.

Grain : une ligne = une exposition (`recommendation_id`), un produit affiche a
un rang (1..5) dans une slate (`slate_id`) pour une session. Trois cibles
evaluees separement : `viewed_after_impression`, `added_to_cart_after`,
`purchased_after`. La colonne `clicked` n'existe plus dans la semantique V4 et
n'est jamais utilisee.

Regle de disponibilite : toute feature doit etre connue strictement avant
`impression_timestamp`. `rank` et `model_score` ne sont JAMAIS des features
d'entrainement (ils encodent la politique qui a produit l'exposition, donc un
biais de position massif) ; ils ne servent qu'a evaluer la liste reellement
servie (cf. `evaluate.py`, metriques « bout en bout »).

Semantique de l'exposition : `product_exposure_probability` est un softmax
theorique sur les 5 candidats (somme ~1 par slate), mais la selection reelle
est deterministe (Top-5 par score). Ce jeu de donnees ajoute donc
`exposure_probability_status = "deterministic_top_k"` et cette probabilite
n'est jamais utilisee comme poids IPS (cf. `reports/v4_training/06_leakage_checks.json`,
controle R-19).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT

V4_DIR = PROJECT_ROOT / "data" / "raw" / "v4"
LEGACY_DIR = PROJECT_ROOT / "data" / "raw"

FORBIDDEN_ROOTS = ("viewed_after_impression", "added_to_cart_after", "purchased_after",
                  "view_timestamp", "add_to_cart_timestamp", "purchase_timestamp",
                  "rank", "model_score", "recommendation_id", "clicked")

CATEGORICAL_FEATURES = ("category_code", "brand_code", "device_code", "source_code", "channel_code")
NUMERIC_FEATURES = (
    "prix_base_xof", "client_purchase_count_before", "client_recency_days",
    "client_frequency_90d", "client_category_affinity", "product_popularity_before",
    "product_recent_popularity_28d", "is_anonymous", "is_cold_start_client",
)
ALL_FEATURES = list(CATEGORICAL_FEATURES) + list(NUMERIC_FEATURES)
TARGETS = ("viewed_after_impression", "added_to_cart_after", "purchased_after")
EXPOSURE_PROBABILITY_STATUS = "deterministic_top_k"


def _naive(series: pd.Series) -> np.ndarray:
    """Convertit une serie datetime tz-aware en tableau datetime64[ns] naif UTC."""
    return series.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")


def _load_raw() -> dict[str, pd.DataFrame]:
    reco = pd.read_parquet(V4_DIR / "fact_exposition_reco.parquet")
    reco["impression_timestamp"] = pd.to_datetime(reco.impression_timestamp, utc=True)
    ventes = pd.read_parquet(LEGACY_DIR / "fact_ventes.parquet")
    dates = pd.read_parquet(LEGACY_DIR / "dim_date.parquet")
    dates["ds"] = pd.to_datetime(dates.date_complete, utc=True).dt.normalize()
    produits = pd.read_parquet(LEGACY_DIR / "dim_produit.parquet")
    web = pd.read_parquet(LEGACY_DIR / "fact_evenements_web.parquet")
    web["event_timestamp"] = pd.to_datetime(web.event_timestamp, utc=True)
    return {"reco": reco, "ventes": ventes, "dates": dates, "produits": produits, "web": web}


def _session_context(reco: pd.DataFrame, web: pd.DataFrame) -> pd.DataFrame:
    """Appareil, source de trafic et canal de la session (constants par session)."""
    context = (web[~web.est_bot.astype(bool)]
              .groupby("session_id")[["appareil", "source_trafic", "canal"]]
              .agg(lambda s: s.mode().iloc[0] if len(s.mode()) else "inconnu"))
    return reco[["recommendation_id", "session_id"]].merge(
        context, left_on="session_id", right_index=True, how="left")


def _identity_key(reco: pd.DataFrame) -> pd.Series:
    """Cle d'identite unique : client si connu, sinon visiteur anonyme."""
    return reco.client_key.fillna("ANON:" + reco.anonymous_id.astype(str))


def _client_history_features(reco: pd.DataFrame, ventes: pd.DataFrame,
                             dates: pd.DataFrame, produits: pd.DataFrame) -> pd.DataFrame:
    """Historique d'achats confirmes du client, strictement anterieur a l'impression.

    Les visiteurs anonymes n'ont par construction aucun historique d'achat
    identifie (`client_key` est nul) : leurs features d'historique valent 0 et
    `is_anonymous`/`is_cold_start_client` le signalent explicitement.
    """
    confirmed = ventes[ventes.statut_commande.eq("confirmee")].merge(
        dates[["date_key", "ds"]], on="date_key").merge(
        produits[["produit_key", "categorie"]], on="produit_key")
    confirmed = confirmed.sort_values("ds")

    unique_clients = reco.client_key.dropna().unique()
    client_purchases = confirmed[confirmed.client_key.isin(unique_clients)]
    purchase_dates = client_purchases.groupby("client_key").ds.apply(
        lambda s: s.sort_values().to_numpy(dtype="datetime64[ns]"))
    category_history = client_purchases.groupby(["client_key", "categorie"]).ds.apply(
        lambda s: s.sort_values().to_numpy(dtype="datetime64[ns]"))

    cutoffs = _naive(reco.impression_timestamp)
    client_keys = reco.client_key.to_numpy(object)
    categories = reco.produit_key.map(produits.set_index("produit_key").categorie).to_numpy(object)

    n = len(reco)
    purchase_count = np.zeros(n)
    recency_days = np.full(n, 9999.0)
    frequency_90d = np.zeros(n)
    category_affinity = np.zeros(n)

    empty = np.array([], dtype="datetime64[ns]")
    for index in range(n):
        client = client_keys[index]
        if client is None or (isinstance(client, float) and np.isnan(client)):
            continue
        dates_array = purchase_dates.get(client, empty)
        cutoff = cutoffs[index]
        position = np.searchsorted(dates_array, cutoff, side="left")
        purchase_count[index] = position
        if position > 0:
            recency_days[index] = (cutoff - dates_array[position - 1]) / np.timedelta64(1, "D")
        window_start = cutoff - np.timedelta64(90, "D")
        frequency_90d[index] = position - np.searchsorted(dates_array, window_start, side="left")
        category_dates = category_history.get((client, categories[index]), empty)
        category_affinity[index] = np.searchsorted(category_dates, cutoff, side="left")

    return pd.DataFrame({
        "recommendation_id": reco.recommendation_id.to_numpy(),
        "client_purchase_count_before": purchase_count,
        "client_recency_days": recency_days,
        "client_frequency_90d": frequency_90d,
        "client_category_affinity": category_affinity,
    })


def _product_popularity_features(reco: pd.DataFrame, ventes: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    """Popularite du produit strictement anterieure a l'impression (cumul et fenetre 28 jours)."""
    confirmed = ventes[ventes.statut_commande.eq("confirmee")].merge(dates[["date_key", "ds"]], on="date_key")
    daily = confirmed.groupby(["produit_key", "ds"], as_index=False).quantite.sum()

    cutoffs = _naive(reco.impression_timestamp)
    results = np.zeros(len(reco))
    results_28d = np.zeros(len(reco))
    for produit_key, group in reco.groupby("produit_key"):
        product_daily = daily[daily.produit_key.eq(produit_key)].sort_values("ds")
        day_values = _naive(product_daily.ds) if len(product_daily) else np.array([], dtype="datetime64[ns]")
        cumulative = product_daily.quantite.cumsum().to_numpy() if len(product_daily) else np.array([])
        idx = reco.index.get_indexer(group.index)
        group_cutoffs = cutoffs[idx]
        for local_position, global_position in enumerate(idx):
            cutoff = group_cutoffs[local_position]
            position = np.searchsorted(day_values, cutoff, side="left")
            results[global_position] = cumulative[position - 1] if position > 0 else 0.0
            window_start_position = np.searchsorted(day_values, cutoff - np.timedelta64(28, "D"), side="left")
            results_28d[global_position] = (
                cumulative[position - 1] - (cumulative[window_start_position - 1] if window_start_position > 0 else 0.0)
                if position > 0 else 0.0)
    return pd.DataFrame({"recommendation_id": reco.recommendation_id.to_numpy(),
                        "product_popularity_before": results,
                        "product_recent_popularity_28d": results_28d})


def build_dataset() -> pd.DataFrame:
    raw = _load_raw()
    reco, ventes, dates, produits, web = (raw["reco"], raw["ventes"], raw["dates"],
                                          raw["produits"], raw["web"])

    frame = reco.merge(produits[["produit_key", "categorie", "marque", "prix_base_xof"]],
                       on="produit_key", how="left")
    session_context = _session_context(reco, web)
    frame = frame.merge(session_context.drop(columns="session_id"), on="recommendation_id", how="left")

    client_features = _client_history_features(reco, ventes, dates, produits)
    frame = frame.merge(client_features, on="recommendation_id", how="left")
    popularity_features = _product_popularity_features(reco, ventes, dates)
    frame = frame.merge(popularity_features, on="recommendation_id", how="left")

    frame["is_anonymous"] = frame.client_key.isna().astype("int8")
    frame["is_cold_start_client"] = (frame.client_purchase_count_before == 0).astype("int8")
    frame["identity_key"] = _identity_key(frame)

    frame["category_code"] = pd.Categorical(frame.categorie, categories=sorted(frame.categorie.dropna().unique())).codes
    frame["brand_code"] = pd.Categorical(frame.marque, categories=sorted(frame.marque.dropna().unique())).codes
    frame["device_code"] = pd.Categorical(frame.appareil.fillna("inconnu")).codes
    frame["source_code"] = pd.Categorical(frame.source_trafic.fillna("inconnu")).codes
    frame["channel_code"] = pd.Categorical(frame.canal.fillna("inconnu")).codes
    frame["prix_base_xof"] = frame.prix_base_xof.astype(float)

    frame["exposure_probability_status"] = EXPOSURE_PROBABILITY_STATUS

    frame["impression_week"] = (
        (frame.impression_timestamp - frame.impression_timestamp.min()).dt.days // 7
    ).astype(int)

    for column in TARGETS:
        frame[column] = frame[column].astype(int)
    for column in NUMERIC_FEATURES:
        frame[column] = frame[column].replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)

    keep = ["recommendation_id", "slate_id", "session_id", "client_key", "anonymous_id",
            "identity_key", "produit_key", "categorie", "model_version", "experiment_group",
            "rank", "model_score", "product_exposure_probability", "exposure_probability_status",
            "impression_timestamp", "impression_week"] + ALL_FEATURES + list(TARGETS)
    return frame[keep].copy()


def validate_no_forbidden_columns(columns: list[str]) -> None:
    offending = [c for c in columns if any(root in c for root in FORBIDDEN_ROOTS)]
    if offending:
        raise ValueError("Features interdites detectees : " + str(offending))


if __name__ == "__main__":
    dataset = build_dataset()
    validate_no_forbidden_columns(ALL_FEATURES)
    print(dataset.shape)
    print(dataset[list(TARGETS)].mean())
    out = PROJECT_ROOT / "data" / "raw" / "v4" / "recommendation_dataset.parquet"
    dataset.to_parquet(out, index=False)
    print("ecrit:", out)
