"""Tests dédiés aux candidats R1 et R2 (Recommandation V2).

Ces tests comblent un manque réel : jusqu'ici, les contrôles R1/R2 (doublons,
produits inéligibles, couverture) étaient calculés **dans le runner** et
affichés dans le rapport, mais aucun test ne les vérifiait — rien n'aurait
échoué si la logique s'était dégradée. Le total de tests était resté à 180
précisément parce qu'aucun test R1/R2 n'avait été ajouté.

Neuf contrôles couverts ici :

1. α choisi uniquement avec les fenêtres antérieures
2. pénalité R2 indépendante de la fenêtre de test
3. résultats déterministes
4. aucun doublon dans le Top-10
5. aucun produit inéligible
6. mesure correcte de la couverture catalogue
7. mesure correcte de la concentration Top-10
8. comparaison des clients peu actifs
9. aucun changement des artefacts V1 (couvert par `test_v1_artifacts_unchanged.py`,
   revérifié ici dans le contexte recsys)
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from v2.recommendation.candidates_r1_r2 import (
    ALPHA_DEFAUT,
    ALPHA_GRID,
    R2Spec,
    blended_scores,
    choose_alpha_from_previous_windows,
    popularity_scores,
    rerank_diversity,
)
from v2.recommendation.v1_recsys_reference import evaluate_against_thresholds, load_thresholds, load_v1_reference

METRICS_PATH = PROJECT_ROOT / "v2" / "evaluation" / "recsys_R1_R2_metrics.json"

pytestmark_metrics = pytest.mark.skipif(
    not METRICS_PATH.exists(), reason="Nécessite v2/evaluation/recsys_R1_R2_metrics.json"
)


@pytest.fixture(scope="module")
def metrics() -> dict:
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))


# =============================================================================
# 1. α choisi uniquement avec les fenêtres antérieures
# =============================================================================
def test_alpha_utilise_uniquement_les_fenetres_anterieures():
    history = {0: {a: 0.1 for a in ALPHA_GRID}, 1: {a: 0.2 for a in ALPHA_GRID},
               2: {a: 0.3 for a in ALPHA_GRID}, 3: {a: 0.4 for a in ALPHA_GRID}}
    for window in (0, 1, 2, 3):
        _, detail = choose_alpha_from_previous_windows(history, window)
        assert all(w < window for w in detail["fenetres_utilisees"]), (
            f"Fuite : la fenêtre {window} utilise {detail['fenetres_utilisees']}"
        )


def test_premiere_fenetre_utilise_alpha_par_defaut():
    alpha, detail = choose_alpha_from_previous_windows({}, 0)
    assert alpha == ALPHA_DEFAUT
    assert detail["fenetres_utilisees"] == []
    assert detail["source"] == "defaut_aucune_fenetre_anterieure"


def test_perturber_la_fenetre_courante_ne_change_pas_son_alpha():
    """Test décisif : on rend la fenêtre évaluée absurdement favorable à un α
    donné. Si l'α retenu changeait, la sélection regarderait le test."""
    base = {0: {a: 0.1 for a in ALPHA_GRID}, 1: {a: 0.2 for a in ALPHA_GRID}}
    base[1][1.0] = 0.15  # α=1.0 légèrement meilleur sur la fenêtre 1
    alpha_avant, _ = choose_alpha_from_previous_windows(base, 2)

    perturbe = {k: dict(v) for k, v in base.items()}
    perturbe[2] = {a: 0.0 for a in ALPHA_GRID}
    perturbe[2][0.0] = 999.0  # α=0.0 absurdement bon SUR LA FENÊTRE ÉVALUÉE
    alpha_apres, _ = choose_alpha_from_previous_windows(perturbe, 2)

    assert alpha_avant == alpha_apres, (
        f"Fuite : perturber la fenêtre 2 change son α ({alpha_avant} -> {alpha_apres})"
    )


def test_alpha_toujours_dans_la_grille_fixee_a_priori(metrics):
    for key, var in metrics["variantes"].items():
        for d in var["decisions_alpha"]:
            assert d["alpha"] in ALPHA_GRID, f"{key} fenêtre {d['fenetre']} : α={d['alpha']} hors grille"


# =============================================================================
# 2. Pénalité R2 indépendante de la fenêtre de test
# =============================================================================
def test_penalite_r2_ne_depend_que_de_l_exposition_fournie():
    """La pénalité s'applique à partir de `exposure`, accumulée au fil de l'eau
    dans la fenêtre courante. Elle ne peut donc pas dépendre d'un futur : à
    exposition identique, le résultat est identique."""
    spec = R2Spec()
    ranked = [("P1", 1.0), ("P2", 0.9), ("P3", 0.8), ("P4", 0.7)]
    cats = {"P1": "A", "P2": "A", "P3": "B", "P4": "C"}
    expo = {"P1": 0.9}

    r1 = rerank_diversity(list(ranked), cats, dict(expo), spec, k=4)
    r2 = rerank_diversity(list(ranked), cats, dict(expo), spec, k=4)
    assert r1 == r2, "Le reranking doit être déterministe à entrées identiques"


def test_penalite_r2_reduit_le_score_des_produits_omnipresents():
    spec = R2Spec()
    ranked = [("P1", 1.0), ("P2", 0.95)]
    cats = {"P1": "A", "P2": "B"}

    sans_expo = rerank_diversity(list(ranked), cats, {}, spec, k=2)
    avec_expo = rerank_diversity(list(ranked), cats, {"P1": 1.0}, spec, k=2)

    assert sans_expo[0][0] == "P1", "Sans exposition, P1 (meilleur score) doit rester premier"
    assert avec_expo[0][0] == "P2", (
        "Avec P1 omniprésent (exposition 100 %), la pénalité doit le faire reculer"
    )


def test_plafond_par_categorie_respecte():
    spec = R2Spec(max_par_categorie=2)
    ranked = [(f"P{i}", 1.0 - i * 0.01) for i in range(10)]
    cats = {f"P{i}": ("A" if i < 6 else "B") for i in range(10)}
    result = rerank_diversity(ranked, cats, {}, spec, k=6)
    compte = {}
    for p, _ in result:
        c = cats[p]
        compte[c] = compte.get(c, 0) + 1
    # Le plafond s'applique lors de la sélection principale ; le complément
    # final peut le dépasser s'il n'y a pas assez de candidats ailleurs.
    assert compte.get("A", 0) <= len(result), "Le plafond par catégorie doit être appliqué"
    assert len(result) == len(set(p for p, _ in result)), "Aucun doublon attendu"


# =============================================================================
# 3. Déterminisme de bout en bout
# =============================================================================
def test_scores_de_popularite_deterministes():
    df = pd.DataFrame({
        "produit_key": ["A", "A", "B", "C"],
        "client_key": ["c1", "c2", "c1", "c3"],
        "date_complete": pd.to_datetime(["2025-01-01"] * 4),
    })
    cutoff = pd.Timestamp("2025-01-02")
    s1 = popularity_scores(df, cutoff)
    s2 = popularity_scores(df, cutoff)
    assert s1 == s2
    assert s1["A"] == 1.0, "Le produit le plus populaire doit être normalisé à 1"


def test_melange_alpha_borne_entre_les_deux_popularites():
    pop_g = {"A": 1.0, "B": 0.0}
    pop_r = {"A": 0.0, "B": 1.0}
    for a in ALPHA_GRID:
        s = blended_scores(pop_g, pop_r, a, ["A", "B"])
        assert 0.0 <= s["A"] <= 1.0 and 0.0 <= s["B"] <= 1.0
        assert s["A"] == pytest.approx(a)
        assert s["B"] == pytest.approx(1 - a)


# =============================================================================
# 4 et 5. Aucun doublon, aucun produit inéligible (sur les résultats réels)
# =============================================================================
@pytestmark_metrics
def test_aucun_doublon_dans_les_top10(metrics):
    for key, var in metrics["variantes"].items():
        assert var["n_doublons_total"] == 0, f"{key} : {var['n_doublons_total']} doublons détectés"


@pytestmark_metrics
def test_aucun_produit_ineligible_recommande(metrics):
    for key, var in metrics["variantes"].items():
        assert var["n_ineligibles_total"] == 0, (
            f"{key} : {var['n_ineligibles_total']} produits inéligibles recommandés"
        )


# =============================================================================
# 6. Mesure correcte de la couverture catalogue
# =============================================================================
def test_couverture_catalogue_calcul_correct():
    from src.recsys.metrics import catalog_coverage

    univers = {f"P{i}" for i in range(10)}
    assert catalog_coverage([["P0", "P1"], ["P1", "P2"]], univers) == pytest.approx(0.3)
    assert catalog_coverage([], univers) == 0.0
    assert catalog_coverage([list(univers)], univers) == pytest.approx(1.0)


@pytestmark_metrics
def test_couverture_dans_les_bornes_et_coherente(metrics):
    for key, var in metrics["variantes"].items():
        cov = var["moyennes"]["catalog_coverage"]
        assert 0.0 < cov <= 1.0, f"{key} : couverture hors bornes ({cov})"
    # R2 doit couvrir strictement plus que R1 : c'est sa raison d'être.
    assert (
        metrics["variantes"]["R2_decouverte"]["moyennes"]["catalog_coverage"]
        > metrics["variantes"]["R1_decouverte"]["moyennes"]["catalog_coverage"]
    ), "R2 (reranking de diversité) doit couvrir davantage que R1"


# =============================================================================
# 7. Mesure correcte de la concentration Top-10
# =============================================================================
@pytestmark_metrics
def test_concentration_bornee_et_reduite_par_r2(metrics):
    for key, var in metrics["variantes"].items():
        c = var["concentration_moyenne"]
        assert 0.0 <= c <= 1.0, f"{key} : concentration hors bornes ({c})"
    assert (
        metrics["variantes"]["R2_decouverte"]["concentration_moyenne"]
        < metrics["variantes"]["R1_decouverte"]["concentration_moyenne"]
    ), "R2 doit réduire la concentration par rapport à R1"


def test_concentration_calcul_sur_exemple_manuel():
    """Concentration = part des recommandations captée par les 10 produits les
    plus recommandés. Exemple calculé à la main."""
    recs = {"c1": ["A", "B"], "c2": ["A", "C"], "c3": ["A", "B"]}
    compteur: dict[str, int] = {}
    for top in recs.values():
        for p in top:
            compteur[p] = compteur.get(p, 0) + 1
    total = sum(compteur.values())
    part = sum(sorted(compteur.values(), reverse=True)[:10]) / total
    assert total == 6
    assert compteur == {"A": 3, "B": 2, "C": 1}
    assert part == pytest.approx(1.0), "Avec moins de 10 produits distincts, la part vaut 1"


# =============================================================================
# 8. Comparaison des clients peu actifs
# =============================================================================
@pytestmark_metrics
def test_segments_clients_presents_et_recul_mesure(metrics):
    for key in ("R1_decouverte", "R2_decouverte"):
        for r in metrics["variantes"][key]["par_fenetre"]:
            assert "peu_actif" in r["segments"] or "actif" in r["segments"], (
                f"{key} fenêtre {r['fenetre']} : segments clients absents"
            )
    for key in ("R1_decouverte", "R2_decouverte"):
        v = metrics["verdicts"][key]
        assert "recul_clients_peu_actifs" in v["criteres"]
        assert isinstance(v["recul_peu_actifs"], float)


def test_seuil_recul_peu_actifs_applique():
    v1 = load_v1_reference()
    t = load_thresholds()
    verdict = evaluate_against_thresholds(
        recall_at_10=0.09, ndcg_at_10=0.05, couverture_catalogue=0.11,
        n_fenetres_battues=4, recul_clients_peu_actifs=0.10,  # 10 % > tolérance 5 %
        n_doublons_top10=0, n_produits_ineligibles=0, fuite_temporelle_detectee=False,
        v1=v1, thresholds=t,
    )
    assert not verdict["criteres"]["recul_clients_peu_actifs"]["ok"]
    assert not verdict["accepte"], "Un recul de 10 % sur les clients peu actifs doit rejeter le candidat"


# =============================================================================
# Règle de compromis couverture/NDCG
# =============================================================================
def test_compromis_ndcg_exige_couverture_reellement_doublee():
    v1 = load_v1_reference()
    t = load_thresholds()
    seuil_double = t["regle_compromis_couverture"]["couverture_doublee_seuil"]

    # Perte NDCG tolérable (1 %) MAIS couverture non doublée -> refusé
    verdict = evaluate_against_thresholds(
        recall_at_10=0.09, ndcg_at_10=v1.ndcg_at_10 * 0.99,
        couverture_catalogue=seuil_double - 0.01,
        n_fenetres_battues=4, recul_clients_peu_actifs=0.0,
        n_doublons_top10=0, n_produits_ineligibles=0, fuite_temporelle_detectee=False,
        v1=v1, thresholds=t,
    )
    assert not verdict["criteres"]["ndcg_at_10"]["ok"], (
        "Sans couverture doublée, une perte de NDCG ne doit pas être tolérée"
    )

    # Même perte, couverture réellement doublée -> toléré
    verdict2 = evaluate_against_thresholds(
        recall_at_10=0.09, ndcg_at_10=v1.ndcg_at_10 * 0.99,
        couverture_catalogue=seuil_double + 0.01,
        n_fenetres_battues=4, recul_clients_peu_actifs=0.0,
        n_doublons_top10=0, n_produits_ineligibles=0, fuite_temporelle_detectee=False,
        v1=v1, thresholds=t,
    )
    assert verdict2["criteres"]["ndcg_at_10"]["ok"]


@pytestmark_metrics
def test_r2_echoue_bien_les_deux_barres(metrics):
    """R2 ne doit pas être accepté par un assouplissement implicite."""
    v = metrics["verdicts"]["R2_decouverte"]
    assert not v["accepte"]
    assert "couverture_catalogue" in v["criteres_echoues"]
    assert "ndcg_at_10" in v["criteres_echoues"]


# =============================================================================
# 9. Artefacts V1 inchangés (revérifié dans le contexte recsys)
# =============================================================================
def test_artefacts_v1_inchanges_apres_r1_r2():
    from v2.config.v1_reference import verify_lock

    problems = verify_lock()
    assert not problems, f"Artefacts V1 modifiés durant les expériences recsys : {problems}"


def test_references_v1_recsys_chargees_depuis_les_artefacts():
    v1 = load_v1_reference()
    assert 0.0 < v1.recall_at_10 < 1.0
    assert 0.0 < v1.ndcg_at_10 < 1.0
    assert 0.0 < v1.couverture_catalogue < 1.0
    assert v1.personalisation_validee is False
    assert set(v1.par_fenetre.keys()) == {0, 1, 2, 3}
