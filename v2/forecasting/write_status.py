"""Enregistrement du statut officiel Forecasting V2 après les candidats A–C.

    python -m v2.forecasting.write_status

Écrit ``v2/models/forecasting_v2_status.json`` — la source de vérité du statut
des candidats. Les décisions y sont figées telles que validées, y compris le
maintien de C3 malgré un C2 très légèrement mieux calibré sur les produits A :
la règle de sélection avait été fixée avant l'évaluation et n'est pas
rétro-ajustée.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from v2.evaluation.harness import V2_EVAL, V2_MODELS

STATUS_PATH = V2_MODELS / "forecasting_v2_status.json"


def _statut_e() -> dict:
    """Statut du candidat E, lu depuis les résultats du pilote s'ils existent."""
    pilote_path = V2_EVAL / "E_pilote_metrics.json"
    if not pilote_path.exists():
        return {"status": "not_started", "note": "Pilote E non exécuté."}

    e = json.loads(pilote_path.read_text(encoding="utf-8"))
    porte = e["porte_decision"]
    ref = e["reference_v1_pilote"]
    niveaux = e["resultats_par_niveau"]
    gains_7j = {
        code: (ref["wape_7j"] - r["wape_7j"]) / ref["wape_7j"] for code, r in niveaux.items()
    }
    meilleur_7j = max(gains_7j, key=gains_7j.get)

    return {
        "status": "not_promising" if not porte["porte_franchie"] else "pilot_passed",
        "reason": e["reason"],
        "etape_atteinte": "pilote_fenetres_1_et_2",
        "six_fenetres_executees": False,
        "porte_decision": {
            "gain_minimal_exige": porte["gain_minimal_exige"],
            "meilleur_gain_observe_30j": porte["meilleur_gain_relatif"],
            "meilleur_niveau_30j": porte["meilleur_niveau"],
            "fixee_avant_execution": True,
        },
        "audit_disponibilite_e0": "v2/reports/06_E0_audit_disponibilite.md",
        "resultat_secondaire_notable": {
            "constat": (
                "Les variables métier améliorent nettement la WAPE à 7 jours (jusqu'à "
                f"{gains_7j[meilleur_7j]:+.2%} pour {meilleur_7j}, gain monotone avec l'ajout de "
                "variables) mais pas à 30 jours ni au grain quotidien."
            ),
            "explication": (
                "La stratégie récursive accumule l'erreur sur 30 jours et masque l'apport des "
                "variables ; à court horizon cet effet est faible."
            ),
            "gains_relatifs_7j": {k: round(v, 6) for k, v in gains_7j.items()},
            "insuffisant_malgre_tout": (
                "Le meilleur niveau reste au-dessus du seuil V2 de 0,44 à 7 jours — aucun niveau ne "
                "serait accepté même en reciblant le protocole sur le court horizon."
            ),
            "piste_v3": (
                "Prévision directe par horizon (sans récursion) — piste #12 du registre V2 forecasting."
            ),
        },
        "note_promotions": (
            "E2 (promotions) est le seul niveau franchement dégradé à 30 jours (−5,26 %) tout en "
            "améliorant le 7 jours : comportement instable, cohérent avec l'hypothèse non vérifiable "
            "sur la connaissance du calendrier promotionnel au cutoff (cf. E0)."
        ),
    }


def main() -> None:
    a = json.loads((V2_EVAL / "candidat_A_metrics.json").read_text(encoding="utf-8"))
    b = json.loads((V2_EVAL / "candidat_B_metrics.json").read_text(encoding="utf-8"))
    c = json.loads((V2_EVAL / "candidat_C_metrics.json").read_text(encoding="utf-8"))

    v1 = a["metriques_v1_reference"]
    c80 = c["variantes"]["niveau_80"]

    status = {
        # --- Clés de statut exactes, validées ---
        "forecasting_point_model": "v1_autoets_naive",
        "point_forecast_v2_validated": False,
        "interval_calibration_v2_validated": True,
        "interval_calibration_method": "C3_abc_x_intermitence",
        "challenger_interval_method": "C2_abc",
        # --- Nommage imposé ---
        "denomination_officielle": "Forecasting V1 avec recalibration V2 des intervalles",
        "ne_pas_presenter_comme": (
            "une Forecasting V2 complète — la prévision centrale reste strictement celle de la V1, "
            "seule la calibration des intervalles a été améliorée."
        ),
        "genere_le": datetime.now(timezone.utc).isoformat(),
        # --- Candidats ---
        "candidats": {
            "A_blend_autoets_wa28": {
                "status": "rejected",
                "reason": "insufficient_gain",
                "wape_30j": a["metriques_candidat"]["cumule"]["30"]["WAPE"],
                "fenetres_ameliorees_sur_6": a["comparaison_v1"]["n_fenetres_ameliorees_30j"],
                "note": (
                    "Gain agrégé de +0,67 % entièrement porté par la fenêtre 1, où le poids n'était pas "
                    "appris (valeur par défaut) ; fenêtres 3 à 6 toutes dégradées. Le mécanisme ne "
                    "généralise pas."
                ),
                "composant_conserve_pour_reutilisation": True,
                "proprietes_utiles": {
                    "stabilite_ecart_type_wape30j_v1": v1["stabilite"]["WAPE_30j_ecart_type"],
                    "stabilite_ecart_type_wape30j_A": a["metriques_candidat"]["stabilite"]["WAPE_30j_ecart_type"],
                    "biais_normalise_v1": v1["quotidien"]["biais_normalise"],
                    "biais_normalise_A": a["metriques_candidat"]["quotidien"]["biais_normalise"],
                },
            },
            "B_selection_par_segment": {
                "status": "rejected",
                "reason": "worse_than_v1_and_candidate_a",
                "meilleure_variante": b["meilleure_variante"],
                "wape_30j": b["comparaison_globale"]["meilleure_variante_b_wape_30j"],
                "note": (
                    "Les trois variantes sont sous la V1 et sous A. Décisions de segment instables "
                    "entre fenêtres (0 % à 46 % de produits basculés selon la fenêtre) : bruit, pas signal."
                ),
            },
            "C_recalibration_intervalles": {
                "status": "retained",
                "reason": "interval_calibration_improved",
                "methode_retenue": "C3_abc_x_intermitence",
                "challenger_documente": "C2_abc",
                "couverture_produits_a": {
                    "v1_reference": c80["C0_reference_v1_loo_global"]["couverture_produits_a"],
                    "C3_retenu": c80["C3_par_abc_profil"]["couverture_produits_a"],
                    "C2_challenger": c80["C2_par_abc"]["couverture_produits_a"],
                    "cible": [0.78, 0.84],
                },
                "largeur_moyenne": {
                    "v1_reference": c80["C0_reference_v1_loo_global"]["largeur_moyenne"],
                    "C3_retenu": c80["C3_par_abc_profil"]["largeur_moyenne"],
                    "C2_challenger": c80["C2_par_abc"]["largeur_moyenne"],
                },
                "note_c2_vs_c3": (
                    "L'écart entre C2 et C3 est très faible (somme des écarts au niveau nominal : "
                    "2,05 pp pour C2 contre 2,07 pp pour C3 ; largeur moyenne 3,5973 contre 3,5951). "
                    "C2 est légèrement MIEUX calibré sur les produits A (écart 0,27 pp contre 0,97 pp). "
                    "C3 est néanmoins retenu parce que la règle de sélection — largeur minimale parmi "
                    "les variantes conformes — avait été fixée AVANT l'évaluation et n'est pas "
                    "rétro-ajustée après observation des résultats. C2 reste documenté comme challenger."
                ),
            },
            "D_hurdle_recalibre": {
                "status": "not_launched",
                "reason": "previously_rejected_and_no_new_signal",
                "note": (
                    "Le hurdle avait déjà été testé et rejeté en V1 (biais normalisé >0,10, "
                    "discrimination faible du classifieur avec ROC-AUC ≈0,62, dérive du biais avec "
                    "l'horizon). Aucun élément nouveau ne justifie un réentraînement de 45-65 min."
                ),
            },
            "E_variables_metier": _statut_e(),
        },
        # --- Référence chiffrée ---
        "reference_v1": {
            "wape_cumule_30j": v1["cumule"]["30"]["WAPE"],
            "wape_cumule_7j": v1["cumule"]["7"]["WAPE"],
            "wape_quotidien": v1["quotidien"]["WAPE"],
        },
        "perimetre": {
            "n_fenetres": 6,
            "n_produits_fenetres": 1662,
            "artefacts_v1_modifies": False,
        },
        "aucune_publication_supabase": True,
        "aucun_deploiement": True,
    }

    V2_MODELS.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Statut écrit : {STATUS_PATH.relative_to(V2_MODELS.parents[1])}")
    print(json.dumps({k: v for k, v in status.items() if not isinstance(v, dict)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
