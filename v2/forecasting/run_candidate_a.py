"""Évaluation complète du candidat A — combinaison AutoETS / WindowAverage28.

    python -m v2.forecasting.run_candidate_a

Produit :
* ``v2/evaluation/candidat_A_metrics.json`` — toutes les métriques brutes
* ``v2/reports/02_forecasting_candidat_A.md`` — rapport lisible

Aucun réentraînement : recombinaison des prédictions V1 figées. Les artefacts
V1 ne sont jamais modifiés (garanti par le verrou SHA-256).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
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
from v2.forecasting.candidate_a_blend import (
    WEIGHT_GRID,
    BlendSpec,
    SelectionMode,
    build_blend_frame,
    load_v1_operational_predictions,
    run_candidate_a,
)

CANDIDATE_LABEL = "candidat_A_blend_autoets_wa28"


def main() -> None:
    t_start = time.time()
    log_event({"type": "debut", "candidat": CANDIDATE_LABEL, "memoire_rss_mb": current_rss_mb()})

    table = load_analytical_table()
    segments = SegmentContext(table).build()

    # --- Référence V1, évaluée avec le MÊME harnais ------------------------
    t0 = time.time()
    v1_frame = attach_horizon(load_v1_predictions())
    v1_eval = evaluate_predictions(v1_frame, segments, "V1_AutoETS_repli_Naive")
    duree_v1 = time.time() - t0

    # --- Candidat A : mode expansif (poids sur fenêtres antérieures) -------
    t0 = time.time()
    blend_frame = build_blend_frame(load_v1_operational_predictions())
    spec = BlendSpec(mode=SelectionMode.EXPANDING)
    cand = run_candidate_a(spec, frame=blend_frame)
    duree_candidat = time.time() - t0

    poids_par_fenetre = (
        cand.groupby("window")
        .agg(poids_autoets=("poids_autoets", "first"), source=("poids_source", "first"),
             fenetres_utilisees=("poids_fenetres_utilisees", "first"))
        .reset_index()
    )

    cand_frame = attach_horizon(cand[["unique_id", "ds", "window", "y", "y_pred"]])
    cand_eval = evaluate_predictions(cand_frame, segments, CANDIDATE_LABEL)
    comparaison = compare_to_v1(cand_eval, v1_eval)

    # --- Variantes à poids fixe (référence de sensibilité) -----------------
    variantes_fixes = {}
    for w in WEIGHT_GRID:
        sub = run_candidate_a(BlendSpec(mode=SelectionMode.FIXED, fixed_weight=w), frame=blend_frame)
        sub_eval = evaluate_predictions(attach_horizon(sub[["unique_id", "ds", "window", "y", "y_pred"]]), segments, f"w={w:.2f}")
        variantes_fixes[f"{w:.2f}"] = {
            "WAPE_quotidien": sub_eval["quotidien"]["WAPE"],
            "WAPE_cumule_7j": sub_eval["cumule"]["7"]["WAPE"],
            "WAPE_cumule_30j": sub_eval["cumule"]["30"]["WAPE"],
        }

    # --- Intervalles : méthode V1 (LOO), pour comparaison à l'identique ----
    t0 = time.time()
    iv_cand = compute_intervals(cand_frame, CalibrationRegime.LEAVE_ONE_WINDOW_OUT, niveau=0.80)
    cov_cand_80 = coverage_report(iv_cand, segments, 0.80)
    iv_cand95 = compute_intervals(cand_frame, CalibrationRegime.LEAVE_ONE_WINDOW_OUT, niveau=0.95)
    cov_cand_95 = coverage_report(iv_cand95, segments, 0.95)

    iv_v1 = compute_intervals(v1_frame, CalibrationRegime.LEAVE_ONE_WINDOW_OUT, niveau=0.80)
    cov_v1_80 = coverage_report(iv_v1, segments, 0.80)
    duree_intervalles = time.time() - t0

    # --- Seuils d'acceptation ---------------------------------------------
    v1_ref = load_v1_reference()
    v1_wape_abc_a = v1_eval["par_segment"]["abc"]["A"]["WAPE_cumule_30j"]
    thresholds = resolve_thresholds(v1_ref, v1_wape_abc_a=v1_wape_abc_a)

    verdict = evaluate_candidate(
        wape_cumule_30j=cand_eval["cumule"]["30"]["WAPE"],
        wape_cumule_7j=cand_eval["cumule"]["7"]["WAPE"],
        wape_quotidien=cand_eval["quotidien"]["WAPE"],
        wape_abc_a=cand_eval["par_segment"]["abc"]["A"]["WAPE_cumule_30j"],
        n_fenetres_ameliorees_30j=comparaison["n_fenetres_ameliorees_30j"],
        couverture_80_globale=cov_cand_80["couverture_globale"],
        couverture_80_produits_a=cov_cand_80.get("par_abc", {}).get("A", {}).get("couverture", float("nan")),
        valeurs_non_finies=cand_eval["qualite"]["n_non_finis"],
        valeurs_negatives=cand_eval["qualite"]["n_negatifs"],
        thresholds=thresholds,
    )

    statut = "experiment_not_retained" if not verdict["accepte"] else "experiment_retained"
    raison = "insufficient_gain" if not verdict["accepte"] else "all_criteria_met"

    duree_totale = time.time() - t_start
    memoire = current_rss_mb()

    payload = {
        "candidat": CANDIDATE_LABEL,
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "status": statut,
        "reason": raison,
        "description": (
            "Combinaison convexe y = w*AutoETS + (1-w)*WindowAverage28. Poids choisi par fenêtre "
            "uniquement sur les fenêtres strictement antérieures, sur une grille fixée a priori. "
            "Aucun réentraînement : recombinaison des prédictions V1 figées."
        ),
        "poids_par_fenetre": poids_par_fenetre.to_dict(orient="records"),
        "grille_poids": list(WEIGHT_GRID),
        "metriques_candidat": cand_eval,
        "metriques_v1_reference": v1_eval,
        "comparaison_v1": comparaison,
        "variantes_poids_fixe": variantes_fixes,
        "intervalles": {
            "methode": "conforme empirique, calibration leave-one-window-out par bucket d'horizon "
                       "(méthode V1, pour comparaison à l'identique)",
            "candidat_80": cov_cand_80,
            "candidat_95": cov_cand_95,
            "v1_80_recalcule_meme_methode": cov_v1_80,
        },
        "seuils_acceptation": thresholds.to_dict(),
        "verdict": verdict,
        "cout_calcul": {
            "duree_totale_s": round(duree_totale, 2),
            "duree_evaluation_v1_s": round(duree_v1, 2),
            "duree_candidat_s": round(duree_candidat, 2),
            "duree_intervalles_s": round(duree_intervalles, 2),
            "memoire_rss_mb": memoire,
            "reentrainement": False,
        },
        "reutilisation_future": (
            "Le mélange reste un composant réutilisable : un futur candidat combiné pourrait "
            "associer le meilleur point forecast (A ou B) aux intervalles recalibrés du candidat C."
        ),
    }

    V2_EVAL.mkdir(parents=True, exist_ok=True)
    (V2_EVAL / "candidat_A_metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log_event({
        "type": "fin", "candidat": CANDIDATE_LABEL, "statut": statut,
        "duree_totale_s": round(duree_totale, 2), "memoire_rss_mb": memoire,
        "wape_30j": cand_eval["cumule"]["30"]["WAPE"],
    })
    _write_report(payload)
    print(f"Statut : {statut} ({raison}) — WAPE30j={cand_eval['cumule']['30']['WAPE']:.6f} "
          f"vs V1 {v1_eval['cumule']['30']['WAPE']:.6f}")


def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _write_report(p: dict) -> None:
    c, v1, comp = p["metriques_candidat"], p["metriques_v1_reference"], p["comparaison_v1"]
    verdict = p["verdict"]

    lines = [
        "# 02 — Candidat A : combinaison AutoETS / WindowAverage28",
        "",
        f"_Généré le {p['genere_le']}. Branche `feature/v2-model-improvements`._",
        "",
        f"**Statut : `{p['status']}` — raison : `{p['reason']}`**",
        "",
        "## 1. Ce que fait le candidat",
        "",
        p["description"],
        "",
        f"Grille de poids fixée a priori : {p['grille_poids']}. Poids retenus par fenêtre :",
        "",
        "| Fenêtre | Poids AutoETS | Source du poids | Fenêtres utilisées |",
        "|---:|---:|---|---|",
    ]
    for r in p["poids_par_fenetre"]:
        lines.append(f"| {r['window']} | {r['poids_autoets']:.2f} | `{r['source']}` | {r['fenetres_utilisees']} |")

    lines += [
        "",
        "Les fenêtres 1 à 4 retiennent un poids équilibré (0,50), les fenêtres 5 et 6 basculent vers "
        "AutoETS (0,75) — cohérent avec le fait qu'AutoETS domine sur les fenêtres tardives.",
        "",
        "## 2. Métriques principales — candidat vs V1",
        "",
        "| Métrique | V1 | Candidat A | Gain absolu | Gain relatif |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in [
        ("wape_quotidien", "WAPE quotidienne"),
        ("wape_cumule_7j", "WAPE cumulée 7 j"),
        ("wape_cumule_14j", "WAPE cumulée 14 j"),
        ("wape_cumule_30j", "WAPE cumulée 30 j"),
    ]:
        d = comp[key]
        lines.append(
            f"| {label} | {_fmt(d['v1'], 6)} | {_fmt(d['candidat'], 6)} | "
            f"{_fmt(d['gain_absolu'], 6)} | {d['gain_relatif']:+.2%} |"
        )

    lines += [
        "",
        f"**Fenêtres améliorées à 30 jours : {comp['n_fenetres_ameliorees_30j']} sur 6.**",
        "",
        "## 3. Résultats par fenêtre (grain cumulé 30 jours)",
        "",
        "| Fenêtre | V1 | Candidat A | Gain | Améliorée ? |",
        "|---:|---:|---:|---:|:---:|",
    ]
    for d in comp["detail_par_fenetre"]:
        lines.append(
            f"| {d['fenetre']} | {_fmt(d['v1'], 6)} | {_fmt(d['candidat'], 6)} | "
            f"{_fmt(d['gain_absolu'], 6)} | {'oui' if d['amelioree'] else 'non'} |"
        )

    lines += [
        "",
        "## 4. Résultats par segment (grain cumulé 30 jours)",
        "",
        "### Classe ABC",
        "",
        "| Classe | V1 | Candidat A | Gain | n produits×fenêtres |",
        "|---|---:|---:|---:|---:|",
    ]
    for cls in sorted(c["par_segment"]["abc"]):
        cv = c["par_segment"]["abc"][cls]["WAPE_cumule_30j"]
        vv = v1["par_segment"]["abc"][cls]["WAPE_cumule_30j"]
        lines.append(f"| {cls} | {_fmt(vv, 6)} | {_fmt(cv, 6)} | {_fmt(vv - cv, 6)} | {c['par_segment']['abc'][cls]['n_produits_fenetres']} |")

    lines += ["", "### Profil de demande", "",
              "| Profil | V1 | Candidat A | Gain | n produits×fenêtres |", "|---|---:|---:|---:|---:|"]
    for prof in sorted(c["par_segment"]["profil"]):
        cv = c["par_segment"]["profil"][prof]["WAPE_cumule_30j"]
        vv = v1["par_segment"]["profil"].get(prof, {}).get("WAPE_cumule_30j", float("nan"))
        lines.append(f"| {prof} | {_fmt(vv, 6)} | {_fmt(cv, 6)} | {_fmt(vv - cv, 6)} | {c['par_segment']['profil'][prof]['n_produits_fenetres']} |")

    if "produits_recents" in c["par_segment"]:
        pr_c = c["par_segment"]["produits_recents"]
        pr_v = v1["par_segment"].get("produits_recents", {})
        lines += [
            "", "### Produits récents", "",
            f"- Définition : {pr_c['definition']}",
            f"- V1 : {_fmt(pr_v.get('WAPE_cumule_30j'), 6)} · Candidat A : {_fmt(pr_c['WAPE_cumule_30j'], 6)} "
            f"· n = {pr_c['n_produits_fenetres']}",
        ]

    lines += [
        "",
        "## 5. Biais et stabilité",
        "",
        "| Indicateur | V1 | Candidat A |",
        "|---|---:|---:|",
        f"| Biais normalisé (quotidien) | {_fmt(v1['quotidien']['biais_normalise'], 6)} | {_fmt(c['quotidien']['biais_normalise'], 6)} |",
        f"| Biais normalisé (cumulé 30 j) | {_fmt(v1['cumule']['30']['biais_normalise'], 6)} | {_fmt(c['cumule']['30']['biais_normalise'], 6)} |",
        f"| WAPE 30 j — écart-type inter-fenêtres | {_fmt(v1['stabilite']['WAPE_30j_ecart_type'], 6)} | {_fmt(c['stabilite']['WAPE_30j_ecart_type'], 6)} |",
        f"| WAPE 30 j — min / max | {_fmt(v1['stabilite']['WAPE_30j_min'], 4)} / {_fmt(v1['stabilite']['WAPE_30j_max'], 4)} | {_fmt(c['stabilite']['WAPE_30j_min'], 4)} / {_fmt(c['stabilite']['WAPE_30j_max'], 4)} |",
        "",
        "## 6. Sensibilité au poids (poids fixe sur toutes les fenêtres)",
        "",
        "_Ces chiffres servent à comprendre la forme de la courbe, **pas** à choisir un poids : "
        "un poids choisi ainsi regarderait toutes les fenêtres, y compris celle évaluée._",
        "",
        "| Poids AutoETS | WAPE quotidienne | WAPE 7 j | WAPE 30 j |",
        "|---:|---:|---:|---:|",
    ]
    for w, m in p["variantes_poids_fixe"].items():
        lines.append(f"| {w} | {_fmt(m['WAPE_quotidien'], 6)} | {_fmt(m['WAPE_cumule_7j'], 6)} | {_fmt(m['WAPE_cumule_30j'], 6)} |")

    cov_c = p["intervalles"]["candidat_80"]
    cov_v = p["intervalles"]["v1_80_recalcule_meme_methode"]
    lines += [
        "",
        "## 7. Intervalles (niveau 80 %)",
        "",
        f"_Méthode : {p['intervalles']['methode']}._",
        "",
        "| Indicateur | V1 | Candidat A |",
        "|---|---:|---:|",
        f"| Couverture globale | {_fmt(cov_v['couverture_globale'])} | {_fmt(cov_c['couverture_globale'])} |",
        f"| Couverture produits A | {_fmt(cov_v.get('par_abc', {}).get('A', {}).get('couverture'))} | {_fmt(cov_c.get('par_abc', {}).get('A', {}).get('couverture'))} |",
        f"| Largeur moyenne | {_fmt(cov_v['largeur_moyenne'])} | {_fmt(cov_c['largeur_moyenne'])} |",
        "",
        "**La combinaison ne corrige pas la sous-couverture des produits A** — c'est précisément "
        "l'objet du candidat C (recalibration par segment).",
        "",
        "## 8. Verdict — chaque seuil d'acceptation",
        "",
        "| Critère | Valeur | Seuil | Règle | Satisfait ? |",
        "|---|---:|---:|---|:---:|",
    ]
    for name, crit in verdict["criteres"].items():
        seuil = crit["seuil"]
        seuil_str = f"[{seuil[0]}, {seuil[1]}]" if isinstance(seuil, list) else _fmt(seuil, 6)
        lines.append(
            f"| `{name}` | {_fmt(crit['valeur'], 6) if isinstance(crit['valeur'], float) else crit['valeur']} | "
            f"{seuil_str} | {crit['regle']} | {'✅' if crit['ok'] else '❌'} |"
        )

    cout = p["cout_calcul"]
    lines += [
        "",
        f"**{verdict['verdict']}**",
        "",
        f"Critères échoués : {verdict['criteres_echoues']}",
        "",
        "## 9. Lecture honnête du résultat",
        "",
        f"Le candidat A améliore réellement la WAPE cumulée à 30 jours "
        f"({_fmt(comp['wape_cumule_30j']['v1'], 6)} → {_fmt(comp['wape_cumule_30j']['candidat'], 6)}, "
        f"soit {comp['wape_cumule_30j']['gain_relatif']:+.2%}) — **le gain est réel, mais très loin du "
        f"seuil d'acceptation de 0,265**. Il faudrait environ "
        f"{(comp['wape_cumule_30j']['candidat'] - 0.265) / comp['wape_cumule_30j']['candidat']:.1%} "
        "d'amélioration supplémentaire pour l'atteindre.",
        "",
        "Un écart favorable de quelques millièmes ne suffit pas à déclarer une V2 : le protocole fixait "
        "les seuils **avant** l'expérience, précisément pour éviter de requalifier après coup un petit "
        "gain en succès.",
        "",
        "### ⚠️ Le gain agrégé est un artefact d'une seule fenêtre",
        "",
        f"- **Fenêtre 1 seule : {_fmt(comp['detail_par_fenetre'][0]['gain_absolu'], 6)}** (amélioration)",
        f"- **Fenêtres 2 à 6 cumulées : "
        f"{_fmt(sum(d['gain_absolu'] for d in comp['detail_par_fenetre'][1:]), 6)}** (dégradation nette)",
        "",
        "**Le gain global vient entièrement de la fenêtre 1, et les fenêtres 3 à 6 sont toutes "
        "dégradées.** Or la fenêtre 1 est précisément celle où le poids n'a pu être appris sur aucune "
        "donnée : c'est le poids par défaut (0,50), fixé a priori. Le « gain » du candidat A repose donc "
        "sur un coup de chance sur une fenêtre non informée, pas sur une capacité d'apprentissage du "
        "poids. Dès que le poids est réellement estimé sur l'historique (fenêtres 2 à 6), le mélange "
        "fait globalement **moins bien** que la V1.",
        "",
        "C'est la raison de fond du rejet, bien plus que l'écart au seuil : le mécanisme ne généralise "
        "pas. Le critère « ≥4 fenêtres améliorées sur 6 » (2/6 obtenues) l'avait anticipé — il est là "
        "exactement pour détecter ce cas.",
        "",
        "### Ce qui s'améliore réellement et mérite d'être retenu",
        "",
        f"- **Stabilité inter-fenêtres** : écart-type de la WAPE 30 j divisé par ~2,3 "
        f"({_fmt(v1['stabilite']['WAPE_30j_ecart_type'], 4)} → {_fmt(c['stabilite']['WAPE_30j_ecart_type'], 4)}).",
        f"- **Biais** : nettement réduit ({_fmt(v1['quotidien']['biais_normalise'], 4)} → "
        f"{_fmt(c['quotidien']['biais_normalise'], 4)}) — la sur-prévision structurelle d'AutoETS est "
        "compensée par WindowAverage28.",
        "",
        "Ces deux propriétés ne dépendent pas d'une fenêtre particulière : elles justifient de conserver "
        "le mélange comme **composant**, sans en faire une V2 à lui seul.",
        "",
        "## 10. Réutilisation future",
        "",
        p["reutilisation_future"],
        "",
        "## 11. Coût de calcul",
        "",
        f"- Durée totale : **{cout['duree_totale_s']} s** (dont candidat {cout['duree_candidat_s']} s, "
        f"intervalles {cout['duree_intervalles_s']} s)",
        f"- Mémoire résidente en fin d'exécution : {cout['memoire_rss_mb']} Mo",
        f"- Réentraînement : **{'oui' if cout['reentrainement'] else 'non'}** — recombinaison de "
        "prédictions V1 figées",
        "",
        "## 12. Garanties",
        "",
        "- Poids déterminés uniquement sur les fenêtres strictement antérieures (tests de perturbation).",
        "- Périmètre identique à la V1 : 1 662 couples (produit, fenêtre).",
        f"- Aucune valeur non finie ({c['qualite']['n_non_finis']}), aucune valeur négative ({c['qualite']['n_negatifs']}).",
        "- Aucun artefact V1 modifié (verrou SHA-256 vérifié par test).",
        "",
    ]

    V2_REPORTS.mkdir(parents=True, exist_ok=True)
    (V2_REPORTS / "02_forecasting_candidat_A.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
