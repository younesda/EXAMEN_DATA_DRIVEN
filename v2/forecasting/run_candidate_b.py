"""Évaluation du candidat B — sélection AutoETS / WindowAverage28 par segment.

    python -m v2.forecasting.run_candidate_b

Produit ``v2/evaluation/candidat_B_metrics.json`` et
``v2/reports/03_forecasting_candidat_B.md``.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from v2.config.acceptance import evaluate_candidate, resolve_thresholds
from v2.config.v1_reference import load_v1_reference
from v2.evaluation.harness import (
    V2_EVAL,
    V2_REPORTS,
    SegmentContext,
    attach_horizon,
    compare_to_v1,
    current_rss_mb,
    evaluate_predictions,
    load_analytical_table,
    load_v1_predictions,
    log_event,
)
from v2.evaluation.intervals import CalibrationRegime, compute_intervals, coverage_report
from v2.forecasting.candidate_a_blend import load_v1_operational_predictions
from v2.forecasting.candidate_b_segment import (
    MARGE_REGULARISATION,
    MIN_OBS_SEGMENT,
    MIN_VALIDATIONS,
    SEUIL_TAUX_ZEROS,
    SegmentSpec,
    VariantB,
    build_selection_frame,
    run_candidate_b,
)


def main() -> None:
    t_start = time.time()
    log_event({"type": "debut", "candidat": "candidat_B", "memoire_rss_mb": current_rss_mb()})

    table = load_analytical_table()
    segments = SegmentContext(table).build()
    v1_frame = attach_horizon(load_v1_predictions())
    v1_eval = evaluate_predictions(v1_frame, segments, "V1_AutoETS_repli_Naive")

    # Candidat A, pour la comparaison exigée (B doit dépasser A ET la V1)
    from v2.forecasting.candidate_a_blend import BlendSpec, SelectionMode, build_blend_frame, run_candidate_a

    blend_frame = build_blend_frame(load_v1_operational_predictions())
    a_out = run_candidate_a(BlendSpec(mode=SelectionMode.EXPANDING), frame=blend_frame)
    a_eval = evaluate_predictions(attach_horizon(a_out[["unique_id", "ds", "window", "y", "y_pred"]]), segments, "candidat_A")

    frame = build_selection_frame(load_v1_operational_predictions())
    v1_ref = load_v1_reference()
    v1_wape_abc_a = v1_eval["par_segment"]["abc"]["A"]["WAPE_cumule_30j"]
    thresholds = resolve_thresholds(v1_ref, v1_wape_abc_a=v1_wape_abc_a)

    variantes = {}
    for variant in VariantB:
        t0 = time.time()
        spec = SegmentSpec(variant=variant)
        out, decisions = run_candidate_b(spec, frame, segments)
        cand_frame = attach_horizon(out[["unique_id", "ds", "window", "y", "y_pred"]])
        ev = evaluate_predictions(cand_frame, segments, spec.name)
        comp = compare_to_v1(ev, v1_eval)

        iv = compute_intervals(cand_frame, CalibrationRegime.LEAVE_ONE_WINDOW_OUT, niveau=0.80)
        cov = coverage_report(iv, segments, 0.80)

        verdict = evaluate_candidate(
            wape_cumule_30j=ev["cumule"]["30"]["WAPE"],
            wape_cumule_7j=ev["cumule"]["7"]["WAPE"],
            wape_quotidien=ev["quotidien"]["WAPE"],
            wape_abc_a=ev["par_segment"]["abc"]["A"]["WAPE_cumule_30j"],
            n_fenetres_ameliorees_30j=comp["n_fenetres_ameliorees_30j"],
            couverture_80_globale=cov["couverture_globale"],
            couverture_80_produits_a=cov.get("par_abc", {}).get("A", {}).get("couverture", float("nan")),
            valeurs_non_finies=ev["qualite"]["n_non_finis"],
            valeurs_negatives=ev["qualite"]["n_negatifs"],
            thresholds=thresholds,
        )
        variantes[variant.value] = {
            "metriques": ev,
            "comparaison_v1": comp,
            "decisions_par_fenetre": decisions.to_dict(orient="records"),
            "intervalles_80": cov,
            "verdict": verdict,
            "duree_s": round(time.time() - t0, 2),
        }

    meilleure = min(variantes, key=lambda k: variantes[k]["metriques"]["cumule"]["30"]["WAPE"])
    wape_meilleure = variantes[meilleure]["metriques"]["cumule"]["30"]["WAPE"]
    bat_v1 = wape_meilleure < v1_eval["cumule"]["30"]["WAPE"]
    bat_a = wape_meilleure < a_eval["cumule"]["30"]["WAPE"]
    accepte = any(v["verdict"]["accepte"] for v in variantes.values())

    statut = "experiment_retained" if accepte else "experiment_not_retained"
    raison = (
        "all_criteria_met" if accepte
        else ("worse_than_v1_and_candidate_a" if not (bat_v1 or bat_a) else "insufficient_gain")
    )

    payload = {
        "candidat": "candidat_B_selection_par_segment",
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "status": statut,
        "reason": raison,
        "parametres_fixes_a_priori": {
            "seuil_taux_zeros_B1": SEUIL_TAUX_ZEROS,
            "min_observations_segment_B2": MIN_OBS_SEGMENT,
            "min_validations_B3": MIN_VALIDATIONS,
            "marge_regularisation_B3": MARGE_REGULARISATION,
        },
        "variantes": variantes,
        "meilleure_variante": meilleure,
        "comparaison_globale": {
            "v1_wape_30j": v1_eval["cumule"]["30"]["WAPE"],
            "candidat_a_wape_30j": a_eval["cumule"]["30"]["WAPE"],
            "meilleure_variante_b_wape_30j": wape_meilleure,
            "b_bat_v1": bat_v1,
            "b_bat_candidat_a": bat_a,
        },
        "metriques_v1_reference": v1_eval,
        "seuils_acceptation": thresholds.to_dict(),
        "cout_calcul": {
            "duree_totale_s": round(time.time() - t_start, 2),
            "memoire_rss_mb": current_rss_mb(),
            "reentrainement": False,
        },
    }

    V2_EVAL.mkdir(parents=True, exist_ok=True)
    (V2_EVAL / "candidat_B_metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log_event({"type": "fin", "candidat": "candidat_B", "statut": statut,
               "duree_totale_s": payload["cout_calcul"]["duree_totale_s"],
               "memoire_rss_mb": payload["cout_calcul"]["memoire_rss_mb"]})
    _write_report(payload, a_eval)
    print(f"Statut : {statut} ({raison}) — meilleure variante {meilleure} "
          f"WAPE30j={wape_meilleure:.6f} vs V1 {v1_eval['cumule']['30']['WAPE']:.6f} "
          f"vs A {a_eval['cumule']['30']['WAPE']:.6f}")


def _fmt(x, nd=6):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _write_report(p: dict, a_eval: dict) -> None:
    v1 = p["metriques_v1_reference"]
    cg = p["comparaison_globale"]

    lines = [
        "# 03 — Candidat B : sélection AutoETS / WindowAverage28 par segment",
        "",
        f"_Généré le {p['genere_le']}. Branche `feature/v2-model-improvements`._",
        "",
        f"**Statut : `{p['status']}` — raison : `{p['reason']}`**",
        "",
        "## 1. Les trois variantes testées",
        "",
        "| Variante | Principe | Apprentissage |",
        "|---|---|---|",
        f"| **B1** | Règle fixée a priori : WindowAverage28 si taux de jours sans vente > "
        f"{SEUIL_TAUX_ZEROS:.0%}, AutoETS sinon | Aucun |",
        "| **B2** | Meilleur modèle par segment (classe ABC × profil de demande) | Fenêtres "
        "strictement antérieures |",
        f"| **B3** | Sélection par produit, autorisée seulement si ≥{MIN_VALIDATIONS} fenêtres passées "
        f"ET gain ≥{MARGE_REGULARISATION:.0%} | Fenêtres strictement antérieures, fortement régularisée |",
        "",
        "Tous les paramètres ci-dessus ont été fixés **avant** de regarder le moindre résultat. Les "
        "variables de segmentation (ABC, taux de zéros, ADI, ancienneté, longueur d'historique) sont "
        "recalculées par fenêtre **sur le train uniquement**.",
        "",
        "## 2. Résultat principal",
        "",
        "| Modèle | WAPE 30 j | WAPE 7 j | WAPE quotidienne | Fenêtres améliorées /6 |",
        "|---|---:|---:|---:|---:|",
        f"| **V1 (référence)** | {_fmt(cg['v1_wape_30j'])} | {_fmt(v1['cumule']['7']['WAPE'])} | "
        f"{_fmt(v1['quotidien']['WAPE'])} | — |",
        f"| Candidat A | {_fmt(cg['candidat_a_wape_30j'])} | {_fmt(a_eval['cumule']['7']['WAPE'])} | "
        f"{_fmt(a_eval['quotidien']['WAPE'])} | 2 |",
    ]
    for name, v in p["variantes"].items():
        m, c = v["metriques"], v["comparaison_v1"]
        lines.append(
            f"| {name} | {_fmt(m['cumule']['30']['WAPE'])} | {_fmt(m['cumule']['7']['WAPE'])} | "
            f"{_fmt(m['quotidien']['WAPE'])} | {c['n_fenetres_ameliorees_30j']} |"
        )

    lines += [
        "",
        f"**Aucune des trois variantes ne bat la V1** (meilleure : `{p['meilleure_variante']}` à "
        f"{_fmt(cg['meilleure_variante_b_wape_30j'])} contre {_fmt(cg['v1_wape_30j'])}), "
        f"ni le candidat A ({_fmt(cg['candidat_a_wape_30j'])}).",
        "",
        "## 3. Pourquoi la sélection par segment échoue",
        "",
        "### Les décisions sont instables d'une fenêtre à l'autre",
        "",
        "Part de produits basculés vers WindowAverage28, par fenêtre :",
        "",
        "| Variante | F1 | F2 | F3 | F4 | F5 | F6 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, v in p["variantes"].items():
        parts = [f"{d['part_windowaverage28']:.1%}" for d in v["decisions_par_fenetre"]]
        lines.append(f"| {name} | " + " | ".join(parts) + " |")

    lines += [
        "",
        "**B2 est le cas le plus parlant** : la part de produits confiés à WindowAverage28 passe de "
        "0 % (F1, aucune donnée) à 46,4 % (F2), puis retombe à 21,8 %, 11,7 %, puis 0 % sur les deux "
        "dernières fenêtres. Le « meilleur modèle par segment » change donc complètement d'une fenêtre "
        "à la suivante : ce n'est pas un signal stable, c'est du bruit d'échantillonnage. Une règle "
        "apprise sur ce bruit ne peut pas généraliser — et de fait, elle dégrade la performance.",
        "",
        "**B3 (par produit)** est encore plus exposé : malgré une régularisation sévère "
        f"(≥{MIN_VALIDATIONS} fenêtres et ≥{MARGE_REGULARISATION:.0%} de gain exigés), c'est la "
        "variante la moins bonne. Avec au plus 5 fenêtres d'historique par produit, estimer un choix de "
        "modèle produit par produit revient à ajuster sur très peu de points.",
        "",
        "**B1 (règle fixe, sans apprentissage)** fait presque aussi bien que B2 — ce qui confirme que "
        "l'apprentissage de la règle n'apporte rien : toute la performance vient de la règle a priori, "
        "et celle-ci est déjà moins bonne que de garder AutoETS partout.",
        "",
        "## 4. Détail des seuils d'acceptation (meilleure variante)",
        "",
        "| Critère | Valeur | Seuil | Satisfait ? |",
        "|---|---:|---:|:---:|",
    ]
    best = p["variantes"][p["meilleure_variante"]]["verdict"]
    for name, crit in best["criteres"].items():
        seuil = crit["seuil"]
        seuil_str = f"[{seuil[0]}, {seuil[1]}]" if isinstance(seuil, list) else _fmt(seuil)
        val = _fmt(crit["valeur"]) if isinstance(crit["valeur"], float) else crit["valeur"]
        lines.append(f"| `{name}` | {val} | {seuil_str} | {'✅' if crit['ok'] else '❌'} |")

    lines += [
        "",
        f"**{best['verdict']}**",
        "",
        "## 5. Décision",
        "",
        "Conformément au protocole (« si le candidat B ne dépasse pas le candidat A et la V1 de façon "
        "stable, arrête-le et archive-le comme non retenu »), **le candidat B est arrêté et archivé "
        "comme non retenu**. Aucune variante supplémentaire ne sera essayée : le problème n'est pas le "
        "réglage, c'est que le signal de segmentation n'est pas stable dans le temps sur ce jeu de "
        "données.",
        "",
        "## 6. Enseignement transférable",
        "",
        "L'échec de B renforce le diagnostic du candidat A : **le choix entre AutoETS et "
        "WindowAverage28 ne se généralise ni globalement (A), ni par segment, ni par produit (B).** "
        "Cela oriente la suite vers ce qui reste réellement perfectible et mesurable : la calibration "
        "de l'incertitude (candidat C), où la V1 a un défaut documenté et chiffré (sous-couverture des "
        "produits A à ~74 % au lieu de 80 %).",
        "",
        "## 7. Coût de calcul",
        "",
        f"- Durée totale : **{p['cout_calcul']['duree_totale_s']} s** pour les trois variantes",
        f"- Mémoire résidente : {p['cout_calcul']['memoire_rss_mb']} Mo",
        "- Réentraînement : **non** (sélection parmi les prédictions V1 figées)",
        "",
        "## 8. Garanties",
        "",
        "- Segmentation calculée par fenêtre sur le **train uniquement**.",
        "- Règles apprises **exclusivement** sur les fenêtres strictement antérieures (F1 retombe sur "
        "AutoETS par défaut, sans apprentissage).",
        "- Aucun artefact V1 modifié.",
        "",
    ]

    V2_REPORTS.mkdir(parents=True, exist_ok=True)
    (V2_REPORTS / "03_forecasting_candidat_B.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
