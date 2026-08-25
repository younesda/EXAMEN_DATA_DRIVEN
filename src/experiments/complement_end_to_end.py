"""Complement panier end-to-end — version corrigee (2026-08-18).

Version precedente : la categorie de scoring provenait de la cible masquee
(`cat = g.loc[g.produit_key.eq(target),'categorie'].iloc[0]`). Les modeles
`popularite_categorie`, `reference` et `rrf` recevaient donc la categorie de
l'article a deviner. Les metriques produites alors
(Recall@10 0,437 / NDCG@10 0,213) sont conservees, marquees
`invalidated_due_to_target_category_leakage`, dans
`models/advanced/recommendation_ranking/invalidated/`.

Le scoring passe desormais exclusivement par `src/recsys/complement.py`, qui
n'accepte que le contexte observe et impose un departage neutre.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.recsys.complement import (
    KS_DEFAULT, evaluate_unit, masked_target, rank, score_all, tiebreak_order, train_statistics)

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"
SEED = 42
DRAWS = 2000
REFERENCE = "popularite_globale"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    orders = pd.read_parquet(ROOT / "order_baskets.parquet")
    orders["date_commande"] = pd.to_datetime(orders.date_commande)
    multi = orders.groupby("order_id").filter(lambda x: x.produit_key.nunique() >= 2)
    order_dates = multi.groupby("order_id").date_commande.min().sort_values()
    chunks = np.array_split(order_dates.index.to_numpy(), 4)
    category_of = multi.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()
    tiebreak = tiebreak_order(orders.produit_key.unique())

    rows, units, contexts = [], [], []
    for window in (2, 3, 4):
        test_ids = set(chunks[window - 1].tolist())
        test = multi[multi.order_id.isin(test_ids)]
        train = multi[multi.date_commande < test.date_commande.min()]
        cooccurrence, popularity, category_popularity = train_statistics(train)
        for order_id, group in test.groupby("order_id"):
            items = list(dict.fromkeys(group.produit_key))
            target = masked_target(items)
            context = set(items) - {target}
            context_categories = sorted({category_of[x] for x in context})
            scores = score_all(context, context_categories, cooccurrence,
                               popularity, category_popularity, tiebreak)
            # Le contexte est stocke une seule fois par commande, et non repete
            # sur chaque ligne de rang : la table de predictions reste bornee.
            contexts.append({"window": window, "order_id": order_id, "target": target,
                             "context_items": json.dumps(sorted(context)),
                             "n_context": len(context)})
            for model, values in scores.items():
                top = rank(values, context, popularity, tiebreak, max(KS_DEFAULT))
                units.append({"window": window, "order_id": order_id, "model": model,
                              **evaluate_unit(top, target)})
                for position, item in enumerate(top, 1):
                    rows.append({"order_id": order_id, "window": window, "model": model,
                                 "item": item, "rank": position,
                                 "label": int(item == target), "score": 1.0 / position})

    predictions = pd.DataFrame(rows)
    predictions["window"] = predictions.window.astype("int8")
    predictions["rank"] = predictions["rank"].astype("int8")
    predictions["label"] = predictions.label.astype("int8")
    for column in ("order_id", "model", "item"):
        predictions[column] = predictions[column].astype("category")
    predictions.to_parquet(OUT / "complement_topk_predictions.parquet", index=False,
                           row_group_size=100_000)
    pd.DataFrame(contexts).to_parquet(OUT / "complement_contexts.parquet", index=False)
    unit_frame = pd.DataFrame(units)
    metric_columns = [c for c in unit_frame.columns if "@" in c] + ["mrr"]
    metrics = unit_frame.groupby(["window", "model"])[metric_columns].mean().reset_index()
    coverage = (predictions[predictions["rank"] <= 10]
                .groupby(["window", "model"]).item.nunique() / 300.0).rename("coverage_catalogue")
    metrics = metrics.merge(coverage, on=["window", "model"])
    metrics["n_targets"] = unit_frame.groupby(["window", "model"]).order_id.nunique().to_numpy()
    metrics.to_csv(OUT / "complement_end_to_end_metrics.csv", index=False)

    # Bootstrap apparie commande x fenetre du meilleur challenger contre la reference.
    pivot = unit_frame.pivot_table(index=["window", "order_id"], columns="model",
                                   values="ndcg@10", aggfunc="first")
    challengers = [c for c in pivot.columns if c != REFERENCE]
    best = max(challengers, key=lambda name: pivot[name].mean())
    difference = (pivot[best] - pivot[REFERENCE]).to_numpy()
    rng = np.random.default_rng(SEED)
    samples = np.array([np.mean(rng.choice(difference, difference.size, replace=True))
                        for _ in range(DRAWS)])
    ci = [float(np.quantile(samples, .025)), float(np.quantile(samples, .975))]
    gain = float((pivot[best].mean() - pivot[REFERENCE].mean()) / pivot[REFERENCE].mean())
    promoted = bool(gain >= .05 and ci[0] > 0)

    payload = {
        "leakage_correction": {
            "applied_on": "2026-08-18",
            "previous_status": "invalidated_due_to_target_category_leakage",
            "previous_metrics": {"recall@10": 0.437430, "ndcg@10": 0.212640},
            "previous_artifacts": "models/advanced/recommendation_ranking/invalidated/",
            "removed": "categorie derivee de la cible masquee",
            "scoring_module": "src/recsys/complement.py"},
        "evaluated_windows": [2, 3, 4],
        "prediction_file": "complement_topk_predictions.parquet",
        "metrics_file": "complement_end_to_end_metrics.csv",
        "bootstrap_replicates": DRAWS,
        "bootstrap_unit": "commande_x_fenetre",
        "reference": REFERENCE,
        "best_challenger": best,
        "best_challenger_relative_ndcg_gain": gain,
        "bootstrap_ndcg10_ci95": ci,
        "promotion": promoted,
        "decision": "challenger_promu" if promoted else "aucun_modele_promu",
        "basket_complement_model": best if promoted else "none_validated",
        "basket_complement_baseline": REFERENCE,
        "reason": "gain_valide" if promoted else "no_complementarity_signal",
        "f1_status": "non_evaluable_no_history",
    }
    (OUT / "complement_end_to_end_metadata.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.glob("complement_*"))
                if p.is_file() and "manifest" not in p.name}
    (OUT / "complement_end_to_end_manifest.sha256.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(metrics.round(4).to_string(index=False))
    print()
    print(json.dumps({k: payload[k] for k in
                      ("reference", "best_challenger", "best_challenger_relative_ndcg_gain",
                       "bootstrap_ndcg10_ci95", "promotion", "basket_complement_model")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
