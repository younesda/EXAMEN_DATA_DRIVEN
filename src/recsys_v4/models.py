"""Zoo de modeles de recommandation V4.

Meme discipline que `src.pricing_v4.models` : chaque modele est un
`FittedModel` (nom, type, etat picklable), et la prediction passe par un
dispatcher module-level `predict()` — jamais par une fermeture, pour rester
serialisable par `joblib.dump`.

Chaque modele attribue un SCORE par candidat (les 5 produits d'une slate) ;
`evaluate.slate_metrics` reclasse ensuite les candidats par score decroissant.
Aucun modele ne recoit `rank` ni `model_score` en entree (cf.
`src/recsys_v4/dataset.py`, FORBIDDEN_ROOTS).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRanker
from xgboost import XGBRanker

from src.config.settings import PROJECT_ROOT
from src.recsys_v4.dataset import ALL_FEATURES

SEED = 42
LEGACY_DIR = PROJECT_ROOT / "data" / "raw"

try:
    from catboost import CatBoostRanker
    _HAS_CATBOOST = True
except ImportError:
    _HAS_CATBOOST = False


@dataclass
class FittedModel:
    name: str
    kind: str
    state: dict[str, Any] = field(default_factory=dict)
    train_seconds: float = 0.0

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        return predict(self, frame)


def predict(model: FittedModel, frame: pd.DataFrame) -> np.ndarray:
    kind, state = model.kind, model.state

    if kind == "column_score":
        return frame[state["column"]].to_numpy(dtype=float)

    if kind == "category_table":
        return frame.categorie.map(state["table"]).fillna(state["overall"]).to_numpy(dtype=float)

    if kind == "cooccurrence":
        client_history = state["client_history"]
        cooccurrence = state["cooccurrence"]
        scores = np.zeros(len(frame))
        for index, (identity, produit) in enumerate(zip(frame.identity_key, frame.produit_key)):
            history = client_history.get(identity)
            if not history:
                scores[index] = state["fallback"].get(produit, 0.0)
                continue
            scores[index] = sum(cooccurrence.get(item, {}).get(produit, 0.0) for item in history)
        return scores

    if kind == "rrf":
        working = frame[["slate_id", "produit_key"]].copy()
        fused = np.zeros(len(frame))
        for member in state["members"]:
            member_scores = predict(member, frame)
            working["_s"] = member_scores
            ranks = working.groupby("slate_id")["_s"].rank(method="first", ascending=False)
            fused += 1.0 / (state["k"] + ranks.to_numpy())
        return fused

    if kind == "weighted_blend":
        total = np.zeros(len(frame))
        for column, weight in state["weights"].items():
            values = frame[column].to_numpy(dtype=float)
            spread = values.max() - values.min()
            normalized = (values - values.min()) / spread if spread > 0 else np.zeros_like(values)
            total += weight * normalized
        return total

    if kind == "tree_score":
        return state["model"].predict(frame[ALL_FEATURES])

    if kind == "tree_proba":
        return state["model"].predict_proba(frame[ALL_FEATURES])[:, 1]

    if kind == "xgb_ranker":
        return state["model"].predict(frame[ALL_FEATURES])

    raise ValueError(f"kind inconnu: {kind}")


def popularite_globale_v1(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    return FittedModel("popularite_globale_v1", "column_score", {"column": "product_popularity_before"})


def popularite_recente(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    return FittedModel("popularite_recente", "column_score", {"column": "product_recent_popularity_28d"})


def popularite_categorie(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    table = train.groupby("categorie").product_popularity_before.mean()
    overall = float(train.product_popularity_before.mean())
    return FittedModel("popularite_categorie", "category_table", {"table": table, "overall": overall})


def _load_confirmed_orders_before(cutoff) -> pd.DataFrame:
    ventes = pd.read_parquet(LEGACY_DIR / "fact_ventes.parquet")
    dates = pd.read_parquet(LEGACY_DIR / "dim_date.parquet")
    dates = dates.assign(ds=pd.to_datetime(dates.date_complete, utc=True).dt.normalize())
    confirmed = ventes[ventes.statut_commande.eq("confirmee")].merge(dates[["date_key", "ds"]], on="date_key")
    return confirmed[confirmed.ds < cutoff]


def cooccurrence(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    """Affinite personnalisee : co-achat historique du client avec chaque candidat."""
    orders = _load_confirmed_orders_before(cutoff)
    basket = defaultdict(set)
    for row in orders.itertuples():
        basket[row.order_id].add(row.produit_key)
    cooccurrence_counts: dict[str, Counter] = defaultdict(Counter)
    popularity: Counter = Counter()
    for items in basket.values():
        items = list(items)
        popularity.update(items)
        for item in items:
            cooccurrence_counts[item].update(other for other in items if other != item)

    client_purchases = orders.groupby("client_key").produit_key.apply(lambda s: set(s)).to_dict()
    client_history = {f"{client}": items for client, items in client_purchases.items()}
    fallback = {product: float(count) for product, count in popularity.items()}
    return FittedModel("cooccurrence", "cooccurrence",
                       {"client_history": client_history,
                        "cooccurrence": {k: dict(v) for k, v in cooccurrence_counts.items()},
                        "fallback": fallback})


def rrf(train: pd.DataFrame, target: str, cutoff, members: list[FittedModel]) -> FittedModel:
    return FittedModel("RRF", "rrf", {"members": members, "k": 60})


def hybride_popularite_affinite(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    return FittedModel("hybride_popularite_affinite", "weighted_blend",
                       {"weights": {"product_popularity_before": 0.6, "client_category_affinity": 0.4}})


_LGBM_RANKER_PARAMS = dict(n_estimators=150, num_leaves=15, min_child_samples=30,
                          learning_rate=0.05, random_state=SEED, n_jobs=2, verbosity=-1)


def lightgbm_lambdarank(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    ordered = train.sort_values("slate_id")
    groups = ordered.groupby("slate_id").size().to_numpy()
    model = LGBMRanker(objective="lambdarank", **_LGBM_RANKER_PARAMS)
    model.fit(ordered[ALL_FEATURES], ordered[target], group=groups)
    return FittedModel("LightGBM_LambdaRank", "tree_score", {"model": model})


def catboost_ranker(train: pd.DataFrame, target: str, cutoff) -> FittedModel | None:
    if not _HAS_CATBOOST:
        return None
    ordered = train.sort_values("slate_id")
    model = CatBoostRanker(loss_function="YetiRank", iterations=200, depth=6,
                          learning_rate=0.06, random_seed=SEED, verbose=False)
    model.fit(ordered[ALL_FEATURES], ordered[target], group_id=ordered.slate_id.to_numpy())
    return FittedModel("CatBoostRanker", "tree_score", {"model": model})


def xgboost_ranker(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    ordered = train.sort_values("slate_id")
    groups = ordered.groupby("slate_id").size().to_numpy()
    model = XGBRanker(objective="rank:pairwise", n_estimators=150, max_depth=5,
                      learning_rate=0.06, random_state=SEED, n_jobs=2)
    model.fit(ordered[ALL_FEATURES], ordered[target], group=groups)
    return FittedModel("XGBoost_Ranker", "xgb_ranker", {"model": model})


def pointwise_conversion(train: pd.DataFrame, target: str, cutoff) -> FittedModel:
    model = LGBMClassifier(n_estimators=150, num_leaves=15, min_child_samples=30,
                          learning_rate=0.05, random_state=SEED, n_jobs=2, verbosity=-1)
    model.fit(train[ALL_FEATURES], train[target])
    return FittedModel("pointwise_conversion", "tree_proba", {"model": model})


SIMPLE_FACTORIES: dict[str, Any] = {
    "popularite_globale_v1": popularite_globale_v1,
    "popularite_recente": popularite_recente,
    "popularite_categorie": popularite_categorie,
    "cooccurrence": cooccurrence,
    "hybride_popularite_affinite": hybride_popularite_affinite,
    "LightGBM_LambdaRank": lightgbm_lambdarank,
    "CatBoostRanker": catboost_ranker,
    "XGBoost_Ranker": xgboost_ranker,
    "pointwise_conversion": pointwise_conversion,
}
