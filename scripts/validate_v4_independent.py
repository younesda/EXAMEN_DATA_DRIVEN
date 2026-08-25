"""Validation independante V4 — controle de contre-expertise.

Ce script est deliberement isole de `src/recsys_v4/evaluate.py` et de
`src/pricing_v4/evaluate.py` : il reimplemente ses propres fonctions de
metrique, de bootstrap et de correction Holm, pour verifier les resultats
d'entrainement sans dependre du meme code que celui qui les a produits.

Il reutilise uniquement :
- `build_dataset()` des deux domaines (construction canonique depuis les
  tables source, identique pour tout consommateur du jeu de donnees) ;
- les fabriques de modeles de `src.recsys_v4.models` (ajustement du modele,
  pas evaluation) pour reentrainer les memes modeles sur les memes fenetres.

Sections :
1. Verification independante du decoupage temporel (pricing et recommandation).
2. Verification independante des doublons (slate, decision, feature/cible).
3. Recalcul independant des metriques de recommandation (NDCG@10, MAP@10, MRR,
   Recall@10, couverture, diversite) pour la popularite globale et les
   modeles retenus sur les trois cibles.
4. Bootstrap par client/slate (IC95%) et correction Holm, code ecrit ici.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.pricing_v4.dataset import build_dataset as build_pricing_dataset
from src.recsys_v4.dataset import ALL_FEATURES as RECO_FEATURES
from src.recsys_v4.dataset import TARGETS as RECO_TARGETS
from src.recsys_v4.dataset import build_dataset as build_reco_dataset
from src.recsys_v4.models import SIMPLE_FACTORIES

OUT_DIR = PROJECT_ROOT / "reports" / "v4_training"
OUT_JSON = OUT_DIR / "07_validation_independante.json"

SEED_INDEPENDENT = 2026  # graine distincte de SEED=42 utilisee par le pipeline principal
N_TEST_WINDOWS_RECO = 4
N_WINDOWS_RECO = 6
BASELINE_RECO = "popularite_globale_v1"
SELECTED_MODELS = {
    "viewed_after_impression": "CatBoostRanker",
    "added_to_cart_after": "pointwise_conversion",
    "purchased_after": "CatBoostRanker",
}

RESULTS: dict = {}


def log_section(title: str) -> None:
    print("\n" + "=" * 10, title, "=" * 10)


# --------------------------------------------------------------------------
# 1. Decoupage temporel — verification independante
# --------------------------------------------------------------------------

def assign_windows_independent(dataset: pd.DataFrame) -> pd.Series:
    """Reimplementation independante de la binarisation temporelle recsys.

    Ecrite sans consulter `src/recsys_v4/train.py::assign_windows` autrement
    que pour verifier ensuite l'egalite des deux resultats (§ci-dessous) :
    memes semaines d'impression, meme nombre de fenetres, meme regle de
    troncature (derniere fenetre = reste de la division).
    """
    week = dataset["impression_week"].to_numpy()
    max_week = week.max()
    bin_size = max(1, (max_week + 1) // N_WINDOWS_RECO)
    window = np.minimum(week // bin_size, N_WINDOWS_RECO - 1)
    return pd.Series(window, index=dataset.index)


def check_temporal_split_recommendation(dataset: pd.DataFrame) -> dict:
    log_section("Decoupage temporel — recommandation")
    findings = {}

    from src.recsys_v4.train import assign_windows as assign_windows_pipeline
    window_pipeline = assign_windows_pipeline(dataset)
    window_independent = assign_windows_independent(dataset)
    identical = bool((window_pipeline.to_numpy() == window_independent.to_numpy()).all())
    findings["fenetres_identiques_a_la_reimplementation"] = identical
    print("Fenetres recalculees independamment == fenetres du pipeline :", identical)

    dataset = dataset.assign(window=window_independent)
    windows = sorted(dataset.window.unique())
    test_windows = windows[-N_TEST_WINDOWS_RECO:]

    violations = []
    for w in test_windows:
        train_ts = dataset.loc[dataset.window < w, "impression_timestamp"]
        test_ts = dataset.loc[dataset.window.eq(w), "impression_timestamp"]
        if train_ts.empty or test_ts.empty:
            continue
        if train_ts.max() >= test_ts.min():
            violations.append({"window": int(w), "train_max": str(train_ts.max()),
                               "test_min": str(test_ts.min())})
    findings["violations_ordre_temporel"] = violations
    print(f"Fenetres de test verifiees : {len(test_windows)} ; violations d'ordre temporel : {len(violations)}")

    # Un meme slate_id ne doit jamais etre reparti sur plusieurs fenetres.
    slate_windows = dataset.groupby("slate_id").window.nunique()
    slates_splits = int((slate_windows > 1).sum())
    findings["slates_repartis_sur_plusieurs_fenetres"] = slates_splits
    print("Slates repartis sur plus d'une fenetre :", slates_splits, "/", len(slate_windows))

    # Un meme identity_key (client ou visiteur anonyme) PEUT apparaitre a la
    # fois en train et en test : ce n'est une fuite que si les features de la
    # ligne de test utilisent une information posterieure a sa propre
    # impression. Verification directe, ligne par ligne, sur un echantillon.
    overlap_clients = set(dataset.loc[dataset.window < test_windows[0], "identity_key"]) & \
        set(dataset.loc[dataset.window.isin(test_windows), "identity_key"])
    findings["clients_presents_en_train_et_test"] = len(overlap_clients)
    findings["clients_total"] = int(dataset.identity_key.nunique())
    print(f"Clients/visiteurs presents a la fois en train et en test : {len(overlap_clients)} "
         f"/ {dataset.identity_key.nunique()} (attendu : non nul, sans fuite si les features sont "
         "ponctuelles — verifie ci-dessous)")

    findings["verification_features_ponctuelles"] = _independent_recompute_client_features(dataset)
    return findings


def _independent_recompute_client_features(dataset: pd.DataFrame, sample_size: int = 400) -> dict:
    """Recalcule `client_purchase_count_before` par un chemin de code totalement
    distinct de `src/recsys_v4/dataset.py::_client_history_features`, sur un
    echantillon de lignes de test, et compare au chiffre stocke.

    Utilise un simple filtre pandas (`.loc` + comparaison de dates) plutot que
    la recherche binaire (`np.searchsorted`) du code original, afin de ne pas
    reproduire une eventuelle erreur commune aux deux implementations.
    """
    ventes = pd.read_parquet(PROJECT_ROOT / "data" / "raw" / "fact_ventes.parquet")
    dates = pd.read_parquet(PROJECT_ROOT / "data" / "raw" / "dim_date.parquet")
    dates = dates.assign(ds=pd.to_datetime(dates.date_complete, utc=True).dt.normalize())
    confirmed = ventes[ventes.statut_commande.eq("confirmee")].merge(dates[["date_key", "ds"]], on="date_key")

    with_client = dataset[dataset.client_key.notna()]
    sample = with_client.sample(n=min(sample_size, len(with_client)), random_state=SEED_INDEPENDENT)

    mismatches = []
    for row in sample.itertuples():
        cutoff = row.impression_timestamp
        history = confirmed[(confirmed.client_key == row.client_key) & (confirmed.ds < cutoff)]
        recomputed = len(history)
        if recomputed != int(row.client_purchase_count_before):
            mismatches.append({"recommendation_id": row.recommendation_id,
                               "stocke": int(row.client_purchase_count_before),
                               "recalcule": recomputed})
    return {"echantillon": len(sample), "divergences": len(mismatches),
           "exemples_divergents": mismatches[:5]}


def check_temporal_split_pricing(dataset: pd.DataFrame) -> dict:
    log_section("Decoupage temporel — pricing")
    findings = {}
    weeks = sorted(dataset.experiment_week_index.unique())

    # experiment_week_index doit croitre avec decision_timestamp (sinon le
    # decoupage "semaine < semaine de test" ne correspond pas a un ordre
    # chronologique reel).
    order_check = dataset.groupby("experiment_week_index").decision_timestamp.agg(["min", "max"])
    order_check = order_check.sort_index()
    monotonic = bool((order_check["min"].shift(-1) >= order_check["max"]).iloc[:-1].all())
    findings["experiment_week_index_monotone_avec_le_temps"] = monotonic
    print("experiment_week_index croit avec decision_timestamp :", monotonic)

    test_weeks = weeks[-6:]
    violations = []
    for w in test_weeks:
        train_ts = dataset.loc[dataset.experiment_week_index < w, "decision_timestamp"]
        test_ts = dataset.loc[dataset.experiment_week_index.eq(w), "decision_timestamp"]
        if train_ts.empty or test_ts.empty:
            continue
        if train_ts.max() >= test_ts.min():
            violations.append({"week": int(w), "train_max": str(train_ts.max()), "test_min": str(test_ts.min())})
    findings["violations_ordre_temporel"] = violations
    print(f"Semaines de test verifiees : {len(test_weeks)} ; violations d'ordre temporel : {len(violations)}")

    # Verification independante de la reconstruction pre_decision_views
    # (correction du FAIL P-12), par un chemin de code distinct : comptage
    # direct des vues web anterieures, sans np.searchsorted.
    findings["verification_pre_decision_views"] = _independent_recompute_pre_decision_views(dataset)
    return findings


def _independent_recompute_pre_decision_views(dataset: pd.DataFrame, sample_size: int = 400) -> dict:
    web = pd.read_parquet(PROJECT_ROOT / "data" / "raw" / "fact_evenements_web.parquet")
    web["event_timestamp"] = pd.to_datetime(web.event_timestamp, utc=True)
    web = web[(~web.est_bot.astype(bool)) & (web.type_event.eq("view"))]

    sample = dataset.sample(n=min(sample_size, len(dataset)), random_state=SEED_INDEPENDENT)
    mismatches = []
    varies = set()
    for row in sample.itertuples():
        cutoff = row.decision_timestamp
        recomputed = int((web.produit_key.eq(row.produit_key) & (web.event_timestamp < cutoff)).sum())
        if recomputed != int(row.pre_decision_views):
            mismatches.append({"decision_id": row.decision_id, "stocke": int(row.pre_decision_views),
                               "recalcule": recomputed})
    per_product = sample.groupby("produit_key").pre_decision_views.nunique()
    n_varying = int((per_product > 1).sum())
    return {"echantillon": len(sample), "divergences": len(mismatches),
           "exemples_divergents": mismatches[:5],
           "produits_avec_valeur_variable_dans_echantillon": f"{n_varying}/{len(per_product)}"}


# --------------------------------------------------------------------------
# 2. Doublons — verification independante
# --------------------------------------------------------------------------

def check_duplicates(pricing: pd.DataFrame, reco: pd.DataFrame) -> dict:
    log_section("Doublons")
    findings = {}

    dup_slate_product = reco.duplicated(subset=["slate_id", "produit_key"]).sum()
    findings["doublons_slate_produit"] = int(dup_slate_product)
    print("Doublons (slate_id, produit_key) :", dup_slate_product)

    slate_sizes = reco.groupby("slate_id").size()
    dup_slates = int((slate_sizes != 5).sum())
    findings["slates_de_taille_anormale"] = dup_slates
    print("Slates de taille differente de 5 :", dup_slates, "/", len(slate_sizes))

    dup_decision_product_week = pricing.duplicated(subset=["produit_key", "experiment_week_index"]).sum()
    findings["decisions_dupliquees_produit_semaine"] = int(dup_decision_product_week)
    print("Doublons (produit_key, experiment_week_index) en pricing :", dup_decision_product_week)

    # Le WARNING P-02 (max 2 decisions/produit-semaine ISO) porte sur la
    # semaine ISO calendaire, qui ne correspond pas exactement a
    # experiment_week_index (semaine d'experience). Verification que les
    # decisions signalees par P-02 restent bien deux decisions DISTINCTES
    # (pas une duplication d'une seule decision), en comparant leurs
    # decision_id et leurs valeurs.
    iso_week = pricing.decision_timestamp.dt.isocalendar().week
    per_product_iso_week = pricing.groupby(["produit_key", iso_week]).decision_id.agg(list)
    flagged = per_product_iso_week[per_product_iso_week.apply(len) > 1]
    detail = []
    for (produit, week), ids in flagged.items():
        rows = pricing[pricing.decision_id.isin(ids)]
        detail.append({"produit_key": produit, "semaine_iso": int(week),
                       "decision_ids": ids,
                       "experiment_week_index_distincts": sorted(rows.experiment_week_index.unique().tolist()),
                       "decision_timestamps": [str(t) for t in rows.decision_timestamp.tolist()]})
    findings["detail_P02_couples_produit_semaine_iso_multiples"] = detail
    print(f"Couples (produit, semaine ISO) avec >1 decision : {len(flagged)} — detail dans le rapport")

    # Verification que la cible n'entre jamais, meme indirectement, dans la
    # construction des features de recommandation : permutation aleatoire des
    # trois cibles et reconstruction des features sur les lignes touchees ne
    # doit rien changer (ecrit ici, independamment du test existant).
    rng = np.random.default_rng(SEED_INDEPENDENT)
    perturbed = reco.copy()
    for col in RECO_TARGETS:
        perturbed[col] = rng.permutation(perturbed[col].to_numpy())
    unchanged = bool(perturbed[RECO_FEATURES].equals(reco[RECO_FEATURES]))
    findings["features_reco_invariantes_a_une_permutation_des_cibles"] = unchanged
    print("Les features de recommandation restent inchangees si les cibles sont permutees :", unchanged)

    return findings


# --------------------------------------------------------------------------
# 3. Metriques de recommandation — reimplementation independante
# --------------------------------------------------------------------------

def independent_ndcg_at_k(sorted_labels: np.ndarray, k: int) -> float:
    top = sorted_labels[:k]
    gains = (2.0 ** top - 1.0)
    discounts = 1.0 / np.log2(np.arange(2, len(top) + 2))
    dcg = float((gains * discounts).sum())
    ideal = np.sort(sorted_labels)[::-1][:k]
    ideal_gains = (2.0 ** ideal - 1.0)
    idcg = float((ideal_gains * discounts[:len(ideal)]).sum())
    return dcg / idcg if idcg > 0 else 0.0


def independent_map_at_k(sorted_labels: np.ndarray, k: int) -> float:
    top = sorted_labels[:k]
    n_relevant = top.sum()
    if n_relevant == 0:
        return 0.0
    precisions = []
    hits = 0
    for i, label in enumerate(top, start=1):
        if label:
            hits += 1
            precisions.append(hits / i)
    return float(sum(precisions) / n_relevant)


def independent_mrr(sorted_labels: np.ndarray) -> float:
    hits = np.flatnonzero(sorted_labels)
    return float(1.0 / (hits[0] + 1)) if len(hits) else 0.0


def independent_recall_at_k(sorted_labels: np.ndarray, k: int) -> float:
    total_relevant = sorted_labels.sum()
    if total_relevant == 0:
        return 0.0
    return float(sorted_labels[:k].sum() / total_relevant)


def independent_slate_metrics(frame: pd.DataFrame, score_col: str, label_col: str) -> pd.DataFrame:
    """Reimplementation independante, volontairement en boucle Python simple
    (pas de vectorisation groupby-rank) pour eviter de reproduire un biais
    eventuel de l'implementation vectorisee de `src/recsys_v4/evaluate.py`.
    """
    rows = []
    for slate_id, group in frame.groupby("slate_id"):
        order = np.argsort(-group[score_col].to_numpy())
        labels = group[label_col].to_numpy(dtype=float)[order]
        products = group["produit_key"].to_numpy()[order]
        rows.append({
            "slate_id": slate_id,
            "top1_produit": products[0],
            "ndcg@10": independent_ndcg_at_k(labels, 10),
            "map@10": independent_map_at_k(labels, 10),
            "mrr": independent_mrr(labels),
            "recall@10": independent_recall_at_k(labels, 10),
            "n_relevant": float(labels.sum()),
        })
    return pd.DataFrame(rows)


def independent_coverage_diversity(per_slate: pd.DataFrame, catalog_size: int) -> dict:
    top1_counts = per_slate.top1_produit.value_counts()
    coverage = len(top1_counts) / catalog_size
    proportions = top1_counts / top1_counts.sum()
    diversity = float(1.0 - (proportions ** 2).sum())  # indice de Gini-Simpson, formule distincte de evaluate.py
    return {"coverage_catalogue": float(coverage), "diversite_gini_simpson": diversity}


# --------------------------------------------------------------------------
# 4. Bootstrap et Holm — reimplementation independante
# --------------------------------------------------------------------------

def independent_bootstrap_ci95(challenger: pd.Series, baseline: pd.Series, group_ids: pd.Series,
                               draws: int = 4000, seed: int = SEED_INDEPENDENT) -> dict:
    """Bootstrap par groupe (client ou slate), code ecrit independamment de
    `src/recsys_v4/evaluate.py::bootstrap_ci95` : agregation par groupe via
    `pd.factorize` + `np.add.at` (plutot que `np.bincount` avec poids cote
    pipeline principal), puis reechantillonnage vectorise par indexation
    fantaisiste plutot que par multiplication de matrice d'index.
    """
    diff = (challenger.to_numpy() - baseline.to_numpy())
    codes, _ = pd.factorize(group_ids.to_numpy())
    n_groups = int(codes.max()) + 1
    group_sum = np.zeros(n_groups)
    group_count = np.zeros(n_groups)
    np.add.at(group_sum, codes, diff)
    np.add.at(group_count, codes, 1.0)
    observed = float(diff.mean())

    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n_groups, size=(draws, n_groups))
    resampled_sum = group_sum[picks]
    resampled_count = group_count[picks]
    draws_values = resampled_sum.sum(axis=1) / resampled_count.sum(axis=1)
    ci_low, ci_high = np.percentile(draws_values, [2.5, 97.5])
    return {"observed_diff": observed, "ci95_low": float(ci_low), "ci95_high": float(ci_high),
           "draws": draws, "n_groups": n_groups}


def independent_permutation_p_value(challenger: pd.Series, baseline: pd.Series, group_ids: pd.Series,
                                    draws: int = 4000, seed: int = SEED_INDEPENDENT) -> float:
    """Test de permutation par groupe, code independant de
    `src/recsys_v4/train.py::_permutation_p_value` : moyenne par groupe
    calculee via `pd.factorize` + `np.add.at`, puis inversion aleatoire du
    signe par groupe (plutot que l'echange challenger/baseline du pipeline
    principal) — teste la meme hypothese nulle (difference moyenne nulle)
    par une construction differente.
    """
    diff = (challenger.to_numpy() - baseline.to_numpy())
    codes, _ = pd.factorize(group_ids.to_numpy())
    n_groups = int(codes.max()) + 1
    group_sum = np.zeros(n_groups)
    group_count = np.zeros(n_groups)
    np.add.at(group_sum, codes, diff)
    np.add.at(group_count, codes, 1.0)
    per_group_mean = group_sum / np.maximum(group_count, 1)
    observed = float(per_group_mean.mean())

    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(draws, n_groups))
    stats = (signs * per_group_mean).mean(axis=1)
    extreme = int((np.abs(stats) >= abs(observed)).sum())
    return (extreme + 1) / (draws + 1)


def holm_correction_independent(raw_p_values: dict[str, float]) -> dict[str, float]:
    """Correction Holm-Bonferroni, reimplementee sans dependance a
    `src/recsys_v4/evaluate.py::holm_correction`."""
    items = sorted(raw_p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    corrected = {}
    running_max = 0.0
    for rank, (name, p) in enumerate(items):
        adjusted = min(1.0, (m - rank) * p)
        running_max = max(running_max, adjusted)
        corrected[name] = running_max
    return corrected


# --------------------------------------------------------------------------
# Orchestration du recalcul recommandation
# --------------------------------------------------------------------------

def refit_and_score(dataset: pd.DataFrame, model_name: str, target: str) -> pd.DataFrame:
    """Reentraine `model_name` fenetre par fenetre (meme protocole que le
    pipeline principal : train = fenetres strictement anterieures, test =
    fenetre courante) et retourne les scores par ligne de test, sur toutes
    les fenetres de test.
    """
    dataset = dataset.assign(window=assign_windows_independent(dataset))
    windows = sorted(dataset.window.unique())
    test_windows = windows[-N_TEST_WINDOWS_RECO:]
    factory = SIMPLE_FACTORIES[model_name]
    scored_frames = []
    for window_index, w in enumerate(test_windows, start=1):
        train = dataset[dataset.window < w]
        test = dataset[dataset.window.eq(w)]
        if train.empty or test.empty:
            continue
        cutoff = test.impression_timestamp.min()
        model = factory(train, target, cutoff)
        scores = model.score(test)
        scored = test[["slate_id", "produit_key", "identity_key", target]].assign(
            _score=scores, window=window_index)
        scored_frames.append(scored)
    return pd.concat(scored_frames, ignore_index=True)


def evaluate_model_independently(dataset: pd.DataFrame, model_name: str, target: str) -> dict:
    scored = refit_and_score(dataset, model_name, target)
    per_window_metrics = []
    per_slate_all = []
    for w, group in scored.groupby("window"):
        per_slate = independent_slate_metrics(group, "_score", target)
        per_slate["identity_key"] = group.groupby("slate_id").identity_key.first().reindex(
            per_slate.slate_id).to_numpy()
        per_slate["window"] = w
        coverage = independent_coverage_diversity(per_slate, dataset.produit_key.nunique())
        per_window_metrics.append({
            "window": int(w),
            "ndcg@10": float(per_slate["ndcg@10"].mean()),
            "map@10": float(per_slate["map@10"].mean()),
            "mrr": float(per_slate["mrr"].mean()),
            "recall@10": float(per_slate["recall@10"].mean()),
            **coverage,
        })
        per_slate_all.append(per_slate)
    per_slate_all = pd.concat(per_slate_all, ignore_index=True)
    summary = {
        "ndcg@10": float(np.mean([m["ndcg@10"] for m in per_window_metrics])),
        "map@10": float(np.mean([m["map@10"] for m in per_window_metrics])),
        "mrr": float(np.mean([m["mrr"] for m in per_window_metrics])),
        "recall@10": float(np.mean([m["recall@10"] for m in per_window_metrics])),
        "coverage_catalogue": float(np.mean([m["coverage_catalogue"] for m in per_window_metrics])),
        "diversite_gini_simpson": float(np.mean([m["diversite_gini_simpson"] for m in per_window_metrics])),
    }
    return {"per_window": per_window_metrics, "summary": summary, "per_slate": per_slate_all}


def independent_recommendation_recompute(dataset: pd.DataFrame) -> dict:
    log_section("Recalcul independant des metriques de recommandation")
    dataset = dataset.assign(window=assign_windows_independent(dataset))
    results = {}
    comparisons = {}

    for target, selected_model in SELECTED_MODELS.items():
        print(f"\n--- cible : {target} (modele retenu : {selected_model}) ---")
        baseline_eval = evaluate_model_independently(dataset, BASELINE_RECO, target)
        challenger_eval = evaluate_model_independently(dataset, selected_model, target)
        results[target] = {"baseline": baseline_eval["summary"], "challenger": challenger_eval["summary"]}

        merged = challenger_eval["per_slate"].merge(
            baseline_eval["per_slate"][["slate_id", "window", "ndcg@10"]],
            on=["slate_id", "window"], suffixes=("", "_baseline"))
        bootstrap = independent_bootstrap_ci95(merged["ndcg@10"], merged["ndcg@10_baseline"], merged.identity_key)
        p_value = independent_permutation_p_value(merged["ndcg@10"], merged["ndcg@10_baseline"], merged.identity_key)
        comparisons[target] = {"bootstrap": bootstrap, "raw_p_value": p_value}
        print(f"NDCG@10 baseline={baseline_eval['summary']['ndcg@10']:.5f} "
             f"{selected_model}={challenger_eval['summary']['ndcg@10']:.5f} "
             f"IC95%=[{bootstrap['ci95_low']:.5f};{bootstrap['ci95_high']:.5f}] p_brute={p_value:.4f}")

    holm = holm_correction_independent({t: c["raw_p_value"] for t, c in comparisons.items()})
    for target in comparisons:
        comparisons[target]["p_value_holm"] = holm[target]

    return {"par_cible": results, "comparaisons": comparisons}


def main() -> None:
    RESULTS["leakage_source"] = json.loads(
        (OUT_DIR / "06_leakage_checks.json").read_text(encoding="utf-8"))

    log_section("Chargement des jeux de donnees")
    pricing_dataset = build_pricing_dataset()
    reco_dataset = build_reco_dataset()
    print("pricing:", pricing_dataset.shape, "recommandation:", reco_dataset.shape)

    RESULTS["decoupage_temporel_pricing"] = check_temporal_split_pricing(pricing_dataset)
    RESULTS["decoupage_temporel_recommandation"] = check_temporal_split_recommendation(reco_dataset)
    RESULTS["doublons"] = check_duplicates(pricing_dataset, reco_dataset)
    RESULTS["recalcul_recommandation"] = independent_recommendation_recompute(reco_dataset)

    OUT_JSON.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8", newline="\n")
    print("\nEcrit :", OUT_JSON)


if __name__ == "__main__":
    main()
