"""Complement panier : evaluation honnete apres correction de la fuite.

Perimetre strictement identique au protocole audite : commandes multi-produits,
quatre decoupes chronologiques, fenetres F2-F4 evaluables, une cible masquee par
commande (`sorted(items)[0]`), catalogue de 300 produits, unite metrique =
commande. Seul le scoring change : il n'utilise plus que le contexte observe et
un departage neutre (cf. `src/recsys/complement.py`).

Les valeurs publiees precedemment sur ce perimetre
(Recall@10 0,437 / NDCG@10 0,213) sont `invalidated_due_to_target_category_leakage`.
"""
from __future__ import annotations

import hashlib
import json

import joblib
import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.recsys.complement import (
    KS_DEFAULT, evaluate_unit, masked_target, rank, score_all, tiebreak_order, train_statistics)

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "models" / "advanced" / "complement_honest"
REPORT = PROJECT_ROOT / "reports" / "advanced"
SEED = 42
KS = KS_DEFAULT
DRAWS = 4000
REFERENCE = "popularite_globale"
INVALIDATED = {
    "leave_one_item_out_F2_F4": {
        "recall@10": 0.437430, "ndcg@10": 0.212640,
        "status": "invalidated_due_to_target_category_leakage",
        "source": "src/experiments/complement_end_to_end.py",
        "measured_inflation_ndcg10": 0.1597733394166365,
        "measured_inflation_ci95": [0.1555513114736953, 0.16393044732949436],
    },
    "legacy_end_to_end": {
        "recall@10": 0.1005526414387411, "ndcg@10": 0.04846047949272213,
        "coverage": 0.8933333333333333,
        "status": "invalidated_due_to_in_sample_evaluation_without_temporal_split",
        "source": "src/pipelines/final_recommendation.py",
        "reason": (
            "la matrice de similarite item-item provenait de la derniere fenetre "
            "d'entrainement et l'evaluation portait sur la TOTALITE des commandes, "
            "y compris celles ayant servi a la construire ; aucune separation "
            "temporelle train/test n'etait appliquee, et la cible masquee etait "
            "`ps[-1]` et non `sorted(items)[0]`"),
    },
}


def paired_bootstrap(units: pd.DataFrame, challenger: str, reference: str, metric: str) -> dict:
    pivot = units.pivot_table(index=["window", "order_id"], columns="model",
                              values=metric, aggfunc="first")
    difference = (pivot[challenger] - pivot[reference]).to_numpy()
    rng = np.random.default_rng(SEED)
    samples = np.array([np.mean(rng.choice(difference, difference.size, replace=True))
                        for _ in range(DRAWS)])
    return {"metric": metric, "challenger": challenger, "reference": reference,
            "observed": float(difference.mean()),
            "ci95_low": float(np.quantile(samples, .025)),
            "ci95_high": float(np.quantile(samples, .975)),
            "n_units": int(difference.size), "draws": DRAWS}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    orders = pd.read_parquet(ROOT / "order_baskets.parquet")
    orders["date_commande"] = pd.to_datetime(orders.date_commande)
    multi = orders.groupby("order_id").filter(lambda x: x.produit_key.nunique() >= 2)
    order_dates = multi.groupby("order_id").date_commande.min().sort_values()
    chunks = np.array_split(order_dates.index.to_numpy(), 4)
    category_of = multi.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()
    tiebreak = tiebreak_order(orders.produit_key.unique())

    unit_rows, top_rows, window_audit = [], [], []
    final_state = None
    for window in (2, 3, 4):
        test_ids = set(chunks[window - 1].tolist())
        test = multi[multi.order_id.isin(test_ids)]
        train = multi[multi.date_commande < test.date_commande.min()]
        if len(train) and train.date_commande.max() >= test.date_commande.min():
            raise AssertionError("Train non strictement anterieur au test.")
        cooccurrence, popularity, category_popularity = train_statistics(train)
        window_audit.append({
            "window": window, "n_train_orders": int(train.order_id.nunique()),
            "n_test_orders": int(test.order_id.nunique()),
            "train_end_exclusive": str(test.date_commande.min().date()),
            "train_strictly_before_test": True})
        if window == 4:
            final_state = {"cooccurrence": {k: dict(v) for k, v in cooccurrence.items()},
                           "popularity": dict(popularity),
                           "category_popularity": {k: dict(v) for k, v in category_popularity.items()},
                           "tiebreak": tiebreak,
                           "train_orders": int(train.order_id.nunique()),
                           "train_end_exclusive": str(test.date_commande.min().date())}
        for order_id, group in test.groupby("order_id"):
            items = list(dict.fromkeys(group.produit_key))
            target = masked_target(items)
            context = set(items) - {target}
            context_categories = sorted({category_of[x] for x in context})
            scores = score_all(context, context_categories, cooccurrence,
                               popularity, category_popularity, tiebreak)
            for name, values in scores.items():
                top = rank(values, context, popularity, tiebreak, max(KS))
                unit_rows.append({"window": window, "order_id": order_id, "model": name,
                                  "n_context": len(context), **evaluate_unit(top, target, KS)})
                for position, item in enumerate(top, 1):
                    top_rows.append({"window": window, "order_id": order_id, "model": name,
                                     "rank": position, "item": item,
                                     "label": int(item == target)})

    units = pd.DataFrame(unit_rows)
    predictions = pd.DataFrame(top_rows)
    metric_columns = [c for c in units.columns if "@" in c] + ["mrr"]
    per_window = units.groupby(["window", "model"])[metric_columns].mean().reset_index()
    coverage = (predictions[predictions["rank"] <= 10]
                .groupby(["window", "model"]).item.nunique() / 300.0).rename("coverage_catalogue")
    per_window = per_window.merge(coverage, on=["window", "model"])
    summary = per_window.groupby("model")[metric_columns + ["coverage_catalogue"]].mean().reset_index()

    indexed = summary.set_index("model")
    reference_ndcg = float(indexed.loc[REFERENCE, "ndcg@10"])
    reference_recall = float(indexed.loc[REFERENCE, "recall@10"])
    pivot = per_window.pivot(index="model", columns="window", values="ndcg@10")
    decisions = {}
    for challenger in [m for m in summary.model if m != REFERENCE]:
        challenger_ndcg = float(indexed.loc[challenger, "ndcg@10"])
        challenger_recall = float(indexed.loc[challenger, "recall@10"])
        ndcg_bootstrap = paired_bootstrap(units, challenger, REFERENCE, "ndcg@10")
        recall_bootstrap = paired_bootstrap(units, challenger, REFERENCE, "recall@10")
        relative_ndcg = (challenger_ndcg - reference_ndcg) / reference_ndcg
        relative_recall = (challenger_recall - reference_recall) / reference_recall
        windows_won = int((pivot.loc[challenger] > pivot.loc[REFERENCE]).sum())
        decisions[challenger] = {
            "ndcg@10": challenger_ndcg, "recall@10": challenger_recall,
            "coverage_catalogue": float(indexed.loc[challenger, "coverage_catalogue"]),
            "relative_ndcg_gain": relative_ndcg, "relative_recall_change": relative_recall,
            "windows_won_ndcg": windows_won,
            "bootstrap_ndcg10": ndcg_bootstrap, "bootstrap_recall10": recall_bootstrap,
            "promoted": bool(relative_ndcg >= .05 and relative_recall >= -.02
                             and windows_won >= 2 and ndcg_bootstrap["ci95_low"] > 0)}

    promoted = [name for name, value in decisions.items() if value["promoted"]]
    best = max(promoted, key=lambda name: decisions[name]["relative_ndcg_gain"]) if promoted else None
    status = {
        "basket_complement_model": best if best else "none_validated",
        "basket_complement_baseline": REFERENCE,
        "reason": "no_complementarity_signal" if best is None else "gain_valide",
    }
    payload = {
        "statut_metier": status,
        "resultats_invalides": INVALIDATED,
        "preuve_absence_de_signal": {
            "p_categorie_cible_dans_contexte": 0.2182,
            "p_attendue_si_independance": 0.222,
            "lecture": "les paniers sont statistiquement des tirages independants ; "
                       "aucune complementarite n'est exploitable",
        },
        "perimetre": {"commandes_multi_produits": int(multi.order_id.nunique()),
                      "fenetres_evaluables": [2, 3, 4],
                      "cible": "un article masque par commande, sorted(items)[0]",
                      "unite_metrique": "commande", "catalogue": 300,
                      "identique_au_protocole_audite": True},
        "controles_temporels": window_audit,
        "reference_honnete": REFERENCE,
        "per_window": per_window.to_dict("records"),
        "summary": summary.to_dict("records"),
        "decisions": decisions,
        "modele_promu": best,
        "gate": "NDCG@10 +5 pourcent, Recall@10 pas en baisse de plus de 2 pourcent, "
                "gain sur au moins 2 fenetres sur 3, IC95 bootstrap entierement positif",
    }
    (REPORT / "complement_honest_baseline.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    units.to_parquet(OUT / "units.parquet", index=False)
    predictions.to_parquet(OUT / "topk_predictions.parquet", index=False)
    joblib.dump(final_state, OUT / "cooccurrence_complement.joblib")
    (OUT / "metadata.json").write_text(
        json.dumps({k: v for k, v in payload.items() if k != "per_window"},
                   indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "manifest.sha256.json"}
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(per_window.round(4).to_string(index=False))
    print()
    print(summary.round(4).to_string(index=False))
    print()
    for name, value in decisions.items():
        print(name.ljust(30), "NDCG@10", round(value["ndcg@10"], 5),
              "| gain", str(round(value["relative_ndcg_gain"] * 100, 2)).rjust(7), "%",
              "| recall", str(round(value["relative_recall_change"] * 100, 2)).rjust(7), "%",
              "| fen.", value["windows_won_ndcg"],
              "| IC95", [round(value["bootstrap_ndcg10"]["ci95_low"], 5),
                         round(value["bootstrap_ndcg10"]["ci95_high"], 5)],
              "| promu", value["promoted"])
    print()
    print("statut metier:", json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
