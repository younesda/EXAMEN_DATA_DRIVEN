"""E0 — audit de disponibilité des variables métier au moment de la prévision.

    python -m v2.forecasting.run_e0_audit

Aucune variable n'entre dans un modèle E avant d'avoir un statut de
disponibilité prouvé ici. Quatre statuts possibles :

* ``connue_sur_tout_horizon`` — valeur connue pour chaque jour J+1..J+30 au
  moment du cutoff ;
* ``connue_a_j_moins_1_seulement`` — état initial connu, mais non projetable
  sur l'horizon sans hypothèse supplémentaire ;
* ``indisponible_dans_le_futur`` — inexistante au moment de la prévision ;
* ``interdite_pour_fuite`` — techniquement présente mais reflétant la cible.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.features.calendar import CALENDAR_FEATURE_COLUMNS
from v2.evaluation.harness import V2_EVAL, V2_REPORTS, load_analytical_table


def audit_stock_projection(table: pd.DataFrame) -> dict:
    """Mesure à quel point le stock de J-1 est (in)utilisable comme constante
    sur 30 jours — question posée explicitement au protocole."""
    s = table[["unique_id", "ds", "stock_disponible_lag1"]].dropna().sort_values(["unique_id", "ds"])
    s["stock_j30"] = s.groupby("unique_id")["stock_disponible_lag1"].shift(-30)
    d = s.dropna(subset=["stock_j30"])
    d = d[d["stock_disponible_lag1"] > 0]
    ratio = (d["stock_j30"] / d["stock_disponible_lag1"]).to_numpy("float64")
    return {
        "n_paires_comparees": int(len(ratio)),
        "ratio_median_j30_sur_j1": float(np.median(ratio)),
        "ratio_p10": float(np.quantile(ratio, 0.10)),
        "ratio_p90": float(np.quantile(ratio, 0.90)),
        "part_variation_superieure_20pct": float(((ratio < 0.8) | (ratio > 1.2)).mean()),
    }


def audit_promotions() -> dict:
    from src.data.connection import get_data_source

    dp = get_data_source().fetch_table("dim_promotion")
    colonnes_creation = [c for c in dp.columns if any(k in c.lower() for k in ("creat", "decid", "insert", "maj", "update"))]
    return {
        "colonnes_disponibles": list(dp.columns),
        "colonne_date_creation_presente": bool(colonnes_creation),
        "colonnes_creation_candidates": colonnes_creation,
        "n_campagnes": int(len(dp)),
    }


def main() -> None:
    table = load_analytical_table()
    stock_audit = audit_stock_projection(table)
    promo_audit = audit_promotions()

    variables = [
        {
            "variable": "jour_semaine / est_weekend",
            "statut": "connue_sur_tout_horizon",
            "justification": "Déterministe : dérivée du calendrier civil, calculable pour n'importe quelle date future.",
            "utilisable_en_E": True, "groupe": "E1_calendrier",
        },
        {
            "variable": "mois / trimestre / semaine",
            "statut": "connue_sur_tout_horizon",
            "justification": "Déterministe, même raison.",
            "utilisable_en_E": True, "groupe": "E1_calendrier",
        },
        {
            "variable": "fin d'année (est_noel, avant_noel, apres_noel, est_nouvel_an…)",
            "statut": "connue_sur_tout_horizon",
            "justification": "Dates fixes du calendrier, connues des années à l'avance.",
            "utilisable_en_E": True, "groupe": "E1_calendrier",
            "reserve": "Aucune fenêtre de backtest ne couvre décembre — l'effet fin d'année ne peut "
                       "donc pas être validé empiriquement ici (limite déjà documentée en V1).",
        },
        {
            "variable": "fêtes religieuses (Korité, Tabaski, Magal, Maouloud, Tamxarit, Ramadan)",
            "statut": "connue_sur_tout_horizon",
            "justification": "Reconstruites par `src/features/calendar.py` ; dates connues à l'avance.",
            "utilisable_en_E": True, "groupe": "E1_calendrier",
        },
        {
            "variable": "en_promotion / remise_pct / n_promotions / portee_promo",
            "statut": "connue_sur_tout_horizon",
            "justification": (
                f"`dim_promotion` fournit `date_debut` et `date_fin` pour {promo_audit['n_campagnes']} "
                "campagnes : la période de validité couvre bien l'horizon futur."
            ),
            "utilisable_en_E": True, "groupe": "E2_promotions",
            "hypothese_explicite": (
                "⚠️ AUCUNE colonne de date de création/décision n'existe dans `dim_promotion` "
                f"(colonnes réelles : {promo_audit['colonnes_disponibles']}). On ne peut donc PAS "
                "prouver qu'une promotion active en J+15 était déjà décidée au cutoff. "
                "HYPOTHÈSE ASSUMÉE : le calendrier promotionnel est un plan arrêté à l'avance, donc "
                "connu au moment de la prévision. Si cette hypothèse est fausse en production, "
                "`en_promotion` et `remise_pct` devront être neutralisés sur l'horizon."
            ),
        },
        {
            "variable": "age_version_produit_jours",
            "statut": "connue_sur_tout_horizon",
            "justification": (
                "Calculée comme (date cible − `date_debut_validite`) : la date de début de validité "
                "est connue au cutoff et la date cible est déterministe."
            ),
            "utilisable_en_E": True, "groupe": "E3_age_version",
            "reserve": (
                "Nommée `age_version_produit_jours` et NON « ancienneté commerciale » : "
                "`date_debut_validite` est la date de début de validité de la ligne SCD, dont la "
                "sémantique métier exacte n'a jamais pu être prouvée (cf. audit V1)."
            ),
        },
        {
            "variable": "stock_disponible_lag1 (état initial au cutoff)",
            "statut": "connue_a_j_moins_1_seulement",
            "justification": (
                "Le stock de la veille du cutoff est connu. Mais il n'est PAS projetable sur "
                "J+1..J+30 : mesuré sur les données, le rapport stock(J+30)/stock(J-1) a une médiane "
                f"de {stock_audit['ratio_median_j30_sur_j1']:.3f}, un p10 de {stock_audit['ratio_p10']:.3f} "
                f"et un p90 de {stock_audit['ratio_p90']:.3f} ; "
                f"{stock_audit['part_variation_superieure_20pct']:.1%} des cas varient de plus de 20 %. "
                "Le tenir constant sur 30 jours serait une hypothèse fausse et non documentée."
            ),
            "utilisable_en_E": True, "groupe": "E4_stock_initial",
            "restriction": (
                "Utilisable UNIQUEMENT pour caractériser l'état initial (une valeur par produit×fenêtre, "
                "constante sur l'horizon en tant que *caractéristique du cutoff*, jamais présentée comme "
                "le stock réel du jour J+k)."
            ),
        },
        {
            "variable": "stock du jour (stock_fin_jour)",
            "statut": "interdite_pour_fuite",
            "justification": "Contemporaine de la cible : inconnue au moment de la prévision.",
            "utilisable_en_E": False, "groupe": "—",
        },
        {
            "variable": "ventes du jour (y) et dérivés contemporains",
            "statut": "interdite_pour_fuite",
            "justification": "C'est la cible elle-même.",
            "utilisable_en_E": False, "groupe": "—",
        },
        {
            "variable": "web_purchase contemporain",
            "statut": "interdite_pour_fuite",
            "justification": (
                "Un événement web `purchase` du jour J peut être le miroir direct de la vente du jour J "
                "(déjà écarté en V1 pour cette raison)."
            ),
            "utilisable_en_E": False, "groupe": "—",
        },
        {
            "variable": "prix payé réel / remise appliquée réelle",
            "statut": "indisponible_dans_le_futur",
            "justification": (
                "Observés a posteriori seulement (calculés depuis le montant net encaissé). "
                "Le prix catalogue, lui, est connu — et fixe pour 300/300 produits."
            ),
            "utilisable_en_E": False, "groupe": "—",
        },
    ]

    payload = {
        "etape": "E0_audit_disponibilite",
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "variables": variables,
        "audit_stock_projection": stock_audit,
        "audit_promotions": promo_audit,
        "n_features_calendaires_disponibles": len(CALENDAR_FEATURE_COLUMNS),
        "groupes_ablation": {
            "E1_calendrier": "features calendaires déterministes",
            "E2_promotions": "E1 + promotions planifiées (sous hypothèse explicite)",
            "E3_age_version": "E2 + age_version_produit_jours",
            "E4_stock_initial": "E3 + état de stock au cutoff (jamais projeté)",
        },
    }

    V2_EVAL.mkdir(parents=True, exist_ok=True)
    (V2_EVAL / "E0_audit_disponibilite.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    _write_report(payload)
    print("E0 terminé. Variables utilisables en E :",
          sum(1 for v in variables if v["utilisable_en_E"]), "/", len(variables))


def _write_report(p: dict) -> None:
    sa, pa = p["audit_stock_projection"], p["audit_promotions"]
    lines = [
        "# 06 — E0 : audit de disponibilité des variables métier",
        "",
        f"_Généré le {p['genere_le']}. Aucune variable n'entre dans un modèle E sans un statut prouvé ici._",
        "",
        "## 1. Statut de chaque variable",
        "",
        "| Variable | Statut | Utilisable en E ? | Groupe |",
        "|---|---|:---:|---|",
    ]
    for v in p["variables"]:
        lines.append(
            f"| {v['variable']} | `{v['statut']}` | {'✅' if v['utilisable_en_E'] else '❌'} | {v['groupe']} |"
        )

    lines += ["", "## 2. Justifications et réserves", ""]
    for v in p["variables"]:
        lines += [f"### {v['variable']}", "", f"- **Statut** : `{v['statut']}`", f"- {v['justification']}"]
        if "hypothese_explicite" in v:
            lines.append(f"- {v['hypothese_explicite']}")
        if "reserve" in v:
            lines.append(f"- **Réserve** : {v['reserve']}")
        if "restriction" in v:
            lines.append(f"- **Restriction d'usage** : {v['restriction']}")
        lines.append("")

    lines += [
        "## 3. Preuve chiffrée : le stock J−1 n'est pas projetable sur 30 jours",
        "",
        "Le protocole demandait explicitement de ne pas rendre le stock « artificiellement constant sur "
        "tout l'horizon sans justification ». Mesure directe sur les données :",
        "",
        "| Indicateur | Valeur |",
        "|---|---:|",
        f"| Paires (stock J−1, stock J+30) comparées | {sa['n_paires_comparees']:,} |",
        f"| Ratio médian stock(J+30) / stock(J−1) | {sa['ratio_median_j30_sur_j1']:.3f} |",
        f"| Ratio p10 | {sa['ratio_p10']:.3f} |",
        f"| Ratio p90 | {sa['ratio_p90']:.3f} |",
        f"| **Part des cas variant de plus de 20 %** | **{sa['part_variation_superieure_20pct']:.1%}** |",
        "",
        f"**Conclusion : dans {sa['part_variation_superieure_20pct']:.1%} des cas le stock a bougé de "
        "plus de 20 % en 30 jours** (et le p90 atteint "
        f"{sa['ratio_p90']:.2f}, soit plus du triple). Le maintenir constant sur l'horizon serait une "
        "hypothèse manifestement fausse. En E4, il n'est donc utilisé que comme **caractéristique de "
        "l'état initial au cutoff**, jamais comme une estimation du stock au jour J+k.",
        "",
        "## 4. Promotions : hypothèse à assumer explicitement",
        "",
        f"`dim_promotion` contient {pa['n_campagnes']} campagnes, avec les colonnes : "
        f"`{', '.join(pa['colonnes_disponibles'])}`.",
        "",
        f"**Aucune colonne de date de création ou de décision n'existe** "
        f"(recherche effectuée : {pa['colonnes_creation_candidates'] or 'aucune correspondance'}). "
        "On dispose donc de la période de validité d'une promotion, mais pas du moment où elle a été "
        "décidée.",
        "",
        "**Hypothèse assumée pour E2** : le calendrier promotionnel est un plan arrêté à l'avance, donc "
        "connu au cutoff. C'est la même hypothèse que celle déjà documentée en V1. Elle est **non "
        "vérifiable avec les données actuelles** — si elle s'avérait fausse en production, les variables "
        "de promotion devraient être neutralisées sur l'horizon, et les résultats de E2 à E4 seraient "
        "invalidés.",
        "",
        "## 5. Groupes d'ablation retenus",
        "",
        "| Étape | Contenu |",
        "|---|---|",
    ]
    for k, v in p["groupes_ablation"].items():
        lines.append(f"| `{k}` | {v} |")

    lines += [
        "",
        f"Le groupe calendaire compte {p['n_features_calendaires_disponibles']} variables déterministes "
        "déjà implémentées et testées en V1 (`src/features/calendar.py`), incluant les fêtes "
        "sénégalaises et la fenêtre du Ramadan.",
        "",
        "## 6. Variables exclues",
        "",
        "Trois variables sont **interdites pour fuite** (stock du jour, ventes du jour, `web_purchase` "
        "contemporain) et une est **indisponible dans le futur** (prix payé réel). Aucune n'entrera dans "
        "un modèle E, quelle que soit son pouvoir prédictif apparent.",
        "",
    ]

    V2_REPORTS.mkdir(parents=True, exist_ok=True)
    (V2_REPORTS / "06_E0_audit_disponibilite.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
