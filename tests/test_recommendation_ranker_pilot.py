"""Pilote de ranking et complement panier — apres correction de la fuite.

Lecture bornee en memoire : les tables de predictions comptent ~1,9 M de
lignes. Rien n'est materialise en entier ; on lit colonne par colonne, fenetre
par fenetre, et par lots de row groups.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "models" / "advanced" / "recommendation_ranking"
PREDICTIONS = OUT / "complement_topk_predictions.parquet"
CONTEXTS = OUT / "complement_contexts.parquet"
MAX_ROWS_MATERIALISED = 150_000
MODELS = ("popularite_globale", "cooccurrence_item_item", "bm25_panier",
          "association_lift", "popularite_categorie_contexte", "rrf_contexte")


def _metadata(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------ pilote ranking


def test_ranker_pilot_has_only_prior_features_and_deterministic_negative_seed():
    meta = _metadata("ranking_pilot_metadata.json")
    assert meta["features_strictly_prior"] is True
    assert meta["no_future_purchase_feature"] is True
    assert meta["negative_sampling_seed"] == 42
    windows = pd.read_csv(OUT / "ranking_pilot_metrics.csv", usecols=["window"])
    assert set(windows.window) == {1, 2}


def test_ranker_gate_failure_keeps_popularity_official():
    meta = _metadata("ranking_pilot_metadata.json")
    assert meta["official_baseline"] == "popularite_globale"
    assert meta["gate"]["four_window_continued"] is False
    assert meta["gate"]["ndcg_gain_ge_5pct"] is False


# ------------------------------------------- complement panier, apres correction


def test_candidate_pilot_declares_the_leakage_correction():
    meta = _metadata("complement_candidate_metadata.json")
    correction = meta["leakage_correction"]
    assert correction["previous_status"] == "invalidated_due_to_target_category_leakage"
    assert correction["scoring_module"] == "src/recsys/complement.py"
    assert meta["evaluated_windows"] == [2, 3, 4]
    assert meta["lambda_rank_started"] is False
    assert meta["f1_status"] == "non_evaluable_no_history"
    assert meta["f1_model_evaluation_allowed"] is False
    assert meta["f1_fallback_required"] is True
    assert meta["f1_diagnostic"]["train_orders"] == 0
    assert meta["f1_diagnostic"]["mean_candidates"] == 0.0


def test_candidate_gate_is_not_met_without_the_leaked_category():
    """Le vivier honnete ne couvre plus la cible : le gate tombe."""
    meta = _metadata("complement_candidate_metadata.json")
    assert meta["candidate_gate_ge_050"] is False
    assert meta["union_recall_at50"][0] == 0.0
    for value in meta["union_recall_at50"][1:]:
        assert 0.0 < value < .50
    previous = meta["leakage_correction"]["previous_union_recall_at50"]
    assert all(new < old for new, old in zip(meta["union_recall_at50"][1:], previous[1:]))


def test_f1_remains_a_genuine_cold_start_window():
    meta = _metadata("complement_candidate_metadata.json")
    diagnostic = meta["f1_diagnostic"]
    assert diagnostic["train_orders"] == 0 and diagnostic["train_distinct_products"] == 0
    assert diagnostic["target_catalog_presence"] == 0.0 and diagnostic["cold_start_rate"] == 1.0


def test_end_to_end_metadata_reports_no_promotion():
    meta = _metadata("complement_end_to_end_metadata.json")
    assert meta["bootstrap_replicates"] >= 2000
    assert meta["bootstrap_unit"] == "commande_x_fenetre"
    assert meta["reference"] == "popularite_globale"
    assert meta["promotion"] is False
    assert meta["basket_complement_model"] == "none_validated"
    assert meta["reason"] == "no_complementarity_signal"
    low, high = meta["bootstrap_ndcg10_ci95"]
    assert low <= 0 <= high, "un IC95 entierement positif imposerait une promotion"


# ------------------------------------------------- lectures bornees en memoire


def test_predictions_cover_the_three_windows_without_materialising_the_table():
    windows = pq.read_table(PREDICTIONS, columns=["window"]).column("window").to_pylist()
    assert set(windows) == {2, 3, 4}
    metadata = pq.ParquetFile(PREDICTIONS).metadata
    assert metadata.num_row_groups >= 10, "table non decoupee : lecture non bornee"
    assert metadata.num_rows > 1_000_000


def test_no_duplicate_recommendation_per_order_and_model_window_by_window():
    """Filtrage par fenetre ET par modele AVANT materialisation."""
    checked = 0
    for window in (2, 3, 4):
        for model in MODELS:
            frame = pq.read_table(
                PREDICTIONS, columns=["order_id", "item", "rank"],
                filters=[("window", "=", window), ("model", "=", model)]).to_pandas()
            assert 0 < len(frame) <= MAX_ROWS_MATERIALISED, (window, model, len(frame))
            assert not frame.duplicated(["order_id", "item"]).any(), (window, model)
            assert not frame.duplicated(["order_id", "rank"]).any(), (window, model)
            assert frame["rank"].between(1, 20).all()
            checked += 1
            del frame
    assert checked == 3 * len(MODELS)


def test_masked_target_never_appears_in_its_own_context():
    """Le contexte est stocke une fois par commande : lecture directe et bornee."""
    contexts = pd.read_parquet(CONTEXTS, columns=["window", "order_id", "target",
                                                  "context_items", "n_context"])
    assert len(contexts) < 20_000
    assert set(contexts.window) == {2, 3, 4}
    parsed = contexts.context_items.map(json.loads)
    assert (parsed.map(len) == contexts.n_context).all()
    assert not any(target in items for target, items in zip(contexts.target, parsed))
    assert contexts.n_context.ge(1).all()


def test_recommendations_never_return_a_context_item():
    """Lecture par lots de row groups, une seule fenetre a la fois."""
    contexts = pd.read_parquet(CONTEXTS, columns=["order_id", "target", "context_items"])
    context_map = {order: set(json.loads(items))
                   for order, items in zip(contexts.order_id, contexts.context_items)}
    reader = pq.ParquetFile(PREDICTIONS)
    inspected = 0
    for batch in reader.iter_batches(batch_size=50_000, columns=["order_id", "item", "label"]):
        frame = batch.to_pandas()
        offending = [order for order, item in zip(frame.order_id, frame.item)
                     if item in context_map[order]]
        assert not offending, "un article du contexte a ete recommande"
        inspected += len(frame)
        if inspected >= 200_000:
            break
    assert inspected >= 200_000


def test_label_marks_exactly_the_masked_target():
    frame = pq.read_table(PREDICTIONS, columns=["order_id", "model", "item", "label"],
                          filters=[("window", "=", 4)]).to_pandas()
    contexts = pd.read_parquet(CONTEXTS, columns=["window", "order_id", "target"])
    targets = dict(zip(contexts[contexts.window.eq(4)].order_id,
                       contexts[contexts.window.eq(4)].target))
    positive = frame[frame.label.eq(1)]
    assert (positive.item.astype(str) == positive.order_id.map(targets).astype(str)).all()
    assert positive.groupby(["order_id", "model"], observed=True).size().max() == 1
