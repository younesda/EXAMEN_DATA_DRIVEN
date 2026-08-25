"""Entrainement et evaluation pricing V4 — orchestration complete.

Decoupage temporel : les 65 cohortes hebdomadaires (`experiment_week_index`,
0..64) sont ordonnees ; les six dernieres (59..64) servent de fenetres de test
externes, une a la fois, en respectant l'ordre chronologique (`refit=False`,
mais entrainement recalcule sur tout l'historique disponible avant chaque
fenetre, comme le forecasting V2). Aucun tuning n'utilise les fenetres de test :
les hyperparametres sont fixes a l'avance (memes valeurs pour toutes les
fenetres), ce qui evite tout ajustement sur le futur.
"""
from __future__ import annotations

import hashlib
import json
import time
import tracemalloc
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.pricing_v4 import evaluate as ev
from src.pricing_v4.dataset import ALL_FEATURES, TARGETS, build_dataset, validate_no_forbidden_columns
from src.pricing_v4.models import MODEL_FACTORIES, FittedModel, constrained_ensemble

#: Membres choisis a priori (rationale architecturale, pas par performance sur
#: le test) : T_learner capture l'heterogeneite par bras de traitement propre
#: au design experimental, Hurdle separe explicitement zero/positif (pertinent
#: pour une demande intermittente), Monotone impose le signe economique attendu
#: de la remise. Poids egaux, fixes avant toute observation de fenetre de test.
ENSEMBLE_MEMBERS = ("T_learner", "Hurdle_zero_positif", "LightGBM_Monotone")

SEED = 42
N_TEST_WINDOWS = 6
OUT_MODELS = PROJECT_ROOT / "models" / "v4" / "pricing"
OUT_MANIFESTS = PROJECT_ROOT / "models" / "v4" / "manifests"
OUT_REPORTS = PROJECT_ROOT / "reports" / "v4_training"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fit_all_models(train: pd.DataFrame, target: str) -> dict[str, FittedModel]:
    """Cle par `model.name` (le nom effectivement utilise, ex. CatBoost_MAE pour
    une cible monetaire) et non par la cle de la factory, qui ne varie pas
    selon la cible."""
    fitted = {}
    for _, factory in MODEL_FACTORIES.items():
        started = time.perf_counter()
        model = factory(train, target)
        if model is None:
            continue
        model.train_seconds = time.perf_counter() - started
        fitted[model.name] = model
    return fitted


def _segment_metrics(test: pd.DataFrame, target: str, predictions: np.ndarray) -> list[dict]:
    rows = []
    frame = test.assign(_pred=predictions)
    for key, column in (("categorie", "categorie"), ("classe_abc", "classe_abc"),
                       ("treatment_group", "treatment_group")):
        for value, group in frame.groupby(column):
            metrics = ev.point_metrics(group[target].to_numpy(), group._pred.to_numpy())
            rows.append({"segment_type": key, "segment_value": value, **metrics})
    return rows


def run_target(dataset: pd.DataFrame, target: str) -> dict:
    weeks = sorted(dataset.experiment_week_index.unique())
    test_weeks = weeks[-N_TEST_WINDOWS:]
    per_window_records = []
    segment_records = []
    oos_predictions = []
    fitted_by_window: dict[int, dict[str, FittedModel]] = {}
    timing_records = []

    for window_index, week in enumerate(test_weeks, start=1):
        train = dataset[dataset.experiment_week_index < week]
        test = dataset[dataset.experiment_week_index == week]
        if train.empty or test.empty:
            continue
        tracemalloc.start()
        fitted = _fit_all_models(train, target)
        members = [fitted[name] for name in ENSEMBLE_MEMBERS if name in fitted]
        if len(members) >= 2:
            fitted["Ensemble_contraint"] = constrained_ensemble(
                members, {name: 1.0 for name in ENSEMBLE_MEMBERS})
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        fitted_by_window[week] = fitted

        for name, model in fitted.items():
            predictions = model.predict_fn(test)
            metrics = ev.point_metrics(test[target].to_numpy(), predictions)
            margin = ev.margin_metrics(
                test.assign(_unit_margin=(test.prix_applique_xof - test.cout_xof)),
                predictions, "_unit_margin") if target == "units_sold_window_7j" else {}
            per_window_records.append({
                "window": window_index, "experiment_week_index": int(week), "model": name,
                "target": target, **metrics, **margin,
                "train_seconds": round(getattr(model, "train_seconds", 0.0), 4),
                "peak_memory_mb": round(peak_memory / (1024 * 1024), 3),
            })
            for row in _segment_metrics(test, target, predictions):
                segment_records.append({"window": window_index, "model": name, "target": target, **row})
            oos_predictions.append(pd.DataFrame({
                "decision_id": test.decision_id.to_numpy(), "produit_key": test.produit_key.to_numpy(),
                "window": window_index, "model": name, "target": target,
                "y_true": test[target].to_numpy(), "y_pred": predictions,
            }))
            timing_records.append({"window": window_index, "model": name, "target": target,
                                   "train_seconds": getattr(model, "train_seconds", 0.0),
                                   "peak_memory_mb": peak_memory / (1024 * 1024)})

    per_window = pd.DataFrame(per_window_records)
    segments = pd.DataFrame(segment_records)
    predictions_frame = pd.concat(oos_predictions, ignore_index=True) if oos_predictions else pd.DataFrame()

    summary = (per_window.groupby("model")
              .agg(wape_macro=("wape_micro", "mean"), wape_std=("wape_micro", "std"),
                   mae=("mae", "mean"), rmse=("rmse", "mean"), bias=("forecast_bias", "mean"))
              .reset_index().sort_values("wape_macro"))

    # WAPE micro poolee sur toutes les fenetres.
    pooled = predictions_frame.groupby("model").apply(
        lambda g: ev.wape(g.y_true.to_numpy(), g.y_pred.to_numpy()), include_groups=False)
    summary["wape_micro_pooled"] = summary.model.map(pooled)

    baseline_pool = ["baseline_moyenne_produit", "baseline_mediane_produit"]
    # Reference de comparaison = la MEILLEURE des deux baselines (celle qu'il
    # faut reellement battre), pas systematiquement la moyenne.
    baseline_name = summary.set_index("model").loc[baseline_pool].wape_macro.idxmin()
    challengers = [name for name in summary.model if name not in baseline_pool]
    base_pred = predictions_frame[predictions_frame.model.eq(baseline_name)].set_index(
        ["window", "decision_id"]).y_pred

    bootstrap_results, raw_p_values = {}, {}
    for name in challengers:
        challenger_pred = predictions_frame[predictions_frame.model.eq(name)].set_index(
            ["window", "decision_id"])
        aligned = challenger_pred.join(base_pred.rename("y_pred_base"), how="inner")
        merged_frame = dataset.set_index("decision_id").loc[
            aligned.index.get_level_values("decision_id")].reset_index()
        bootstrap = ev.product_level_bootstrap(
            merged_frame, target, aligned.y_pred.to_numpy(), aligned.y_pred_base.to_numpy())
        bootstrap_results[name] = bootstrap
        raw_p_values[name] = ev.product_level_permutation(
            merged_frame, target, aligned.y_pred.to_numpy(), aligned.y_pred_base.to_numpy(), draws=1000)
    holm = ev.holm_correction(raw_p_values) if raw_p_values else {}

    windows_won = {}
    pivot = per_window.pivot(index="model", columns="window", values="wape_micro")
    for name in summary.model:
        windows_won[name] = int((pivot.loc[name] < pivot.loc[baseline_name]).sum()) if name in pivot.index else 0

    elasticity = None
    if target == "units_sold_window_7j" and not predictions_frame.empty:
        best_by_wape = summary.iloc[0].model
        best_pred = predictions_frame[predictions_frame.model.eq(best_by_wape)]
        merged = dataset.merge(best_pred[["decision_id", "y_pred"]], on="decision_id", how="inner")
        elasticity = ev.synthetic_elasticity_recovery(merged, merged.y_pred.to_numpy())

    guardrails = ev.margin_floor_violations(dataset)

    return {
        "target": target, "per_window": per_window, "segments": segments,
        "predictions": predictions_frame, "summary": summary, "bootstrap": bootstrap_results,
        "raw_p_values": raw_p_values, "holm_p_values": holm, "windows_won": windows_won,
        "elasticity": elasticity, "guardrails": guardrails, "fitted_by_window": fitted_by_window,
        "test_weeks": test_weeks, "timing": pd.DataFrame(timing_records),
    }


def select_final_model(result: dict) -> dict:
    """Applique les criteres de promotion : biais, marge, stabilite, gain vs baseline."""
    summary = result["summary"].set_index("model")
    baseline_pool = ["baseline_moyenne_produit", "baseline_mediane_produit"]
    baseline_wape = float(summary.loc[baseline_pool, "wape_macro"].min())
    best_baseline_name = summary.loc[baseline_pool, "wape_macro"].idxmin()
    candidates = []
    for name in summary.index:
        if name in baseline_pool:
            continue
        row = summary.loc[name]
        bootstrap = result["bootstrap"].get(name, {})
        windows_won = result["windows_won"].get(name, 0)
        relative_gain = (baseline_wape - row.wape_macro) / baseline_wape if baseline_wape else 0.0
        eligible = (
            abs(row.bias) <= 0.10  # tolerance large ; le seuil strict (3%) est verifie separement
            and relative_gain > 0
            and windows_won >= result["per_window"].window.nunique() // 2
            and bootstrap.get("ci95_high", 1) < 0
        )
        candidates.append({"model": name, "wape_macro": float(row.wape_macro),
                           "bias": float(row.bias), "relative_gain_vs_baseline": relative_gain,
                           "windows_won": windows_won,
                           "bias_under_3pct": bool(abs(row.bias) <= 0.03),
                           "bootstrap_ci95_favorable": bool(bootstrap.get("ci95_high", 1) < 0),
                           "eligible": eligible})
    candidates_frame = pd.DataFrame(candidates).sort_values("wape_macro")
    eligible_frame = candidates_frame[candidates_frame.eligible]
    selected = eligible_frame.iloc[0].model if len(eligible_frame) else best_baseline_name
    return {"candidates": candidates_frame.to_dict("records"), "selected_model": selected,
            "best_baseline": best_baseline_name, "best_baseline_wape_macro": baseline_wape}


def _git_commit() -> str:
    import subprocess
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def _raw_manifest_sha() -> dict:
    path = OUT_MANIFESTS / "raw_data_manifest.json"
    if not path.is_file():
        return {}
    return {entry["table"]: entry["sha256"] for entry in json.loads(path.read_text(encoding="utf-8"))["tables"]}


def persist_target(dataset: pd.DataFrame, target: str, result: dict, commit: str, raw_sha: dict) -> dict:
    """Serialise le modele retenu (reentraine sur l'integralite de l'historique),
    ses metriques, ses predictions hors echantillon et son manifeste SHA-256."""
    from src.pricing_v4.models import MODEL_FACTORIES

    selected_name = result["final_selection"]["selected_model"]
    if selected_name == "Ensemble_contraint":
        fitted_members = [MODEL_FACTORIES[name](dataset, target) for name in ENSEMBLE_MEMBERS
                         if name in MODEL_FACTORIES]
        final_model = constrained_ensemble(fitted_members, {name: 1.0 for name in ENSEMBLE_MEMBERS})
    else:
        factory = None
        for _, candidate_factory in MODEL_FACTORIES.items():
            probe = candidate_factory(dataset.head(50), target)
            if probe is not None and probe.name == selected_name:
                factory = candidate_factory
                break
        final_model = factory(dataset, target) if factory else None

    target_dir = OUT_MODELS / target
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / "model.joblib"
    if final_model is not None:
        # `final_model` est un FittedModel : dataclass + composants scikit-learn/
        # LightGBM/CatBoost, tous picklables. La prediction se fait ensuite via
        # `src.pricing_v4.models.predict(loaded_model, frame)` — jamais via une
        # fermeture, qui ne survivrait pas a la serialisation.
        joblib.dump({"fitted_model": final_model, "features": ALL_FEATURES,
                    "target": target, "seed": SEED}, artifact_path)

    predictions_path = target_dir / "oos_predictions.csv"
    result["predictions"].to_csv(predictions_path, index=False, encoding="utf-8")
    per_window_path = target_dir / "per_window_metrics.csv"
    result["per_window"].to_csv(per_window_path, index=False, encoding="utf-8")
    segments_path = target_dir / "segment_metrics.csv"
    result["segments"].to_csv(segments_path, index=False, encoding="utf-8")

    holm = result["holm_p_values"]
    metadata = {
        "target": target, "selected_model": selected_name,
        "status": "synthetic_academic_experiment",
        "seed": SEED, "code_version_git_commit": commit,
        "raw_data_sha256": raw_sha,
        "n_train_full": len(dataset), "n_test_windows": N_TEST_WINDOWS,
        "features": ALL_FEATURES,
        "summary": result["summary"].to_dict("records"),
        "final_selection": {k: v for k, v in result["final_selection"].items() if k != "candidates"},
        "candidates": result["final_selection"]["candidates"],
        "bootstrap_vs_best_baseline": result["bootstrap"],
        "raw_p_values": result["raw_p_values"], "holm_corrected_p_values": holm,
        "windows_won": result["windows_won"],
        "elasticity_recovery_diagnostic": result["elasticity"],
        "guardrails": result["guardrails"],
        "timing": {
            "total_train_seconds": float(result["timing"].train_seconds.sum()),
            "peak_memory_mb_max": float(result["timing"].peak_memory_mb.max()),
        },
    }
    metadata_path = target_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
                             encoding="utf-8", newline="\n")

    model_card = f"""# Model card — pricing V4 — {target}

Statut : `synthetic_academic_experiment`. Donnees synthetiques, projet
academique. Aucune performance commerciale reelle n'est revendiquee.

Modele retenu : `{selected_name}`.
WAPE macro (moyenne des {N_TEST_WINDOWS} fenetres) : {result['summary'].set_index('model').loc[selected_name, 'wape_macro']:.4f}
Biais moyen : {result['summary'].set_index('model').loc[selected_name, 'bias']:+.4f}

Cible : `{target}`. Grain : une decision de tarification hebdomadaire par produit.
Le prix effectivement applique est toujours `prix_applique_xof`, jamais la
remise proposee.

Features utilisees : {', '.join(ALL_FEATURES)}

Features explicitement exclues : `product_impressions` (constante par produit
dans la table livree, ne represente pas un cumul pre-decision), toute variable
posterieure a la decision, les trois cibles elles-memes.

Limites : experience synthetique, remise confondue avec l'identite produit
(assignation persistante par produit), aucune revendication causale, usage
academique et benchmark de pipeline uniquement.
"""
    (target_dir / "MODEL_CARD.md").write_text(model_card, encoding="utf-8", newline="\n")

    manifest = {}
    for path in (artifact_path, predictions_path, per_window_path, segments_path, metadata_path):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest[str(path.relative_to(target_dir))] = digest
    (target_dir / "manifest.sha256.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    return metadata


def main() -> dict:
    OUT_MODELS.mkdir(parents=True, exist_ok=True)
    OUT_MANIFESTS.mkdir(parents=True, exist_ok=True)
    OUT_REPORTS.mkdir(parents=True, exist_ok=True)

    dataset = build_dataset()
    validate_no_forbidden_columns(ALL_FEATURES)
    commit = _git_commit()
    raw_sha = _raw_manifest_sha()

    all_results, comparison_rows = {}, []
    for target in TARGETS:
        print("=== cible:", target, "===")
        result = run_target(dataset, target)
        result["final_selection"] = select_final_model(result)
        all_results[target] = result
        print(result["summary"][["model", "wape_macro", "bias"]].to_string(index=False))
        print("modele retenu:", result["final_selection"]["selected_model"])
        print()
        persist_target(dataset, target, result, commit, raw_sha)
        for row in result["summary"].to_dict("records"):
            comparison_rows.append({"domain": "pricing", "target": target, **row})

    pd.DataFrame(comparison_rows).to_csv(
        OUT_REPORTS / "03_model_comparison_pricing.csv", index=False, encoding="utf-8")

    return all_results


if __name__ == "__main__":
    RESULTS = main()
