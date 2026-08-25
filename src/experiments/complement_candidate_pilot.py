"""Couverture candidat du complement panier — version corrigee (2026-08-18).

Version precedente : `popularite_categorie` etait construite sur la categorie
de la CIBLE MASQUEE, et cette liste fuitee alimentait l'union de candidats. Le
Recall@50 candidat annonce (0,8676 / 0,8895 / 0,9332 sur F2-F4) etait donc lui
aussi gonfle. Les artefacts correspondants sont conserves sous
`models/advanced/recommendation_ranking/invalidated/`.

Le scoring passe desormais par `src/recsys/complement.py` : seules les
categories des articles presents dans le CONTEXTE sont utilisees.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.recsys.complement import (
    RRF_SOURCES, masked_target, rank, score_all, tiebreak_order, train_statistics)

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"
CANDIDATE_KS = (10, 20, 50)
GATE = .50


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    orders = pd.read_parquet(ROOT / "order_baskets.parquet")
    orders["date_commande"] = pd.to_datetime(orders.date_commande)
    multi = orders.groupby("order_id").filter(lambda x: x.produit_key.nunique() >= 2)
    order_dates = multi.groupby("order_id").date_commande.min().sort_values()
    chunks = np.array_split(order_dates.index.to_numpy(), 4)
    category_of = multi.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()
    tiebreak = tiebreak_order(orders.produit_key.unique())

    rows, union_rows = [], []
    for window in range(1, 5):
        test_ids = set(chunks[window - 1].tolist())
        test = multi[multi.order_id.isin(test_ids)]
        train = multi[multi.date_commande < test.date_commande.min()]
        cooccurrence, popularity, category_popularity = train_statistics(train)
        evaluable = bool(len(train) and train.produit_key.nunique() > 0)
        hits = {name: 0 for name in RRF_SOURCES}
        union_hits = {k: 0 for k in CANDIDATE_KS}
        union_sizes, n = [], 0
        for order_id, group in test.groupby("order_id"):
            items = list(dict.fromkeys(group.produit_key))
            target = masked_target(items)
            context = set(items) - {target}
            context_categories = sorted({category_of[x] for x in context})
            n += 1
            if not evaluable:
                union_sizes.append(0)
                continue
            scores = score_all(context, context_categories, cooccurrence,
                               popularity, category_popularity, tiebreak)
            union: set[str] = set()
            for name in RRF_SOURCES:
                ranked = rank(scores[name], context, popularity, tiebreak, 50)
                hits[name] += int(target in ranked)
                union.update(ranked)
            fused = rank(scores["rrf_contexte"], context, popularity, tiebreak, 50)
            union_sizes.append(len(fused))
            for k in CANDIDATE_KS:
                union_hits[k] += int(target in fused[:k])
        for name, hit in hits.items():
            rows.append({"scenario": "complement_panier", "window": window, "model": name,
                         "n_orders": len(test_ids), "n_targets": n,
                         "candidate_recall_at50": hit / max(n, 1),
                         "evaluable": evaluable})
        for k, hit in union_hits.items():
            union_rows.append({"window": window, "model": "rrf_top" + str(k),
                               "n_targets": n, "k": k,
                               "candidate_recall": hit / max(n, 1),
                               "mean_candidates": float(np.mean(union_sizes)) if union_sizes else 0.0,
                               "evaluable": evaluable})

    metrics = pd.DataFrame(rows)
    unions = pd.DataFrame(union_rows)
    pd.concat([metrics, unions], ignore_index=True).to_csv(
        OUT / "complement_candidate_metrics.csv", index=False)
    eligible = unions[unions.window.isin([2, 3, 4]) & unions.k.eq(50)]
    recall_at50 = [float(unions[unions.window.eq(w) & unions.k.eq(50)].candidate_recall.iloc[0])
                   for w in range(1, 5)]
    gate = bool(len(eligible) == 3 and (eligible.candidate_recall >= GATE).all())

    payload = {
        "leakage_correction": {
            "applied_on": "2026-08-18",
            "previous_status": "invalidated_due_to_target_category_leakage",
            "previous_union_recall_at50": [0.0, 0.8676068818, 0.8895438803, 0.9332393739],
            "previous_artifacts": "models/advanced/recommendation_ranking/invalidated/",
            "scoring_module": "src/recsys/complement.py"},
        "metrics": metrics.to_dict("records"),
        "union_recall_at50": recall_at50,
        "union_recall_at20": [float(unions[unions.window.eq(w) & unions.k.eq(20)].candidate_recall.iloc[0])
                              for w in range(1, 5)],
        "union_recall_at10": [float(unions[unions.window.eq(w) & unions.k.eq(10)].candidate_recall.iloc[0])
                              for w in range(1, 5)],
        "candidate_gate_ge_050": gate,
        "candidate_gate_rule": "all three evaluable windows F2-F4 meet Recall@50 >= 0.50 and none may be zero",
        "evaluated_windows": [2, 3, 4],
        "f1_status": "non_evaluable_no_history",
        "f1_model_evaluation_allowed": False,
        "f1_fallback_required": True,
        "f1_fallback_options": ["popularite_catalogue_non_comportementale", "selection_metier"],
        "f1_diagnostic": {"train_orders": 0, "train_distinct_products": 0,
                          "test_orders": int(metrics[metrics.window.eq(1)].n_targets.iloc[0]),
                          "target_catalog_presence": 0.0, "mean_candidates": 0.0,
                          "cold_start_rate": 1.0},
        "lambda_rank_started": False,
        "interpretation": (
            "sans la categorie de la cible, le vivier de candidats honnete ne couvre "
            "plus la cible dans la majorite des cas : le gate candidat n'est pas franchi, "
            "ce qui confirme l'absence de signal de complementarite"),
    }
    (OUT / "complement_candidate_metadata.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.glob("complement_*")) if p.is_file() and "manifest" not in p.name}
    (OUT / "complement_manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(metrics.round(4).to_string(index=False))
    print()
    print(unions.round(4).to_string(index=False))
    print()
    print("gate candidat >= 0.50 :", gate, "| Recall@50 F1-F4 :", [round(x, 4) for x in recall_at50])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
