"""Metriques de recommandation V4 — grain slate (5 candidats), bootstrap client/slate.

Chaque slate ne compte que 5 candidats (deja verifie par l'audit V4, controle
R-14) : les metriques sont calculees sur ce candidate set exact, jamais sur le
catalogue entier — c'est la metrique « candidate set » demandee par la
consigne. La metrique « bout en bout » (end-to-end) utilise en plus le RANG
reellement servi (`rank`), pour decrire la politique historiquement deployee,
jamais comme feature d'un nouveau modele.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
KS = (5, 10, 20)


def _dcg(hits: np.ndarray) -> float:
    if hits.size == 0:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, hits.size + 2))
    return float((hits * discounts).sum())


def rank_slate(scores: pd.Series) -> pd.Series:
    """Retourne le rang 1..n (1=meilleur score) au sein d'un slate, ex aequo
    departages par ordre croissant de produit_key (deterministe, neutre)."""
    return scores.rank(method="first", ascending=False).astype(int)


def slate_metrics(frame: pd.DataFrame, score_col: str, label_col: str, ks=KS) -> pd.DataFrame:
    """Une ligne de metriques par slate, a partir d'un score de reclassement."""
    rows = []
    for slate_id, group in frame.groupby("slate_id"):
        ordered = group.sort_values(score_col, ascending=False)
        labels = ordered[label_col].to_numpy(dtype=float)
        n_relevant = float(labels.sum())
        row = {"slate_id": slate_id, "n_relevant": n_relevant}
        for k in ks:
            top = labels[:k]
            hit = float(top.sum() > 0)
            row[f"recall@{k}"] = (top.sum() / n_relevant) if n_relevant > 0 else 0.0
            idcg = _dcg(np.ones(min(int(n_relevant), k))) if n_relevant > 0 else 0.0
            row[f"ndcg@{k}"] = (_dcg(top) / idcg) if idcg > 0 else 0.0
            row[f"hitrate@{k}"] = hit
        positions = np.flatnonzero(labels) + 1
        row["mrr"] = float(1.0 / positions[0]) if positions.size else 0.0
        # MAP@10
        top10 = labels[:10]
        hits, score = 0, 0.0
        for index, value in enumerate(top10, start=1):
            if value > 0:
                hits += 1
                score += hits / index
        row["map@10"] = (score / n_relevant) if n_relevant > 0 else 0.0
        row["top1_produit"] = ordered.produit_key.iloc[0]
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_summary(per_slate: pd.DataFrame, ks=KS) -> dict:
    summary = {"n_slates": len(per_slate)}
    for k in ks:
        summary[f"recall@{k}"] = float(per_slate[f"recall@{k}"].mean())
        summary[f"ndcg@{k}"] = float(per_slate[f"ndcg@{k}"].mean())
        summary[f"hitrate@{k}"] = float(per_slate[f"hitrate@{k}"].mean())
    summary["mrr"] = float(per_slate.mrr.mean())
    summary["map@10"] = float(per_slate["map@10"].mean())
    return summary


def coverage_diversity_novelty(per_slate: pd.DataFrame, popularity: pd.Series, n_catalog: int) -> dict:
    """Couverture catalogue, nouveaute (popularite inverse) et concentration Top-10."""
    top1 = per_slate.top1_produit
    coverage = top1.nunique() / max(n_catalog, 1)
    total_popularity = max(float(popularity.sum()), 1e-9)
    shares = popularity / total_popularity
    novelty = float((-np.log2(shares.reindex(top1).fillna(shares.min() if len(shares) else 1e-9) + 1e-12)).mean())
    top10_products = top1.value_counts().head(10)
    concentration_top10 = float(top10_products.sum() / max(len(top1), 1))
    diversity = float(top1.nunique() / max(len(top1), 1))
    return {"coverage_catalogue": coverage, "diversite": diversity,
            "nouveaute": novelty, "concentration_top10": concentration_top10}


def _partial_sums_by_group(per_slate: pd.DataFrame, group_col: str, metric_col: str) -> tuple[np.ndarray, np.ndarray]:
    codes, _ = pd.factorize(per_slate[group_col].to_numpy())
    n_groups = codes.max() + 1
    values = per_slate[metric_col].to_numpy(dtype=float)
    sums = np.bincount(codes, weights=values, minlength=n_groups)
    counts = np.bincount(codes, minlength=n_groups)
    return sums, counts


def bootstrap_ci95(per_slate_challenger: pd.DataFrame, per_slate_baseline: pd.DataFrame,
                   group_col: str, metric_col: str, draws: int = 3000, seed: int = SEED) -> dict:
    """IC95% bootstrap de la difference de metrique (challenger - baseline), grain groupe."""
    merged_challenger = per_slate_challenger[[group_col, "slate_id", metric_col]].rename(
        columns={metric_col: "challenger"})
    merged_baseline = per_slate_baseline[[group_col, "slate_id", metric_col]].rename(
        columns={metric_col: "baseline"})
    merged = merged_challenger.merge(merged_baseline, on=["slate_id", group_col])
    codes, _ = pd.factorize(merged[group_col].to_numpy())
    n_groups = codes.max() + 1
    diff = (merged.challenger - merged.baseline).to_numpy()
    sum_diff = np.bincount(codes, weights=diff, minlength=n_groups)
    counts = np.bincount(codes, minlength=n_groups)
    observed = float(diff.mean())
    rng = np.random.default_rng(seed)
    draw_index = rng.integers(0, n_groups, size=(draws, n_groups))
    means = sum_diff[draw_index].sum(axis=1) / np.maximum(counts[draw_index].sum(axis=1), 1)
    return {"observed_diff": observed, "ci95_low": float(np.quantile(means, .025)),
            "ci95_high": float(np.quantile(means, .975)), "draws": draws, "n_groups": int(n_groups)}


def holm_correction(p_values: dict[str, float]) -> dict[str, float]:
    items = sorted(p_values.items(), key=lambda item: item[1])
    m = len(items)
    corrected, running_max = {}, 0.0
    for rank, (name, raw_p) in enumerate(items, start=1):
        adjusted = min(1.0, raw_p * (m - rank + 1))
        running_max = max(running_max, adjusted)
        corrected[name] = running_max
    return corrected


def as_served_metrics(frame: pd.DataFrame, label_col: str, ks=KS) -> pd.DataFrame:
    """Metrique « bout en bout » : la liste REELLEMENT servie, via le rang loggue.

    Sert uniquement a decrire la politique historique (`popularite_globale_v1`
    ou `challenger_affinite_categorie_v1`), jamais a entrainer un modele.
    """
    working = frame.copy()
    working["_score_from_rank"] = -working["rank"]
    return slate_metrics(working, "_score_from_rank", label_col, ks)
