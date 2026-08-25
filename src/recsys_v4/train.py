"""Entrainement et evaluation recommandation V4 — orchestration complete.

Decoupage temporel : les 78 semaines d'exposition (`impression_week`) sont
regroupees en 6 fenetres d'environ 13 semaines ; les quatre dernieres servent
de fenetres de test externes, en ordre chronologique. Aucun tuning n'utilise
les fenetres de test.

Deux familles de metriques, jamais confondues :

* candidate-set — reclassement des 5 candidats d'une slate par chaque modele,
  a partir de features strictement pre-impression ;
* bout en bout (as-served) — la liste REELLEMENT servie, via le rang loggue,
  qui decrit la politique historique (`popularite_globale_v1` en controle,
  `challenger_affinite_categorie_v1` en traitement) sans jamais servir de
  feature d'entrainement.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import tracemalloc
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.recsys_v4 import evaluate as ev
from src.recsys_v4.dataset import ALL_FEATURES, TARGETS, build_dataset, validate_no_forbidden_columns
from src.recsys_v4.models import SIMPLE_FACTORIES, FittedModel, rrf

SEED = 42
N_WINDOWS = 6
N_TEST_WINDOWS = 4
BASELINE_NAME = "popularite_globale_v1"
RRF_MEMBERS = ("popularite_globale_v1", "popularite_categorie", "cooccurrence")
OUT_MODELS = PROJECT_ROOT / "models" / "v4" / "recommendation"
OUT_MANIFESTS = PROJECT_ROOT / "models" / "v4" / "manifests"
OUT_REPORTS = PROJECT_ROOT / "reports" / "v4_training"


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def _raw_manifest_sha() -> dict:
    path = OUT_MANIFESTS / "raw_data_manifest.json"
    if not path.is_file():
        return {}
    return {entry["table"]: entry["sha256"] for entry in json.loads(path.read_text(encoding="utf-8"))["tables"]}


def assign_windows(dataset: pd.DataFrame) -> pd.Series:
    max_week = dataset.impression_week.max()
    bin_size = max(1, (max_week + 1) // N_WINDOWS)
    return (dataset.impression_week // bin_size).clip(upper=N_WINDOWS - 1)


def _fit_all_models(train: pd.DataFrame, target: str, cutoff) -> dict[str, FittedModel]:
    fitted = {}
    for name, factory in SIMPLE_FACTORIES.items():
        started = time.perf_counter()
        model = factory(train, target, cutoff)
        if model is None:
            continue
        model.train_seconds = time.perf_counter() - started
        fitted[model.name] = model
    members = [fitted[name] for name in RRF_MEMBERS if name in fitted]
    if len(members) >= 2:
        fitted["RRF"] = rrf(train, target, cutoff, members)
    return fitted


def run_target(dataset: pd.DataFrame, target: str) -> dict:
    windows = sorted(dataset.window.unique())
    test_windows = windows[-N_TEST_WINDOWS:]
    per_window_records, oos_scores, timing_records = [], [], []
    as_served_records = []

    for window_index, window in enumerate(test_windows, start=1):
        train = dataset[dataset.window < window]
        test = dataset[dataset.window.eq(window)]
        if train.empty or test.empty:
            continue
        cutoff = test.impression_timestamp.min()
        tracemalloc.start()
        fitted = _fit_all_models(train, target, cutoff)
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        for name, model in fitted.items():
            scores = model.score(test)
            scored = test[["slate_id", "produit_key", "identity_key", "categorie",
                          "experiment_group", target]].assign(_score=scores)
            per_slate = ev.slate_metrics(scored, "_score", target)
            per_slate["identity_key"] = scored.groupby("slate_id").identity_key.first().reindex(
                per_slate.slate_id).to_numpy()
            summary = ev.aggregate_summary(per_slate)
            coverage = ev.coverage_diversity_novelty(
                per_slate, train.groupby("produit_key").size(), dataset.produit_key.nunique())
            per_window_records.append({"window": window_index, "model": name, "target": target,
                                       **summary, **coverage,
                                       "train_seconds": round(getattr(model, "train_seconds", 0.0), 4),
                                       "peak_memory_mb": round(peak_memory / (1024 * 1024), 3)})
            oos_scores.append(per_slate.assign(window=window_index, model=name, target=target))
            timing_records.append({"window": window_index, "model": name, "target": target,
                                   "train_seconds": getattr(model, "train_seconds", 0.0),
                                   "peak_memory_mb": peak_memory / (1024 * 1024)})

        for group_value, group in test.groupby("experiment_group"):
            served = ev.as_served_metrics(group, target)
            served_summary = ev.aggregate_summary(served)
            as_served_records.append({"window": window_index, "experiment_group": group_value,
                                      "target": target, "n_slates": len(served), **served_summary})

    per_window = pd.DataFrame(per_window_records)
    oos = pd.concat(oos_scores, ignore_index=True) if oos_scores else pd.DataFrame()
    as_served = pd.DataFrame(as_served_records)

    summary = (per_window.groupby("model")
              .agg(**{f"{metric}_mean": (metric, "mean") for metric in
                     ("recall@5", "recall@10", "recall@20", "ndcg@5", "ndcg@10", "ndcg@20",
                      "hitrate@10", "mrr", "map@10", "coverage_catalogue", "diversite",
                      "nouveaute", "concentration_top10")})
              .reset_index().sort_values("ndcg@10_mean", ascending=False))

    challengers = [name for name in summary.model if name != BASELINE_NAME]
    bootstrap_results, raw_p_values = {}, {}
    baseline_oos = oos[oos.model.eq(BASELINE_NAME)]
    for name in challengers:
        challenger_oos = oos[oos.model.eq(name)]
        common_windows = set(challenger_oos.window) & set(baseline_oos.window)
        merged_a = challenger_oos[challenger_oos.window.isin(common_windows)]
        merged_b = baseline_oos[baseline_oos.window.isin(common_windows)]
        if merged_a.empty or merged_b.empty:
            continue
        bootstrap_results[name] = ev.bootstrap_ci95(merged_a, merged_b, "identity_key", "ndcg@10")
        raw_p_values[name] = _permutation_p_value(merged_a, merged_b, "identity_key", "ndcg@10")
    holm = ev.holm_correction(raw_p_values) if raw_p_values else {}

    pivot = per_window.pivot(index="model", columns="window", values="ndcg@10")
    windows_won = {name: int((pivot.loc[name] > pivot.loc[BASELINE_NAME]).sum())
                  if name in pivot.index and BASELINE_NAME in pivot.index else 0
                  for name in summary.model}

    return {"target": target, "per_window": per_window, "summary": summary,
            "predictions": oos, "as_served": as_served, "bootstrap": bootstrap_results,
            "raw_p_values": raw_p_values, "holm_p_values": holm, "windows_won": windows_won,
            "timing": pd.DataFrame(timing_records), "test_windows": test_windows}


def _permutation_p_value(challenger: pd.DataFrame, baseline: pd.DataFrame, group_col: str,
                         metric: str, draws: int = 1000, seed: int = SEED) -> float:
    merged = challenger[[group_col, "slate_id", metric]].rename(columns={metric: "a"}).merge(
        baseline[[group_col, "slate_id", metric]].rename(columns={metric: "b"}), on=["slate_id", group_col])
    codes, _ = pd.factorize(merged[group_col].to_numpy())
    n_groups = codes.max() + 1
    diff = (merged.a - merged.b).to_numpy()
    sum_a = np.bincount(codes, weights=merged.a.to_numpy(), minlength=n_groups)
    sum_b = np.bincount(codes, weights=merged.b.to_numpy(), minlength=n_groups)
    counts = np.maximum(np.bincount(codes, minlength=n_groups), 1)
    observed = float((sum_a.sum() - sum_b.sum()) / counts.sum())
    rng = np.random.default_rng(seed)
    swap = rng.random((draws, n_groups)) < 0.5
    swapped_a = np.where(swap, sum_b, sum_a)
    swapped_b = np.where(swap, sum_a, sum_b)
    stats = (swapped_a.sum(axis=1) - swapped_b.sum(axis=1)) / counts.sum()
    extreme = int((np.abs(stats) >= abs(observed)).sum())
    return (extreme + 1) / (draws + 1)


def select_final_model(result: dict) -> dict:
    summary = result["summary"].set_index("model")
    if BASELINE_NAME not in summary.index:
        return {"selected_model": BASELINE_NAME, "candidates": [], "reason": "baseline absente"}
    baseline_ndcg = float(summary.loc[BASELINE_NAME, "ndcg@10_mean"])
    baseline_recall = float(summary.loc[BASELINE_NAME, "recall@10_mean"])
    candidates = []
    for name in summary.index:
        if name == BASELINE_NAME:
            continue
        row = summary.loc[name]
        bootstrap = result["bootstrap"].get(name, {})
        relative_ndcg_gain = (row["ndcg@10_mean"] - baseline_ndcg) / baseline_ndcg if baseline_ndcg else 0.0
        relative_recall_change = (row["recall@10_mean"] - baseline_recall) / baseline_recall if baseline_recall else 0.0
        windows_won = result["windows_won"].get(name, 0)
        eligible = (relative_ndcg_gain >= 0.05 and relative_recall_change >= -0.02
                   and windows_won >= 3 and bootstrap.get("ci95_low", -1) > 0)
        candidates.append({"model": name, "ndcg@10": float(row["ndcg@10_mean"]),
                           "recall@10": float(row["recall@10_mean"]),
                           "relative_ndcg_gain": relative_ndcg_gain,
                           "relative_recall_change": relative_recall_change,
                           "windows_won": windows_won,
                           "coverage_catalogue": float(row["coverage_catalogue_mean"]),
                           "diversite": float(row["diversite_mean"]),
                           "bootstrap_ci95_favorable": bool(bootstrap.get("ci95_low", -1) > 0),
                           "eligible": eligible})
    candidates_frame = pd.DataFrame(candidates).sort_values("ndcg@10", ascending=False)
    eligible_frame = candidates_frame[candidates_frame.eligible] if len(candidates_frame) else candidates_frame
    selected = eligible_frame.iloc[0].model if len(eligible_frame) else BASELINE_NAME
    return {"candidates": candidates_frame.to_dict("records"), "selected_model": selected,
            "baseline": BASELINE_NAME, "baseline_ndcg10": baseline_ndcg}


def persist_target(dataset: pd.DataFrame, target: str, result: dict, commit: str, raw_sha: dict) -> dict:
    selected_name = result["final_selection"]["selected_model"]
    cutoff = dataset.impression_timestamp.max()
    if selected_name == "RRF":
        members = [SIMPLE_FACTORIES[name](dataset, target, cutoff) for name in RRF_MEMBERS
                  if name in SIMPLE_FACTORIES]
        final_model = rrf(dataset, target, cutoff, members)
    else:
        factory = SIMPLE_FACTORIES.get(selected_name)
        final_model = factory(dataset, target, cutoff) if factory else None
        if final_model is None and selected_name != BASELINE_NAME:
            final_model = None
        elif selected_name == BASELINE_NAME:
            final_model = SIMPLE_FACTORIES[BASELINE_NAME](dataset, target, cutoff)

    target_dir = OUT_MODELS / target
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / "model.joblib"
    if final_model is not None:
        joblib.dump({"fitted_model": final_model, "features": ALL_FEATURES, "target": target, "seed": SEED},
                   artifact_path)

    predictions_path = target_dir / "oos_predictions.csv"
    result["predictions"].drop(columns=["identity_key"], errors="ignore").to_csv(
        predictions_path, index=False, encoding="utf-8")
    per_window_path = target_dir / "per_window_metrics.csv"
    result["per_window"].to_csv(per_window_path, index=False, encoding="utf-8")
    as_served_path = target_dir / "as_served_metrics.csv"
    result["as_served"].to_csv(as_served_path, index=False, encoding="utf-8")

    metadata = {
        "target": target, "selected_model": selected_name,
        "status": "synthetic_academic_experiment", "seed": SEED,
        "code_version_git_commit": commit, "raw_data_sha256": raw_sha,
        "n_impressions_full": len(dataset), "n_test_windows": N_TEST_WINDOWS,
        "features": ALL_FEATURES, "summary": result["summary"].to_dict("records"),
        "final_selection": {k: v for k, v in result["final_selection"].items() if k != "candidates"},
        "candidates": result["final_selection"]["candidates"],
        "bootstrap_vs_baseline": result["bootstrap"], "raw_p_values": result["raw_p_values"],
        "holm_corrected_p_values": result["holm_p_values"], "windows_won": result["windows_won"],
        "timing": {"total_train_seconds": float(result["timing"].train_seconds.sum()),
                  "peak_memory_mb_max": float(result["timing"].peak_memory_mb.max())},
    }
    metadata_path = target_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
                             encoding="utf-8", newline="\n")

    model_card = f"""# Model card — recommandation V4 — {target}

Statut : `synthetic_academic_experiment`. Donnees synthetiques, projet
academique. Aucune performance commerciale reelle n'est revendiquee.

Modele retenu : `{selected_name}`.
NDCG@10 moyen : {result['summary'].set_index('model').loc[selected_name, 'ndcg@10_mean']:.4f}
Recall@10 moyen : {result['summary'].set_index('model').loc[selected_name, 'recall@10_mean']:.4f}

Cible : `{target}`. Grain : reclassement des 5 candidats d'une slate.

Features utilisees : {', '.join(ALL_FEATURES)}

Features explicitement exclues : `rank`, `model_score` (encodent la politique
qui a produit l'exposition ; usage reserve a l'evaluation « bout en bout » de
la liste servie), toute variable posterieure a l'impression, les trois cibles
elles-memes, `clicked` (absente de la semantique V4).

`exposure_probability_status = deterministic_top_k` : la selection reelle des
5 candidats est deterministe (Top-5 par score), pas un tirage selon le softmax
theorique de `product_exposure_probability`. Cette propension n'est jamais
utilisee comme poids IPS.

Limites : experience synthetique, aucune revendication causale, usage
academique et benchmark de pipeline uniquement.
"""
    (target_dir / "MODEL_CARD.md").write_text(model_card, encoding="utf-8", newline="\n")

    manifest = {}
    for path in (artifact_path, predictions_path, per_window_path, as_served_path, metadata_path):
        if path.is_file():
            manifest[str(path.relative_to(target_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (target_dir / "manifest.sha256.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return metadata


def main() -> dict:
    OUT_MODELS.mkdir(parents=True, exist_ok=True)
    OUT_MANIFESTS.mkdir(parents=True, exist_ok=True)
    OUT_REPORTS.mkdir(parents=True, exist_ok=True)

    dataset = build_dataset()
    validate_no_forbidden_columns(ALL_FEATURES)
    dataset["window"] = assign_windows(dataset)
    commit = _git_commit()
    raw_sha = _raw_manifest_sha()

    all_results, comparison_rows = {}, []
    for target in TARGETS:
        print("=== cible:", target, "===")
        result = run_target(dataset, target)
        result["final_selection"] = select_final_model(result)
        all_results[target] = result
        print(result["summary"][["model", "ndcg@10_mean", "recall@10_mean"]].to_string(index=False))
        print("modele retenu:", result["final_selection"]["selected_model"])
        print()
        persist_target(dataset, target, result, commit, raw_sha)
        for row in result["summary"].to_dict("records"):
            comparison_rows.append({"domain": "recommendation", "target": target, **row})

    pd.DataFrame(comparison_rows).to_csv(
        OUT_REPORTS / "03_model_comparison_recommendation.csv", index=False, encoding="utf-8")
    return all_results


if __name__ == "__main__":
    RESULTS = main()
