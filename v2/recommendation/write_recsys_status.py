"""Statut officiel Recommandation V2.

    python -m v2.recommendation.write_recsys_status

Écrit ``v2/models/recsys_v2_status.json``. R2 est conservé comme challenger
de diversité — jamais supprimé, jamais éligible comme moteur principal, et
sa pénalité n'est pas réglée rétrospectivement pour le faire passer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from v2.evaluation.harness import V2_EVAL, V2_MODELS

STATUS_PATH = V2_MODELS / "recsys_v2_status.json"


def _statut_r3() -> dict:
    path = V2_EVAL / "R3_pilote_metrics.json"
    if not path.exists():
        return {"status": "not_started"}
    r = json.loads(path.read_text(encoding="utf-8"))
    return {
        "status": r["status"],
        "reason": r["reason"],
        "porte_franchie": r["porte_franchie"],
        "signal_sous_groupe_personnalisable": r["signal_sous_groupe_personnalisable"],
        "seuils_eligibilite": r["seuils_eligibilite_fixes_a_priori"],
        "part_clients_personnalises": [
            {"fenetre": e["fenetre"], "part": e["part_clients_personnalises"]}
            for e in r["statistiques_eligibilite"]
        ],
        "moyennes": r["moyennes_r3"],
    }


def _statut_r4() -> dict:
    path = V2_EVAL / "R3_pilote_metrics.json"
    if not path.exists():
        return {"status": "not_started"}
    r = json.loads(path.read_text(encoding="utf-8"))
    return {
        "status": "not_launched" if r["decision_r4"] == "not_launched" else "to_launch",
        "reason": r["raison_r4"],
        "note": (
            "R4 était un routage historique-suffisant → personnalisé / autres → popularité globale. "
            "R3 teste déjà ce routage avec une personnalisation légère ; sans signal sur le "
            "sous-groupe ciblé, un collaboratif plus lourd sur la même population n'a pas de fondement."
        ),
    }


def main() -> None:
    r1r2 = json.loads((V2_EVAL / "recsys_R1_R2_metrics.json").read_text(encoding="utf-8"))
    v1 = r1r2["reference_v1"]
    var = r1r2["variantes"]

    status = {
        # --- Clés officielles ---
        "recommendation_primary_model": "v1_popularite_globale",
        "recommendation_v2_validated": False,
        "R1_status": "experiment_not_retained",
        "R1_reason": "no_improvement_over_v1",
        "R2_status": "exploratory_diversity_challenger",
        "R2_primary_model_eligible": False,
        "R2_reason": "coverage_and_diversity_improved_but_relevance_loss_exceeds_threshold",
        "genere_le": datetime.now(timezone.utc).isoformat(),

        "reference_v1": {
            "recall_at_10": v1["recall_at_10"],
            "ndcg_at_10": v1["ndcg_at_10"],
            "couverture_catalogue": v1["couverture_catalogue"],
            "personalisation_validee": v1["personalisation_validee"],
        },

        "R1_details": {
            "recall_at_10": var["R1_decouverte"]["moyennes"]["recall_at_10"],
            "ndcg_at_10": var["R1_decouverte"]["moyennes"]["ndcg_at_10"],
            "couverture_catalogue": var["R1_decouverte"]["moyennes"]["catalog_coverage"],
            "cause_echec": (
                "Le α choisi sur les fenêtres antérieures retient la popularité récente pure "
                "(α=0,00 sur F1 et F2), moins bonne que la popularité globale sur la fenêtre évaluée. "
                "Même non-généralisation que les candidats A et B du forecasting."
            ),
        },

        "R2_details": {
            "recall_at_10": var["R2_decouverte"]["moyennes"]["recall_at_10"],
            "ndcg_at_10": var["R2_decouverte"]["moyennes"]["ndcg_at_10"],
            "couverture_catalogue": var["R2_decouverte"]["moyennes"]["catalog_coverage"],
            "diversite_at_10": var["R2_decouverte"]["moyennes"]["diversity_at_10"],
            "concentration_top10": var["R2_decouverte"]["concentration_moyenne"],
            "concentration_r1_pour_comparaison": var["R1_decouverte"]["concentration_moyenne"],
            "apport_demontre": (
                "Réduit la concentration des recommandations de 92,5 % à 53,5 % sur les 10 produits "
                "les plus recommandés, et augmente la couverture catalogue de +64,6 %."
            ),
            "usage_metier_envisage": (
                "Bloc « Découvrir d'autres produits » — complément de la liste principale, jamais "
                "en remplacement du moteur principal."
            ),
            "penalite_non_reglee_retrospectivement": True,
            "note_penalite": (
                "La pénalité d'omniprésence n'a PAS été réajustée après observation des résultats pour "
                "faire passer R2. Un réglage moins agressif devra être fixé a priori dans une itération "
                "future s'il est jugé pertinent."
            ),
        },

        "R3": _statut_r3(),
        "R4": _statut_r4(),

        "signal_web": {
            "actif_dans_modele_principal": False,
            "raison": "dégradait le recall cold-start en V1 (0,0846 avec contre 0,1110 sans)",
        },

        "perimetre": {"n_fenetres": 4, "artefacts_v1_modifies": False},
        "aucune_publication_supabase": True,
        "aucun_deploiement": True,
    }

    V2_MODELS.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in status.items() if not isinstance(v, dict)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
