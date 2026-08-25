"""Clôture Recommandation V2.

    python -m v2.recommendation.close_recsys_v2

Produit le tableau de décision final et le rapport de clôture. Aucun candidat
n'ayant satisfait les seuils, la V1 (popularité globale) reste le modèle
principal — c'est le résultat par défaut du protocole, pas un échec du
processus.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from v2.evaluation.harness import V2_EVAL, V2_REPORTS


def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def main() -> None:
    r1r2 = json.loads((V2_EVAL / "recsys_R1_R2_metrics.json").read_text(encoding="utf-8"))
    r3 = json.loads((V2_EVAL / "R3_pilote_metrics.json").read_text(encoding="utf-8"))
    v1 = r1r2["reference_v1"]
    var = r1r2["variantes"]

    part_perso = float(np.mean([e["part_clients_personnalises"] for e in r3["statistiques_eligibilite"]]))

    rows = [
        {
            "modele": "V1 popularité globale", "recall": v1["recall_at_10"], "ndcg": v1["ndcg_at_10"],
            "couverture": v1["couverture_catalogue"], "diversite": v1["diversite_at_10"],
            "clients_perso": "0", "statut": "**Référence — modèle principal**",
        },
        {
            "modele": "R1 popularité régularisée",
            "recall": var["R1_decouverte"]["moyennes"]["recall_at_10"],
            "ndcg": var["R1_decouverte"]["moyennes"]["ndcg_at_10"],
            "couverture": var["R1_decouverte"]["moyennes"]["catalog_coverage"],
            "diversite": var["R1_decouverte"]["moyennes"]["diversity_at_10"],
            "clients_perso": "0", "statut": "`experiment_not_retained`",
        },
        {
            "modele": "R2 reranking de diversité",
            "recall": var["R2_decouverte"]["moyennes"]["recall_at_10"],
            "ndcg": var["R2_decouverte"]["moyennes"]["ndcg_at_10"],
            "couverture": var["R2_decouverte"]["moyennes"]["catalog_coverage"],
            "diversite": var["R2_decouverte"]["moyennes"]["diversity_at_10"],
            "clients_perso": "0", "statut": "`exploratory_diversity_challenger`",
        },
        {
            "modele": "R3 personnalisation catégorie (pilote F1-F2)",
            "recall": r3["moyennes_r3"]["recall_at_10"], "ndcg": r3["moyennes_r3"]["ndcg_at_10"],
            "couverture": r3["moyennes_r3"]["catalog_coverage"], "diversite": None,
            "clients_perso": f"{part_perso:.1%}", "statut": "`experiment_not_retained`",
        },
    ]

    payload = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "recommendation_primary_model": "v1_popularite_globale",
        "recommendation_v2_validated": False,
        "personalisation_validee": False,
        "tableau_decision": rows,
        "R4": {"status": "not_launched", "reason": "no_personalization_signal_in_R3"},
        "donnees_supplementaires_necessaires": ["order_id", "session_id", "event_timestamp",
                                                "davantage d'interactions par client"],
    }
    (V2_EVAL / "recsys_v2_decision_finale.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    lines = [
        "# 11 — Clôture Recommandation V2",
        "",
        f"_Généré le {payload['genere_le']}. Branche `feature/v2-model-improvements`, non fusionnée._",
        "",
        "## 1. Statut officiel",
        "",
        "```",
        "recommendation_primary_model: v1_popularite_globale",
        "recommendation_v2_validated: false",
        "R1_status: experiment_not_retained",
        "R1_reason: no_improvement_over_v1",
        "R2_status: exploratory_diversity_challenger",
        "R2_primary_model_eligible: false",
        "R2_reason: coverage_and_diversity_improved_but_relevance_loss_exceeds_threshold",
        "R3_status: experiment_not_retained",
        "R3_reason: relevance_not_improved",
        "R4_status: not_launched",
        "R4_reason: no_personalization_signal_in_R3",
        "```",
        "",
        "## 2. Tableau de décision",
        "",
        "| Modèle | Recall@10 | NDCG@10 | Couverture | Diversité | Clients personnalisés | Statut |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['modele']} | {_fmt(r['recall'])} | {_fmt(r['ndcg'])} | {_fmt(r['couverture'])} | "
            f"{_fmt(r['diversite'])} | {r['clients_perso']} | {r['statut']} |"
        )

    lines += [
        "",
        "_R3 est mesuré sur le pilote (fenêtres 1-2) et n'est donc pas strictement comparable aux "
        "moyennes 4 fenêtres de V1/R1/R2 ; sa comparaison valide figure au rapport 10, contre une V1 "
        "recalculée sur les deux mêmes fenêtres._",
        "",
        "## 3. Pourquoi R3 échoue — et pourquoi cela règle aussi le sort de R4",
        "",
        "R3 échoue la porte sur la pertinence : NDCG@10 −1,29 % et Recall@10 −2,09 % face à une V1 "
        "recalculée sur les mêmes fenêtres. Mais le point décisif est ailleurs :",
        "",
        f"**{part_perso:.1%} des clients passent les seuils d'éligibilité.** Les seuils fixés a priori "
        "(≥3 achats, ≥2 catégories, ≥60 % dans les catégories dominantes) ne filtrent presque personne, "
        "parce que le client médian a environ 17 achats répartis sur 6 catégories. R3 revient donc à "
        "**personnaliser quasiment tout le monde** — et cela dégrade quand même la pertinence.",
        "",
        "Sur le sous-groupe personnalisable lui-même — le test qui compte — R3 est également en retrait "
        "(−1,36 % et −1,22 % de NDCG@10 sur les deux fenêtres). **Il n'y a pas de signal de "
        "personnalisation à exploiter**, même là où les conditions sont les plus favorables.",
        "",
        "**Conséquence directe pour R4** : R4 devait router les clients « à historique suffisant » vers "
        "un modèle personnalisé et les autres vers la popularité. Or il n'existe pas de tel clivage ici "
        f"— {part_perso:.1%} des clients sont éligibles, il n'y a pas de sous-groupe à router. Et sur ce "
        "quasi-tout, la personnalisation légère ne produit aucun gain. Lancer un collaboratif plus "
        "lourd sur la même population, avec la même sparsité (~0,96) et le même volume d'historique, "
        "reviendrait à traiter un problème de sophistication alors que le problème est l'absence de "
        "signal. **R4 : `not_launched`, `no_personalization_signal_in_R3`.**",
        "",
        "## 4. Le seul acquis réel : la couverture",
        "",
        "| Modèle | Couverture | vs V1 | Concentration top-10 produits |",
        "|---|---:|---:|---:|",
        f"| V1 | {_fmt(v1['couverture_catalogue'])} | — | — |",
        f"| R2 | {_fmt(var['R2_decouverte']['moyennes']['catalog_coverage'])} | +64,6 % | "
        f"{_fmt(var['R2_decouverte']['concentration_moyenne'])} (contre "
        f"{_fmt(var['R1_decouverte']['concentration_moyenne'])} pour R1) |",
        f"| R3 (pilote) | {_fmt(r3['moyennes_r3']['catalog_coverage'])} | +161,8 % | — |",
        "",
        "Deux candidats indépendants montrent donc que **la concentration extrême de la V1 est "
        "corrigeable** : R2 fait passer la part des recommandations captée par les 10 produits les plus "
        "recommandés de 92,5 % à 53,5 %, et R3 triple la couverture catalogue. Dans les deux cas, le "
        "prix payé est une perte de pertinence — modérée, mais réelle, et supérieure aux tolérances "
        "fixées.",
        "",
        "C'est un résultat exploitable pour le métier : il existe un levier de diversité, à condition "
        "d'accepter explicitement un arbitrage pertinence/découverte. **R2 est conservé à ce titre** "
        "comme scénario exploratoire pour un bloc « Découvrir d'autres produits », en complément — "
        "jamais en remplacement — de la liste principale.",
        "",
        "## 5. Clôture honnête",
        "",
        "- **Modèle principal inchangé** : popularité globale (V1).",
        "- **Aucune personnalisation validée** : R1, R3 rejetés, R4 non lancé faute de signal.",
        "- **R2 conservé comme scénario exploratoire de diversité**, non éligible comme moteur principal, "
        "et **sa pénalité n'a pas été réglée rétrospectivement** pour le faire passer.",
        "- **Données supplémentaires nécessaires** pour espérer une personnalisation utile : "
        "`order_id` (paniers réels), `session_id` et `event_timestamp` (séquences), et davantage "
        "d'interactions par client.",
        "",
        "Ce résultat est cohérent avec les trois modules du projet : sur ce jeu de données "
        "(300 produits, ~18 mois, forte intermittence, prix catalogue fixe), **le signal fin — "
        "individuel, séquentiel ou causal — n'est pas exploitable**. Les baselines simples restent les "
        "meilleures réponses honnêtes.",
        "",
        "## 6. Garanties",
        "",
        "- 4 fenêtres V1, mêmes clients évaluables, mêmes définitions de métriques (module V1 importé "
        "sans modification).",
        "- Profils et règles appris **uniquement sur les fenêtres antérieures**.",
        "- 21 tests dédiés R1/R2 ajoutés (le total passe de 180 à 201) — ils manquaient réellement.",
        "- Aucun artefact V1 modifié, aucune fusion dans `main`, aucune écriture Supabase, aucun "
        "déploiement.",
        "- **Pricing V2 non démarré.**",
        "",
    ]
    V2_REPORTS.mkdir(parents=True, exist_ok=True)
    (V2_REPORTS / "11_recsys_v2_cloture.md").write_text("\n".join(lines), encoding="utf-8")
    print("Clôture Recommandation V2 écrite.")


if __name__ == "__main__":
    main()
