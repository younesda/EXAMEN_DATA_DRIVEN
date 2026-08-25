"""Audits candidate coverage for the three recommendation decisions.

This stage is intentionally bounded: candidate coverage is measured before any
learning-to-rank fit.  All targets are future confirmed-order or web events.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"
REPORT = PROJECT_ROOT / "reports" / "11_recommendation_advanced_ranking.md"
SEED = 42


def _wape_dummy():
    return None


def _top(counter: Counter, n: int = 100) -> list[str]:
    return [item for item, _ in counter.most_common(n)]


def _orders() -> pd.DataFrame:
    d = pd.read_parquet(ROOT / "order_baskets.parquet")
    d["date_commande"] = pd.to_datetime(d.date_commande)
    return d


def _cooccurrence(train: pd.DataFrame) -> dict[str, Counter]:
    result: dict[str, Counter] = defaultdict(Counter)
    for _, group in train.groupby("order_id"):
        items = list(dict.fromkeys(group.produit_key))
        for item in items:
            result[item].update(other for other in items if other != item)
    return result


def _next_candidates(train: pd.DataFrame, user: str, cutoff: pd.Timestamp, products: list[str], interactions: dict[str, Counter] | None = None, co: dict[str, Counter] | None = None, global_pop: Counter | None = None, recent_pop: Counter | None = None, user_items: dict[str, set[str]] | None = None, user_categories: dict[str, set[str]] | None = None) -> tuple[list[str], dict[str, dict]]:
    seen = (user_items or {}).get(user, set())
    global_pop = global_pop or Counter(train.produit_key)
    recent_pop = recent_pop or Counter(train[train.date_commande >= cutoff - pd.Timedelta(days=60)].produit_key)
    cats = (user_categories or {}).get(user, set())
    cat_pop = Counter(train[train.categorie.isin(cats)].produit_key)
    co = co or _cooccurrence(train)
    co_pop = Counter()
    for item in seen:
        co_pop.update(co.get(item, Counter()))
    web_pop = Counter()
    if interactions is not None:
        web_pop.update(interactions.get(user, Counter()))
    sources = {
        "popularite_globale": _top(global_pop, 50), "popularite_recente": _top(recent_pop, 50),
        "popularite_categorie": _top(cat_pop, 50), "item_item_commandes": _top(co_pop, 50),
        "web_recent": _top(web_pop, 50),
    }
    score = Counter(); detail: dict[str, dict] = {}
    for source, items in sources.items():
        for rank, item in enumerate(items, 1):
            score[item] += 1.0 / rank
            detail.setdefault(item, {"sources": [], "ranks": {}, "scores": {}})
            detail[item]["sources"].append(source); detail[item]["ranks"][source] = rank; detail[item]["scores"][source] = float(1.0 / rank)
    ranked = [item for item, _ in score.most_common() if item in products]
    return ranked[:50], {item: detail[item] for item in ranked[:50]}


def _recall_at(candidates: list[str], truth: set[str], k: int) -> float:
    return float(len(set(candidates[:k]) & truth) / len(truth)) if truth else 0.0


def audit_next_purchase(orders: pd.DataFrame, interactions: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    products = sorted(orders.produit_key.unique())
    windows = [pd.Timestamp("2025-05-01"), pd.Timestamp("2026-02-01"), pd.Timestamp("2026-04-02"), pd.Timestamp("2026-06-01")]
    rows = []; candidates_rows = []
    for w, cutoff in enumerate(windows, 1):
        end = cutoff + pd.Timedelta(days=29)
        train = orders[orders.date_commande < cutoff]
        test = orders[orders.date_commande.between(cutoff, end)]
        co = _cooccurrence(train); global_pop = Counter(train.produit_key); recent_pop = Counter(train[train.date_commande >= cutoff - pd.Timedelta(days=60)].produit_key)
        user_items = train.groupby("client_key").produit_key.apply(set).to_dict(); user_categories = train.groupby("client_key").categorie.apply(set).to_dict()
        train_users = set(user_items)
        web_by_user = {}
        wi = interactions[(interactions.event_timestamp < cutoff.tz_localize("UTC")) & (~interactions.event_type.eq("purchase")) & interactions.type_identite.eq("client")]
        for user, group in wi.groupby("identite"):
            web_by_user[user] = Counter(group.produit_key)
        truth = test.groupby("client_key").produit_key.apply(set).to_dict()
        users = sorted(truth)
        for scenario in ("decouverte", "reapprovisionnement"):
            recalls = []; ceilings = []; cold = 0
            for user in users:
                cand, detail = _next_candidates(train, user, cutoff, products, web_by_user, co, global_pop, recent_pop, user_items, user_categories)
                target = truth[user]; seen = set(train[train.client_key.eq(user)].produit_key)
                if scenario == "decouverte": target = target - seen
                if user not in train_users: cold += 1
                recalls.append(_recall_at(cand, target, 50)); ceilings.append(float(len(set(cand) & target) / len(target)) if target else 0.0)
                if len(candidates_rows) < 50000:
                    for item, info in detail.items():
                        candidates_rows.append({"scenario": "prochain_achat", "window": w, "client_key": user, "item": item, "source_count": len(info["sources"]), "sources": ",".join(info["sources"]), "ranks": json.dumps(info["ranks"])})
            rows.append({"scenario": "prochain_achat", "subscenario": scenario, "window": w, "n_clients": len(users), "mean_history_orders": float(train.groupby("client_key").order_id.nunique().mean()), "candidate_recall_at50": float(np.mean(recalls)), "candidate_ceiling_at50": float(np.mean(ceilings)), "cold_start_rate": cold / max(len(users), 1), "target_present_rate": float(np.mean([bool(truth[u] - (set(train[train.client_key.eq(u)].produit_key) if scenario == "decouverte" else set())) for u in users]))})
    return pd.DataFrame(rows), {"candidate_rows": pd.DataFrame(candidates_rows), "products": len(products)}


def audit_basket(orders: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    multi = orders.groupby("order_id").filter(lambda x: x.produit_key.nunique() >= 2)
    order_dates = multi.groupby("order_id").date_commande.min().sort_values()
    chunks = np.array_split(order_dates.index.to_numpy(), 4)
    co_rows = []; rows = []
    for w, ids in enumerate(chunks, 1):
        test_ids = set(ids.tolist()); test = multi[multi.order_id.isin(test_ids)]; train = multi[~multi.order_id.isin(test_ids) & multi.date_commande.lt(test.date_commande.min())]
        co = _cooccurrence(train); global_pop = Counter(train.produit_key)
        hits10 = []; hits50 = []; n_targets = 0
        for order_id, group in test.groupby("order_id"):
            context = set(group.produit_key)
            for target in context:
                candidates = Counter(global_pop)
                for item in context - {target}: candidates.update(co.get(item, Counter()))
                ranked = [x for x, _ in candidates.most_common() if x not in context]
                truth = {target}; hits10.append(float(target in ranked[:10])); hits50.append(float(target in ranked[:50])); n_targets += 1
        rows.append({"scenario": "complement_panier", "window": w, "n_orders": len(test_ids), "n_multi_orders_train": int(train.order_id.nunique()), "n_targets": n_targets, "candidate_recall_at10": float(np.mean(hits10)) if hits10 else 0.0, "candidate_recall_at50": float(np.mean(hits50)) if hits50 else 0.0, "candidate_ceiling_at50": float(np.mean(hits50)) if hits50 else 0.0, "cold_start_rate": 0.0})
    return pd.DataFrame(rows), {"n_multi_orders": int(multi.order_id.nunique())}


def audit_session() -> pd.DataFrame:
    seq = pd.read_parquet(ROOT / "session_sequences.parquet")
    seq["event_timestamp"] = pd.to_datetime(seq.event_timestamp, utc=True)
    seq = seq.sort_values(["session_id", "event_timestamp", "event_id"])
    session_groups = [(sid, g.copy()) for sid, g in seq.groupby("session_id", sort=False)]
    session_groups.sort(key=lambda x: x[1].event_timestamp.min())
    prior_pop = Counter()
    rows = []
    for event_type in ("view", "add_to_cart", "purchase"):
        useful = 0; targets = 0; candidate_hits = 0
        prior_pop.clear()
        for _, group in session_groups:
            if len(group) < 3: continue
            context = group.iloc[:-1]
            target = group.iloc[-1]
            if len(context) < 2 or pd.isna(target.produit_key): continue
            prior_pop.update(context.loc[context.event_type.eq(event_type), "produit_key"].dropna().tolist())
            if target.event_type != event_type: continue
            useful += 1; targets += 1
            pop = [item for item, _ in prior_pop.most_common()]
            context_items = set(context.produit_key.dropna())
            candidate_hits += float(target.produit_key in [x for x in pop if x not in context_items][:50])
        rows.append({"scenario": "session", "target_type": event_type, "n_evaluable_sessions": useful, "context_min_events": 2, "target_strictly_after_context": True, "candidate_recall_at50": candidate_hits / max(targets, 1), "bots_excluded": "not_available_in_session_sequences"})
    return pd.DataFrame(rows)


def main() -> None:
    orders = _orders(); interactions = pd.read_parquet(ROOT / "client_product_interactions.parquet"); interactions["event_timestamp"] = pd.to_datetime(interactions.event_timestamp, utc=True)
    next_metrics, next_art = audit_next_purchase(orders, interactions)
    basket_metrics, basket_meta = audit_basket(orders)
    session_metrics = audit_session()
    metrics = pd.concat([next_metrics, basket_metrics, session_metrics], ignore_index=True, sort=False)
    OUT.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(OUT / "candidate_coverage_metrics.csv", index=False)
    next_art["candidate_rows"].to_csv(OUT / "candidate_source_trace.csv", index=False)
    metadata = {
        "status": "candidate_coverage_gate_before_ranking",
        "official_baseline": "popularite_globale",
        "locked_reference": {"recall_at10": 0.0634, "ndcg_at10": 0.0363, "coverage": 0.0622},
        "complement_reference": {"recall_at10": 0.1006, "ndcg_at10": 0.0485, "coverage": 0.8933, "status": "systeme_metier_separe"},
        "candidate_thresholds": {"next_purchase_recall_at50": 0.50, "basket_recall_at50": 0.70},
        "n_orders_multi_product": basket_meta["n_multi_orders"],
        "products": next_art["products"],
        "ranking_started": False,
        "ranking_gate_reason": "candidate coverage audited first; no heavy ranker launched in this bounded stage",
        "session_model_usable": False,
        "no_causal_claim": True,
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob("*") if p.is_file() and p.name != "manifest.sha256.json"}
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    lines = ["# 11 — Recommendation avancée : audit des candidats", "", "Statut : étape de couverture des candidats ; aucun ranker lourd entraîné avant le gate.", "", "## Références verrouillées", "", "- Prochain achat : popularité globale, Recall@10 ≈ 0,0634, NDCG@10 ≈ 0,0363, couverture ≈ 6,22 %.", "- Complément panier : Recall@10 ≈ 0,1006, NDCG@10 ≈ 0,0485, couverture ≈ 89,33 %, système métier séparé.", "", "## Couverture candidat", "", metrics.to_markdown(index=False, floatfmt='.4f'), "", "Les sources de candidats sont tracées par paire (source, rang, score inverse du rang, nombre de sources). Les seuils Recall@50 sont 0,50 pour prochain achat et 0,70 pour complément panier ; le ranker ne doit progresser que si ces gates sont atteints.", "", "## Séparation des problèmes", "", "Prochain achat, complément panier et sessionnel utilisent des cibles, contextes et métriques distincts. Aucun purchase futur n'est utilisé dans les features. Le sessionnel reste non utilisable si la cible ou le contexte est mal aligné ; les événements bots doivent être exclus dans une future extraction complète.", "", "## Décision de cette étape", "", "Aucun LightGBM LambdaRank, CatBoostRanker, XGBoost ranking, ALS/BPR ou deep model n'est lancé dans cette étape bornée. La popularité globale reste la baseline officielle tant qu'un gain bootstrap client×fenêtre entièrement positif n'est pas démontré.", "", "## Artifacts", "", "Métriques : `candidate_coverage_metrics.csv`. Trace des sources : `candidate_source_trace.csv`. Métadonnées et SHA-256 : `models/advanced/recommendation_ranking/`."]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
