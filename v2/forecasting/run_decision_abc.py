"""Synthèse de décision après les candidats A, B et C.

    python -m v2.forecasting.run_decision_abc

Relit les trois fichiers de métriques déjà produits (aucun recalcul) et
construit le tableau de décision, en distinguant explicitement :

* l'amélioration de la **prévision centrale** (candidats A et B) ;
* l'amélioration de l'**incertitude** (candidat C) ;
* le **système combiné** envisageable (meilleur point forecast + intervalles
  recalibrés).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from v2.evaluation.harness import V2_EVAL, V2_REPORTS


def _fmt(x, nd=6):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def main() -> None:
    a = json.loads((V2_EVAL / "candidat_A_metrics.json").read_text(encoding="utf-8"))
    b = json.loads((V2_EVAL / "candidat_B_metrics.json").read_text(encoding="utf-8"))
    c = json.loads((V2_EVAL / "candidat_C_metrics.json").read_text(encoding="utf-8"))

    v1 = a["metriques_v1_reference"]
    a_m, a_c = a["metriques_candidat"], a["comparaison_v1"]
    b_best_key = b["meilleure_variante"]
    b_best = b["variantes"][b_best_key]
    c80 = c["variantes"]["niveau_80"]
    c_ref, c_best_key = c80["C0_reference_v1_loo_global"], c["meilleure_variante_80"]
    c_best = c80[c_best_key]
    c2 = c80["C2_par_abc"]

    rows = [
        {
            "candidat": "V1 (référence)",
            "wape_30j": v1["cumule"]["30"]["WAPE"],
            "wape_7j": v1["cumule"]["7"]["WAPE"],
            "wape_quotidien": v1["quotidien"]["WAPE"],
            "fenetres_gagnees": "—",
            "couverture_a_80": c_ref["couverture_produits_a"],
            "statut": "Référence — modèle officiel",
        },
        {
            "candidat": "A — mélange AutoETS/WA28",
            "wape_30j": a_m["cumule"]["30"]["WAPE"],
            "wape_7j": a_m["cumule"]["7"]["WAPE"],
            "wape_quotidien": a_m["quotidien"]["WAPE"],
            "fenetres_gagnees": f"{a_c['n_fenetres_ameliorees_30j']}/6",
            "couverture_a_80": a["intervalles"]["candidat_80"].get("par_abc", {}).get("A", {}).get("couverture"),
            "statut": f"`{a['status']}` ({a['reason']})",
        },
        {
            "candidat": f"B — sélection par segment ({b_best_key.split('_')[0]})",
            "wape_30j": b_best["metriques"]["cumule"]["30"]["WAPE"],
            "wape_7j": b_best["metriques"]["cumule"]["7"]["WAPE"],
            "wape_quotidien": b_best["metriques"]["quotidien"]["WAPE"],
            "fenetres_gagnees": f"{b_best['comparaison_v1']['n_fenetres_ameliorees_30j']}/6",
            "couverture_a_80": b_best["intervalles_80"].get("par_abc", {}).get("A", {}).get("couverture"),
            "statut": f"`{b['status']}` ({b['reason']})",
        },
        {
            "candidat": f"C — recalibration intervalles ({c_best_key.split('_')[0]})",
            "wape_30j": v1["cumule"]["30"]["WAPE"],
            "wape_7j": v1["cumule"]["7"]["WAPE"],
            "wape_quotidien": v1["quotidien"]["WAPE"],
            "fenetres_gagnees": "sans objet",
            "couverture_a_80": c_best["couverture_produits_a"],
            "statut": f"`{c['status']}` ({c['reason']})",
        },
    ]

    lines = [
        "# 05 — Décision après les candidats A, B et C",
        "",
        f"_Généré le {datetime.now(timezone.utc).isoformat()}. Branche `feature/v2-model-improvements`. "
        "Aucun candidat D ou E n'a été lancé._",
        "",
        "## 1. Tableau de décision",
        "",
        "| Candidat | WAPE 30 j | WAPE 7 j | WAPE quotidienne | Fenêtres gagnées | Couverture A 80 % | Statut |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['candidat']} | {_fmt(r['wape_30j'])} | {_fmt(r['wape_7j'])} | "
            f"{_fmt(r['wape_quotidien'])} | {r['fenetres_gagnees']} | "
            f"{_fmt(r['couverture_a_80'], 4)} | {r['statut']} |"
        )

    lines += [
        "",
        "_Le candidat C ne modifie pas la prévision centrale : ses colonnes WAPE sont, par construction, "
        "identiques à celles de la V1. Seule la colonne « Couverture A 80 % » change._",
        "",
        "## 2. Deux natures d'amélioration, à ne pas confondre",
        "",
        "### a) Prévision centrale (candidats A et B) — **échec**",
        "",
        f"- **A** : {_fmt(a_m['cumule']['30']['WAPE'])} contre {_fmt(v1['cumule']['30']['WAPE'])} en V1, "
        f"soit {a_c['wape_cumule_30j']['gain_relatif']:+.2%}. Gain réel mais très inférieur au seuil "
        "(0,265), et surtout **concentré sur la seule fenêtre 1**, celle où le poids n'était pas appris "
        "(les fenêtres 3 à 6 sont toutes dégradées). 2 fenêtres améliorées sur 6, contre 4 exigées.",
        f"- **B** : meilleure variante à {_fmt(b_best['metriques']['cumule']['30']['WAPE'])} — **moins "
        "bonne que la V1 et que A**. Les décisions de segment sont instables d'une fenêtre à l'autre "
        "(la part de produits basculés vers WindowAverage28 varie de 0 % à 46 % selon la fenêtre) : "
        "le signal de segmentation est du bruit, pas une structure.",
        "",
        "**Conclusion : sur ce jeu de données, le choix entre AutoETS et WindowAverage28 ne se "
        "généralise ni globalement, ni par segment, ni par produit.** Aucune recombinaison des deux "
        "modèles existants n'améliore durablement la prévision centrale.",
        "",
        "### b) Incertitude (candidat C) — **succès**",
        "",
        f"- Couverture des produits A : **{_fmt(c_ref['couverture_produits_a'], 4)} (V1) → "
        f"{_fmt(c_best['couverture_produits_a'], 4)}** (variante retenue `{c_best_key}`), désormais "
        "dans la cible [78 %, 84 %].",
        f"- Largeur moyenne : {_fmt(c_ref['largeur_moyenne'], 4)} → {_fmt(c_best['largeur_moyenne'], 4)} "
        f"({(c_best['largeur_moyenne']/c_ref['largeur_moyenne']-1):+.2%}) — **le gain n'est pas obtenu "
        "en élargissant les intervalles**, seulement en répartissant mieux la largeur entre segments.",
        f"- Variante alternative C2 (par ABC seul) : couverture A {_fmt(c2['couverture_produits_a'], 4)}, "
        "encore plus proche de la cible sur ce segment précis. Le choix C2/C3 est serré et documenté "
        "au rapport 04 §7.",
        "",
        "**C corrige un défaut réel, documenté et chiffré de la V1** — sans toucher aux prévisions.",
        "",
        "## 3. Système combiné envisageable",
        "",
        "Puisque A et B échouent sur le point forecast et que C réussit sur l'incertitude, le système "
        "combiné pertinent est :",
        "",
        "```",
        "Prévision centrale : V1 inchangée (AutoETS + repli Naive)",
        f"Intervalles        : recalibrés par segment ({c_best_key})",
        "```",
        "",
        "Ce n'est **pas** « meilleur point forecast + C » comme envisagé initialement, puisqu'aucun "
        "candidat n'a produit de meilleur point forecast. Le mélange du candidat A reste néanmoins "
        "conservé comme composant : il améliore réellement la **stabilité inter-fenêtres** "
        f"(écart-type {_fmt(v1['stabilite']['WAPE_30j_ecart_type'], 4)} → "
        f"{_fmt(a_m['stabilite']['WAPE_30j_ecart_type'], 4)}) et le **biais** "
        f"({_fmt(v1['quotidien']['biais_normalise'], 4)} → {_fmt(a_m['quotidien']['biais_normalise'], 4)}), "
        "deux propriétés qui pourraient compter si la priorité métier changeait.",
        "",
        "## 4. Statut de la V2 forecasting à ce stade",
        "",
        "| Volet | Statut |",
        "|---|---|",
        "| Prévision centrale | **La V1 reste le modèle officiel** — aucun candidat ne satisfait les seuils |",
        "| Intervalles | **Amélioration retenue** (candidat C), prête à être proposée |",
        "| Candidats D et E | **Non lancés** — décision en attente |",
        "",
        "## 5. Faut-il lancer les candidats D et E ?",
        "",
        "Les éléments objectifs pour trancher :",
        "",
        "**Arguments pour poursuivre**",
        "",
        "- D (hurdle recalibré) et E (variables métier) sont les seuls candidats qui introduisent une "
        "information nouvelle, là où A, B et C ne font que recombiner ou recalibrer l'existant.",
        "- Le diagnostic de la V1 identifiait la forte intermittence (~50 % de jours à zéro) comme la "
        "cause principale de l'erreur quotidienne : c'est exactement ce que vise un modèle hurdle.",
        "",
        "**Arguments pour s'arrêter**",
        "",
        f"- L'écart à combler reste important : il faudrait passer de {_fmt(v1['cumule']['30']['WAPE'], 4)} "
        f"à 0,265 sur la WAPE 30 j, soit environ "
        f"{(v1['cumule']['30']['WAPE'] - 0.265)/v1['cumule']['30']['WAPE']:.1%} d'amélioration — alors "
        "que le meilleur candidat testé n'a obtenu que +0,67 %, et de façon non généralisable.",
        "- Le hurdle LightGBM avait déjà été testé en V1 et rejeté (biais normalisé >0,10, "
        "discrimination faible du classifieur, ROC-AUC ≈0,62) : D repartirait d'une base déjà connue "
        "comme fragile sur ce jeu de données.",
        "- D et E sont les seules expériences **lourdes** du protocole (45-65 min et 1-3 h estimées), "
        "contre quelques secondes pour A, B et C.",
        "",
        "**Recommandation** : la décision revient au métier. Si l'objectif prioritaire est la fiabilité "
        "des intervalles, **C suffit et peut être proposé dès maintenant**. Si l'objectif est de "
        "réellement abaisser la WAPE 30 j sous 0,265, D et E méritent d'être tentés, mais avec une "
        "attente réaliste : les données actuelles (18 mois, forte intermittence, pas de variation de "
        "prix catalogue) limitent structurellement ce qu'un modèle peut extraire — c'est le même "
        "constat que celui posé en V1 pour les trois modules.",
        "",
        "## 6. Garanties (valables pour A, B et C)",
        "",
        "- Aucun artefact V1 modifié (verrou SHA-256 vérifié à chaque exécution de tests).",
        "- Périmètre strictement identique à la V1 : 6 fenêtres, 1 662 couples (produit, fenêtre).",
        "- Aucune information postérieure au cutoff utilisée (tests de perturbation pour A, régime "
        "strict pour C).",
        "- Aucun réentraînement : A, B et C recombinent ou recalibrent des prédictions V1 figées.",
        "- Aucune écriture Supabase, aucun déploiement.",
        "",
    ]

    (V2_REPORTS / "05_decision_apres_ABC.md").write_text("\n".join(lines), encoding="utf-8")

    synthese = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "tableau_decision": rows,
        "point_forecast": {"statut": "aucun_candidat_retenu", "modele_officiel": "V1 AutoETS + repli Naive"},
        "incertitude": {"statut": "candidat_C_retenu", "variante": c_best_key,
                        "couverture_a_v1": c_ref["couverture_produits_a"],
                        "couverture_a_c": c_best["couverture_produits_a"]},
        "candidats_d_e": "non_lances_decision_en_attente",
    }
    (V2_EVAL / "decision_apres_ABC.json").write_text(
        json.dumps(synthese, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print("Rapport 05 écrit. Point forecast : aucun candidat retenu. Intervalles : C retenu.")


if __name__ == "__main__":
    main()
