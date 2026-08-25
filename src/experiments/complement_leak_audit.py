"""Audit de fuite du complément panier.

Le protocole existant (`complement_end_to_end.py`) construit la catégorie de
scoring à partir de la CIBLE MASQUÉE :

    cat = g.loc[g.produit_key.eq(target), 'categorie'].iloc[0]

`popularite_categorie`, `reference` et `rrf` reçoivent donc la catégorie de
l'article qu'ils doivent deviner. Ce module rejoue exactement le même
périmètre (mêmes commandes, mêmes fenêtres, même cible masquée) en comparant
la variante fuitée et la variante honnête, où seules les catégories du
CONTEXTE observé sont utilisées.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "reports" / "advanced"
SEED = 42
KS = (5, 10, 20)


def train_stats(frame: pd.DataFrame):
    co = defaultdict(Counter)
    pop = Counter()
    cats = defaultdict(Counter)
    for _, group in frame.groupby("order_id"):
        items = list(dict.fromkeys(group.produit_key))
        pop.update(items)
        for item in items:
            co[item].update(other for other in items if other != item)
        for cat, sub in group.groupby("categorie"):
            cats[cat].update(sub.produit_key)
    return co, pop, cats


def rank(scores: Counter, context: set[str], k: int = 20) -> list[str]:
    return sorted((y for y in scores if y not in context),
                  key=lambda y: (-scores[y], y))[:k]


def score_lists(context, target_category, context_categories, co, pop, cats):
    """Chaque entrée: (nom, Counter de scores, utilise_categorie_cible)."""
    coo = Counter()
    for item in context:
        for other, value in co.get(item, {}).items():
            coo[other] += float(value)
    bm25 = Counter({x: c / (1.0 + np.log1p(pop[x])) for x, c in coo.items()})
    assoc = Counter({x: c / max(pop[x], 1) for x, c in coo.items()})
    leaky_cat = Counter({x: float(v) for x, v in cats.get(target_category, {}).items()})
    honest_cat = Counter()
    for cat in context_categories:
        for x, v in cats.get(cat, {}).items():
            honest_cat[x] += float(v)
    global_pop = Counter({x: float(v) for x, v in pop.items()})
    leaky_rrf = Counter(coo)
    for x, v in leaky_cat.items():
        leaky_rrf[x] += .25 * v
    honest_rrf = Counter(coo)
    for x, v in honest_cat.items():
        honest_rrf[x] += .25 * v
    return {
        "LEAKY_categorie_cible": (leaky_cat, True),
        "LEAKY_reference": (leaky_cat, True),
        "LEAKY_rrf": (leaky_rrf, True),
        "honnete_categorie_contexte": (honest_cat, False),
        "honnete_cooccurrence": (coo, False),
        "honnete_bm25": (bm25, False),
        "honnete_association": (assoc, False),
        "honnete_popularite_globale": (global_pop, False),
        "honnete_rrf_contexte": (honest_rrf, False),
    }


def main() -> int:
    orders = pd.read_parquet(ROOT / "order_baskets.parquet")
    orders["date_commande"] = pd.to_datetime(orders.date_commande)
    multi = orders.groupby("order_id").filter(lambda x: x.produit_key.nunique() >= 2)
    dates = multi.groupby("order_id").date_commande.min().sort_values()
    chunks = np.array_split(dates.index.to_numpy(), 4)
    category_of = multi.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()

    per_unit = []
    for window in (2, 3, 4):
        test_ids = set(chunks[window - 1].tolist())
        test = multi[multi.order_id.isin(test_ids)]
        train = multi[multi.date_commande.lt(test.date_commande.min())]
        co, pop, cats = train_stats(train)
        for order_id, group in test.groupby("order_id"):
            items = list(dict.fromkeys(group.produit_key))
            target = sorted(items)[0]
            context = set(items) - {target}
            target_category = category_of[target]
            context_categories = sorted({category_of[x] for x in context})
            for name, (scores, uses_target_cat) in score_lists(
                    context, target_category, context_categories, co, pop, cats).items():
                if not scores:
                    scores = Counter({x: float(v) for x, v in pop.items()})
                top = rank(scores, context, max(KS))
                position = top.index(target) if target in top else None
                row = {"window": window, "order_id": order_id, "model": name,
                       "uses_target_category": uses_target_cat}
                for k in KS:
                    hit = int(position is not None and position < k)
                    row[f"hit@{k}"] = hit
                    row[f"ndcg@{k}"] = (1.0 / np.log2(position + 2)) if hit else 0.0
                row["top10"] = top[:10]
                per_unit.append(row)

    units = pd.DataFrame(per_unit)
    agg = (units.groupby(["window", "model", "uses_target_category"])
           .agg(**{f"{m}@{k}": (f"{'hit' if m == 'recall' else 'ndcg'}@{k}", "mean")
                   for k in KS for m in ("recall", "ndcg")},
                n_orders=("order_id", "nunique"))
           .reset_index())
    coverage = (units.explode("top10").groupby(["window", "model"]).top10.nunique() / 300.0)
    agg = agg.merge(coverage.rename("coverage_catalogue"), on=["window", "model"])

    # Bootstrap apparié commande×fenêtre : fuité - honnête (même unité).
    rng = np.random.default_rng(SEED)
    pivot = units.pivot_table(index=["window", "order_id"], columns="model",
                              values="ndcg@10", aggfunc="first")
    pairs = [("LEAKY_categorie_cible", "honnete_categorie_contexte"),
             ("LEAKY_rrf", "honnete_rrf_contexte")]
    bootstrap = {}
    for leaky, honest in pairs:
        diff = (pivot[leaky] - pivot[honest]).to_numpy()
        draws = np.array([np.mean(rng.choice(diff, diff.size, replace=True)) for _ in range(2000)])
        bootstrap[f"{leaky}_moins_{honest}"] = {
            "observed": float(diff.mean()),
            "ci95": [float(np.quantile(draws, .025)), float(np.quantile(draws, .975))],
            "n_units": int(diff.size), "draws": 2000}

    payload = {
        "constat": "complement_end_to_end.py et complement_candidate_pilot.py "
                   "derivent la categorie de scoring de la cible masquee",
        "code_fuite": "cat = g.loc[g.produit_key.eq(target),'categorie'].iloc[0]",
        "perimetre": {"commandes_multi_produits": int(multi.order_id.nunique()),
                      "fenetres": [2, 3, 4], "cible": "sorted(items)[0]",
                      "unite": "commande"},
        "metriques": agg.to_dict("records"),
        "bootstrap_appariee": bootstrap,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "complement_leak_audit.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    units.drop(columns=["top10"]).to_parquet(OUT / "complement_leak_audit_units.parquet", index=False)
    print(agg.to_string(index=False))
    print()
    print(json.dumps(bootstrap, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
