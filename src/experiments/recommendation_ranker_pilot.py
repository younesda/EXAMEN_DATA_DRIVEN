"""Bounded next-purchase ranking pilot on the audited candidate set.

Only LambdaRank and a pointwise logistic baseline are fit.  Candidate and
feature construction is strictly prior to each cutoff; no future purchase is
used as a feature.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src.config.settings import PROJECT_ROOT

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"
SEED = 42
FEATURES = ["global_score", "recent_score", "category_score", "item_item_score", "web_score", "source_count", "user_item_frequency", "user_item_recency_days", "user_category_affinity", "item_views", "item_carts", "price", "margin_rate", "stock_at_cutoff", "already_bought", "novelty"]


def _co(train: pd.DataFrame) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for _, g in train.groupby("order_id"):
        items = list(dict.fromkeys(g.produit_key))
        for item in items:
            out[item].update(x for x in items if x != item)
    return out


def _context(orders: pd.DataFrame, interactions: pd.DataFrame, cutoff: pd.Timestamp, product_info: pd.DataFrame) -> dict:
    train = orders[orders.date_commande < cutoff]
    global_pop = Counter(train.produit_key)
    recent_pop = Counter(train[train.date_commande >= cutoff - pd.Timedelta(days=60)].produit_key)
    co = _co(train)
    user_items = train.groupby("client_key").produit_key.apply(list).to_dict()
    user_categories = train.groupby("client_key").categorie.apply(set).to_dict()
    user_last = train.groupby(["client_key", "produit_key"]).date_commande.max().to_dict()
    user_freq = train.groupby(["client_key", "produit_key"]).quantite.sum().to_dict()
    user_cat = train.groupby(["client_key", "categorie"]).quantite.sum().to_dict()
    wi = interactions[(interactions.event_timestamp < cutoff.tz_localize("UTC")) & interactions.type_identite.eq("client") & ~interactions.event_type.eq("purchase")]
    web = wi.groupby("identite").produit_key.apply(list).to_dict()
    views = wi[wi.event_type.eq("view")].produit_key.value_counts().to_dict()
    carts = wi[wi.event_type.eq("add_to_cart")].produit_key.value_counts().to_dict()
    info = product_info.set_index("produit_key")
    category_items = {category: set(group.index) for category, group in info.groupby("categorie", sort=False)}
    info_records = info.to_dict("index")
    return {"train": train, "global": global_pop, "recent": recent_pop, "co": co, "user_items": user_items, "user_categories": user_categories, "user_last": user_last, "user_freq": user_freq, "user_cat": user_cat, "web": web, "views": views, "carts": carts, "info": info_records, "category_items": category_items}


def build_candidates(ctx: dict, users: list[str], cutoff: pd.Timestamp, truths: dict[str, set[str]] | None = None) -> pd.DataFrame:
    rows = []
    for user in users:
        seen = set(ctx["user_items"].get(user, []))
        cats = ctx["user_categories"].get(user, set())
        eligible_category_items = set().union(*(ctx["category_items"].get(cat, set()) for cat in cats)) if cats else set()
        cat_pop = Counter({item: count for item, count in ctx["global"].items() if item in eligible_category_items})
        co_pop = Counter()
        for item in seen: co_pop.update(ctx["co"].get(item, Counter()))
        web_pop = Counter(ctx["web"].get(user, []))
        source_lists = {"global": [x for x, _ in ctx["global"].most_common(50)], "recent": [x for x, _ in ctx["recent"].most_common(50)], "category": [x for x, _ in cat_pop.most_common(50)], "item_item": [x for x, _ in co_pop.most_common(50)], "web": [x for x, _ in web_pop.most_common(50)]}
        detail = {}
        for source, items in source_lists.items():
            for rank, item in enumerate(items, 1):
                if item in seen: continue
                d = detail.setdefault(item, {"sources": 0, "scores": {}}); d["sources"] += 1; d["scores"][source] = 1.0 / rank
        ranked = sorted(detail, key=lambda x: (-sum(detail[x]["scores"].values()), x))[:50]
        for item in ranked:
            d = detail[item]; product = ctx["info"][item]; last = ctx["user_last"].get((user, item));
            rows.append({"client_key": user, "cutoff": cutoff, "item": item, "label": int(truths is not None and item in truths.get(user, set())), "global_score": d["scores"].get("global", 0.0), "recent_score": d["scores"].get("recent", 0.0), "category_score": d["scores"].get("category", 0.0), "item_item_score": d["scores"].get("item_item", 0.0), "web_score": d["scores"].get("web", 0.0), "source_count": d["sources"], "user_item_frequency": ctx["user_freq"].get((user, item), 0.0), "user_item_recency_days": float((cutoff - last).days) if last is not None else 999.0, "user_category_affinity": ctx["user_cat"].get((user, product['categorie']), 0.0), "item_views": ctx["views"].get(item, 0.0), "item_carts": ctx["carts"].get(item, 0.0), "price": float(product['prix_base_xof']), "margin_rate": float((product['prix_base_xof'] - product['cout_xof']) / max(product['prix_base_xof'], 1.0)), "stock_at_cutoff": 0.0, "already_bought": int(item in seen), "novelty": int(item not in seen)})
    return pd.DataFrame(rows)


def _metrics(frame: pd.DataFrame, score: str, model: str, window: int) -> tuple[dict, pd.DataFrame]:
    rows = []
    for user, g in frame.groupby("client_key"):
        rec = g.sort_values([score, "item"], ascending=[False, True]).item.head(10).tolist(); truth = set(g.loc[g.label.eq(1), "item"]); hits = [int(x in truth) for x in rec]
        dcg = sum(hit / np.log2(i + 2) for i, hit in enumerate(hits)); ideal = sum(1 / np.log2(i + 2) for i in range(min(len(truth), 10))) or 1.0
        rows.append({"client_key": user, "recall": sum(hits) / len(truth) if truth else 0.0, "ndcg": dcg / ideal if truth else 0.0, "coverage": len(set(rec))})
    f = pd.DataFrame(rows); return {"window": window, "model": model, "recall_at10": float(f.recall.mean()), "ndcg_at10": float(f.ndcg.mean()), "coverage": float(f.coverage.gt(0).mean()), "n_clients": len(f)}, f


def run_window(orders: pd.DataFrame, interactions: pd.DataFrame, product_info: pd.DataFrame, cutoff: pd.Timestamp, window: int, train_end: pd.Timestamp) -> tuple[list[dict], pd.DataFrame]:
    print(f"window {window}: context train", flush=True)
    train_ctx = _context(orders, interactions, train_end, product_info)
    validation = orders[orders.date_commande.between(train_end, cutoff - pd.Timedelta(days=1))]
    val_truth = validation.groupby("client_key").produit_key.apply(set).to_dict()
    val_frame = build_candidates(train_ctx, sorted(val_truth), train_end, val_truth)
    print(f"window {window}: validation candidates {len(val_frame)}", flush=True)
    test = orders[orders.date_commande.between(cutoff, cutoff + pd.Timedelta(days=29))]
    truth = test.groupby("client_key").produit_key.apply(set).to_dict()
    test_ctx = _context(orders, interactions, cutoff, product_info)
    frame = build_candidates(test_ctx, sorted(truth), cutoff, truth)
    print(f"window {window}: test candidates {len(frame)}", flush=True)
    rows = []
    # Heuristic RRF and global baseline are evaluated on the same candidates.
    frame["heuristic_score"] = frame[["global_score", "recent_score", "category_score", "item_item_score", "web_score"]].sum(axis=1)
    rows.append(_metrics(frame, "global_score", "popularite_globale", window)[0]); rows.append(_metrics(frame, "heuristic_score", "heuristique_rrf", window)[0])
    useful = val_frame.groupby("client_key").label.transform("sum").gt(0)
    # Reproducible hard-negative sampling: retain all positives and the 20
    # highest heuristic negatives per client/cutoff group.
    val_frame["heuristic_score"] = val_frame[["global_score", "recent_score", "category_score", "item_item_score", "web_score"]].sum(axis=1)
    fit_parts = []
    for _, group in val_frame[useful].groupby(["client_key", "cutoff"], sort=False):
        pos = group[group.label.eq(1)]
        neg = group[group.label.eq(0)].sort_values(["heuristic_score", "item"], ascending=[False, True]).head(20)
        fit_parts.append(pd.concat([pos, neg], ignore_index=True))
    fit = pd.concat(fit_parts, ignore_index=True) if fit_parts else val_frame.iloc[0:0]
    groups = fit.groupby("client_key", sort=False).size().to_numpy()
    if len(fit) and len(groups) > 1:
        print(f"window {window}: fit rows {len(fit)}", flush=True)
        ranker = LGBMRanker(objective="lambdarank", n_estimators=120, learning_rate=.04, num_leaves=15, max_depth=4, min_child_samples=30, reg_lambda=5.0, random_state=SEED, n_jobs=2, verbosity=-1)
        ranker.fit(fit[FEATURES], fit.label, group=groups)
        frame["lambdarank_score"] = ranker.predict(frame[FEATURES])
        rows.append(_metrics(frame, "lambdarank_score", "LightGBM_LambdaRank", window)[0])
        scaler = StandardScaler(); x = scaler.fit_transform(fit[FEATURES]); clf = LogisticRegression(C=.2, max_iter=400, random_state=SEED); clf.fit(x, fit.label); frame["logistic_score"] = clf.predict_proba(scaler.transform(frame[FEATURES]))[:, 1]
        rows.append(_metrics(frame, "logistic_score", "logistique_pointwise", window)[0])
    return rows, frame


def main() -> None:
    orders = pd.read_parquet(ROOT / "order_baskets.parquet"); orders.date_commande = pd.to_datetime(orders.date_commande)
    interactions = pd.read_parquet(ROOT / "client_product_interactions.parquet"); interactions.event_timestamp = pd.to_datetime(interactions.event_timestamp, utc=True)
    product_info = pd.read_parquet(PROJECT_ROOT / "data/raw/dim_produit.parquet")[["produit_key", "categorie", "prix_base_xof", "cout_xof"]].drop_duplicates("produit_key")
    windows = [pd.Timestamp("2025-05-01"), pd.Timestamp("2026-02-01"), pd.Timestamp("2026-04-02"), pd.Timestamp("2026-06-01")]
    results = []; traces = []
    for i, cutoff in enumerate(windows[:2], 1):
        train_end = cutoff - pd.Timedelta(days=30)
        rows, frame = run_window(orders, interactions, product_info, cutoff, i, train_end); results.extend(rows)
        if i <= 2: frame.to_parquet(OUT / f"ranking_candidates_window_{i}.parquet", index=False)
    pilot_metrics = pd.DataFrame(results)
    pilot_summary = pilot_metrics.groupby("model", as_index=False).agg(recall_at10=("recall_at10", "mean"), ndcg_at10=("ndcg_at10", "mean"), coverage=("coverage", "mean"), windows=("window", "nunique"))
    baseline = pilot_summary[pilot_summary.model.eq("popularite_globale")].iloc[0]; rank = pilot_summary[pilot_summary.model.eq("LightGBM_LambdaRank")]
    gate = {"pilot_windows": [1, 2], "ndcg_gain_ge_5pct": bool(len(rank) and rank.ndcg_at10.iloc[0] >= baseline.ndcg_at10 * 1.05), "recall_loss_le_2pct": bool(len(rank) and rank.recall_at10.iloc[0] >= baseline.recall_at10 * .98), "coverage_ge_15pct": bool(len(rank) and rank.coverage.iloc[0] >= .15), "four_window_continued": bool(len(rank) and rank.ndcg_at10.iloc[0] >= baseline.ndcg_at10 * 1.05 and rank.recall_at10.iloc[0] >= baseline.recall_at10 * .98 and rank.coverage.iloc[0] >= .15)}
    if gate["four_window_continued"]:
        for i, cutoff in enumerate(windows[2:], 3):
            rows, frame = run_window(orders, interactions, product_info, cutoff, i, cutoff - pd.Timedelta(days=30)); results.extend(rows)
    metrics = pd.DataFrame(results); metrics.to_csv(OUT / "ranking_pilot_metrics.csv", index=False)
    summary = metrics.groupby("model", as_index=False).agg(recall_at10=("recall_at10", "mean"), ndcg_at10=("ndcg_at10", "mean"), coverage=("coverage", "mean"), windows=("window", "nunique"))
    payload = {"status": "ranking_pilot_completed", "official_baseline": "popularite_globale", "metrics": metrics.to_dict("records"), "summary": summary.to_dict("records"), "gate": gate, "features_strictly_prior": True, "negative_sampling_seed": SEED, "no_future_purchase_feature": True, "checkpoint_windows": [1, 2], "ranking_continued_to_four_windows": gate["four_window_continued"]}
    OUT.mkdir(parents=True, exist_ok=True); (OUT / "ranking_pilot_metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# Ranking pilote — prochain achat", "", "Les candidats proviennent des générateurs audités ; les cibles de prochaine commande restent strictement futures.", "", metrics.to_markdown(index=False, floatfmt='.4f'), "", summary.to_markdown(index=False, floatfmt='.4f'), "", f"Gate pilote : {gate}", "", "Aucune poursuite vers quatre fenêtres ni bootstrap n'est exécutée si le gate échoue. Popularité globale reste officielle tant qu'un IC95 % bootstrap favorable n'est pas obtenu."]
    (OUT / "ranking_pilot_report.md").write_text("\n".join(lines), encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob("*") if p.is_file() and p.name != "manifest.sha256.json"}; (OUT / "ranking_manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
