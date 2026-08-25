"""Agregation des scores des trois domaines pour la route `/metrics`.

Principe unique : **aucune valeur n'est ecrite en dur ici**. Tout provient de
`models/v4/FINAL_STATUS.json` (pricing et recommandation) et de
`models/FINAL_STATUS.json` (decision forecasting V2, non rejouee).

Lorsqu'une metrique n'existe pas dans les metadonnees, le service renvoie
`null` — jamais zero, jamais une valeur inventee. Un `0` present dans la
reponse est donc toujours une valeur reellement mesuree.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from api_v4.registry import REGISTRY
from src.config.settings import PROJECT_ROOT

STATUT_V2_PATH = PROJECT_ROOT / "models" / "FINAL_STATUS.json"

#: Correspondance entre les cibles de recommandation et les clefs publiques.
ROLES_RECOMMANDATION = {
    "purchased_after": "purchase",
    "added_to_cart_after": "add_to_cart",
    "viewed_after_impression": "view",
}
CIBLES_PRICING = ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j")


def _statut_v2() -> dict:
    try:
        return json.loads(STATUT_V2_PATH.read_text(encoding="utf-8"))["status"]
    except Exception:  # noqa: BLE001 - une decision V2 illisible ne doit pas faire tomber la route
        return {}


def _ou_null(source: dict, clef: str) -> Optional[Any]:
    """Valeur si elle existe, `None` sinon. Jamais de valeur de remplacement."""
    valeur = source.get(clef)
    return valeur if valeur is not None else None


def forecasting_scores() -> dict:
    """Decision forecasting V2, reprise telle quelle. Aucun modele n'est charge.

    Les metriques detaillees proviennent de l'instantane de backtest ; celles
    qui n'ont pas ete calculees restent a `null` et sont signalees comme
    indisponibles, jamais remplacees par une valeur.
    """
    statut = _statut_v2()
    instantane = REGISTRY.forecast_snapshot or {}
    metriques = instantane.get("metriques", {}) or {}
    victoires = instantane.get("victoires", {}) or {}

    return {
        "daily_model": _ou_null(statut, "forecasting_daily_model"),
        "planning_model": _ou_null(statut, "forecasting_30d_model"),
        "wape30_macro": _ou_null(statut, "forecasting_wape30_macro"),
        "wape30_micro": _ou_null(metriques, "wape30_micro"),
        "forecast_bias_macro": _ou_null(statut, "forecasting_bias"),
        "status": _ou_null(statut, "forecasting_status"),
        "usage": "planification_30j_et_quotidien",
        "horizons": {
            "quotidien": {
                "wape": _ou_null(metriques, "wape_quotidienne"),
                "definition": "erreur relative ponderee, prevision a un jour",
                "disponible": metriques.get("wape_quotidienne") is not None,
            },
            "cumule_7j": {
                "wape": _ou_null(metriques, "wape_cumulee_7j"),
                "definition": "erreur relative ponderee sur le cumul a 7 jours",
                "disponible": metriques.get("wape_cumulee_7j") is not None,
            },
            "cumule_14j": {
                "wape": _ou_null(metriques, "wape_cumulee_14j"),
                "definition": "erreur relative ponderee sur le cumul a 14 jours",
                "disponible": bool(metriques.get("wape_cumulee_14j_disponible", False)),
                "raison_indisponibilite": (
                    None if metriques.get("wape_cumulee_14j_disponible", False)
                    else "horizon non evalue lors du backtest ; valeur non calculee"),
            },
            "cumule_30j": {
                "wape": _ou_null(metriques, "wape_cumulee_30j"),
                "definition": "erreur relative ponderee sur le cumul a 30 jours",
                "disponible": metriques.get("wape_cumulee_30j") is not None,
            },
        },
        "daily_model_metrics": instantane.get("modele_quotidien_metriques"),
        "windows": {
            "evaluated": victoires.get("n_fenetres_evaluees"),
            "won_planning_30d": victoires.get("planification_30j"),
            "won_daily": victoires.get("quotidien"),
            "reference_planning": victoires.get("reference_planification"),
            "reference_daily": victoires.get("reference_quotidien"),
            "detail": instantane.get("fenetres", []),
        },
        "horizons_evaluated": instantane.get("horizons_evalues"),
        "note": ("Previsions issues d'un backtest historique, sans reentrainement "
                 "dans l'API. Une WAPE30 de 0,25831 n'est pas une exactitude de "
                 "90 pour cent : c'est une erreur relative ponderee, mecaniquement "
                 "elevee sur une demande intermittente. Aucune exactitude n'est "
                 "calculee par ce projet."),
    }


def pricing_scores() -> dict:
    """Scores pricing lus depuis les metadonnees finales, cible par cible."""
    cibles: dict[str, dict] = {}
    modele = None
    statut_usage = None
    causal = False
    for cible in CIBLES_PRICING:
        entree = REGISTRY.model_entry("pricing", cible)
        if entree is None:
            cibles[cible] = {"wape_macro": None, "bias_macro": None,
                             "disponible": False, "raison": "cible absente des metadonnees"}
            continue
        metriques = entree.get("metrics", {})
        modele = modele or entree.get("model_name")
        statut_usage = statut_usage or entree.get("usage")
        causal = bool(entree.get("causal_effect_estimated", False))
        cibles[cible] = {
            "wape_macro": _ou_null(metriques, "wape_macro"),
            "wape_micro_pooled": _ou_null(metriques, "wape_micro_pooled"),
            "bias_macro": _ou_null(metriques, "bias"),
            "mae": _ou_null(metriques, "mae"),
            "rmse": _ou_null(metriques, "rmse"),
            "status": entree.get("status"),
            "disponible": True,
        }
    return {
        "model": modele,
        "status": statut_usage or "simulation_only",
        "targets": cibles,
        "causal_effect_estimated": causal,
        "automatic_optimal_price": False,
        "note": ("Aucun modele d'apprentissage n'a battu la mediane par produit. "
                 "Le chiffre d'affaires et la marge simules sont derives du volume "
                 "et du prix simule, jamais d'un effet de demande estime."),
    }


def recommendation_scores() -> dict:
    """Scores recommandation, avec le gain relatif et la p-value independante."""
    resultat: dict[str, dict] = {}
    for cible, role in ROLES_RECOMMANDATION.items():
        entree = REGISTRY.model_entry("recommendation", cible)
        if entree is None:
            resultat[role] = {"model": None, "disponible": False,
                              "raison": "cible absente des metadonnees"}
            continue
        metriques = entree.get("metrics", {})
        resultat[role] = {
            "target": cible,
            "model": entree.get("model_name"),
            "ndcg10": _ou_null(metriques, "ndcg@10"),
            "ndcg10_gain_relative": _ou_null(metriques, "relative_ndcg_gain"),
            "holm_pvalue_independent": _ou_null(metriques, "p_value_holm_independante"),
            "status": entree.get("status"),
            "used_by_default": entree.get("used_by_default"),
            "fallback": entree.get("fallback"),
            "disponible": True,
        }
    return resultat


def tous_les_scores(compteurs: dict) -> dict:
    """Reponse complete de `/metrics` : scores des trois domaines et compteurs."""
    return {
        "statut_donnees": REGISTRY.final_status.get("status", "synthetic_academic_experiment"),
        "forecasting": forecasting_scores(),
        "pricing": pricing_scores(),
        "recommendation": recommendation_scores(),
        "service": compteurs,
        "avertissement": (
            "Scores academiques sur donnees synthetiques. Aucune performance "
            "commerciale reelle n'est revendiquee et aucun effet causal n'est estime."),
    }
