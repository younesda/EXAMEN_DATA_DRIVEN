"""Source centrale de vérité des statuts et métriques officiels.

Aucun composant ne doit coder une métrique en dur. Tout part de
`models/FINAL_STATUS.json` et du bundle runtime, déjà vérifiés par SHA-256 au
démarrage. Ce module se contente de les traduire en une structure prête à être
affichée, en français, avec le périmètre de chaque chiffre.

Règle de périmètre
------------------
Les métriques de **recommandation générale** (prochain achat, 4 fenêtres de
30 jours) et de **complément panier** (leave-one-item-out F2–F4) portent sur des
tâches différentes. Elles sont exposées séparément, chacune avec son libellé, et
ne sont jamais agrégées ni comparées.

Métriques invalidées
--------------------
`FORBIDDEN_METRICS` liste les valeurs retirées après l'audit de fuite. Elles ne
doivent apparaître nulle part dans une réponse, sauf explicitement étiquetées
comme historique invalidé. `assert_no_invalidated_metric` le vérifie.
"""
from __future__ import annotations

from typing import Any

#: Valeurs invalidées par l'audit — interdites d'affichage comme résultat courant.
FORBIDDEN_METRICS: dict[str, str] = {
    "0.4164": "WAPE pricing invalidée (fuite n_lignes)",
    "0.41637": "WAPE pricing invalidée (fuite n_lignes)",
    "0.437": "Recall@10 complément invalidé (fuite catégorie cible)",
    "0.21264": "NDCG@10 complément invalidé (fuite catégorie cible)",
    "0.1006": "Recall@10 complément invalidé (évaluation in-sample)",
    "0.0485": "NDCG@10 complément invalidé (évaluation in-sample)",
}

_LOWER_IS_BETTER = "Une valeur plus BASSE est meilleure."
_HIGHER_IS_BETTER = "Une valeur plus HAUTE est meilleure."
_NEAR_ZERO_IS_BETTER = "Une valeur proche de ZÉRO est meilleure."


def unwrap(status: dict[str, Any]) -> dict[str, Any]:
    """`FINAL_STATUS.json` enveloppe les statuts sous la clé `status`.

    Le registre conserve le document complet ; les fonctions d'affichage veulent
    le bloc interne. On accepte les deux formes pour éviter toute ambiguïté.
    """
    inner = status.get("status")
    return inner if isinstance(inner, dict) else status


def _metric(key: str, label: str, value: float, unit: str, direction: str,
            explanation: str, caveat: str, better: str) -> dict[str, Any]:
    return {"key": key, "label": label, "value": value, "unit": unit,
            "direction": direction, "explanation": explanation,
            "caveat": caveat, "better": better}


def build_domains(raw_status: dict[str, Any], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Trois modules métier, chacun avec ses métriques et son statut."""
    status = unwrap(raw_status)
    forecasting = metadata.get("forecasting", {})
    pricing = metadata.get("pricing", {})
    recommendation = metadata.get("recommendation", {})
    basket = metadata.get("basket", {})

    forecast_metrics = forecasting.get("metrics", {})
    pricing_metrics = pricing.get("metrics", {})

    return [
        {
            "key": "forecasting",
            "title": "Prévision de la demande",
            "model": status["forecasting_30d_model"],
            "secondary_model": status["forecasting_daily_model"],
            "status": status["forecasting_status"],
            "status_label": "Validé",
            "status_level": "valide",
            "usage": "Planification supervisée à 30 jours. Aucun pilotage automatique.",
            "headline": {"label": "WAPE 30 jours (macro)",
                         "value": forecast_metrics.get("wape30_macro"), "unit": "ratio"},
            "metrics": [
                _metric("wape30_macro", "WAPE 30 jours (macro)",
                        forecast_metrics.get("wape30_macro"), "ratio", "lower",
                        "Erreur moyenne en pourcentage du volume, moyennée sur les six "
                        "fenêtres de test.",
                        "Ne dit rien sur la demande perdue : un jour à zéro vente peut "
                        "être une rupture de stock non observée.",
                        _LOWER_IS_BETTER),
                _metric("wape30_micro", "WAPE 30 jours (micro)",
                        forecast_metrics.get("wape30_micro"), "ratio", "lower",
                        "Même erreur, mais poolée sur toutes les observations au lieu "
                        "d'être moyennée par fenêtre.",
                        "Macro et micro ne doivent jamais être présentées l'une pour "
                        "l'autre.",
                        _LOWER_IS_BETTER),
                _metric("forecast_bias_macro", "Biais de prévision (macro)",
                        forecast_metrics.get("forecast_bias_macro"), "ratio", "zero",
                        "Tendance systématique à sur-prévoir (positif) ou sous-prévoir "
                        "(négatif).",
                        "Un biais nul ne garantit pas une bonne précision : les erreurs "
                        "peuvent se compenser.",
                        _NEAR_ZERO_IS_BETTER),
            ],
            "limits": forecasting.get("limits", []),
        },
        {
            "key": "pricing",
            "title": "Simulation de remise",
            "model": status["pricing_operational_volume_model"],
            "secondary_model": None,
            "status": status["pricing_status"],
            "status_label": "Exploratoire — non causal",
            "status_level": "exploratoire",
            "usage": "Scénario exploratoire sous garde-fous. Validation humaine "
                     "obligatoire, aucune application automatique.",
            "headline": {"label": "WAPE", "value": pricing_metrics.get("wape"), "unit": "ratio"},
            "metrics": [
                _metric("wape", "WAPE quantité", pricing_metrics.get("wape"), "ratio", "lower",
                        "Erreur moyenne sur la quantité vendue, en pourcentage du volume.",
                        "Le prix catalogue est fixe et les campagnes ne sont pas "
                        "randomisées : aucun effet causal ne peut être déduit.",
                        _LOWER_IS_BETTER),
                _metric("forecast_bias", "Biais de volume",
                        pricing_metrics.get("forecast_bias"), "ratio", "zero",
                        "Écart systématique entre volume prévu et volume observé.",
                        "C'est ce biais quasi nul qui autorise l'usage pour une "
                        "simulation de marge.",
                        _NEAR_ZERO_IS_BETTER),
            ],
            "limits": pricing.get("limits", []),
        },
        {
            "key": "recommendation",
            "title": "Recommandation de produits",
            "model": status["general_recommendation_model"],
            "secondary_model": None,
            "status": "validated_baseline",
            "status_label": "Baseline validée",
            "status_level": "valide",
            "usage": "Baseline de popularité. Aucune personnalisation forte n'est "
                     "démontrée.",
            "headline": {"label": "NDCG@10 (prochain achat)",
                         "value": recommendation.get("metrics", {}).get("ndcg"),
                         "unit": "ratio"},
            "perimeters": [
                {
                    "key": "general",
                    "label": recommendation.get("perimeter_label",
                                                "Recommandation générale — prochain achat"),
                    "perimeter": recommendation.get("perimeter"),
                    "description": "Quels produits ce client achètera-t-il ensuite ? "
                                   "Évalué sur 4 fenêtres de 30 jours, end-to-end.",
                    "model": recommendation.get("model_name"),
                    "status": recommendation.get("status"),
                    "metrics": _recommendation_metrics(recommendation.get("metrics", {})),
                },
                {
                    "key": "basket",
                    "label": basket.get("perimeter_label",
                                        "Complément panier — leave-one-item-out"),
                    "perimeter": basket.get("perimeter"),
                    "description": "Quel article manque à ce panier ? Un article masqué "
                                   "par commande, fenêtres F2 à F4.",
                    "model": basket.get("model_name"),
                    "status": basket.get("validated_model", "none_validated"),
                    "metrics": _recommendation_metrics(basket.get("metrics", {})),
                },
            ],
            "limits": recommendation.get("limits", []) + basket.get("limits", []),
        },
    ]


def _recommendation_metrics(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _metric("recall", "Recall@10", metrics.get("recall"), "ratio", "higher",
                "Part des produits réellement achetés qui figurent dans les 10 "
                "recommandations.",
                "Ne mesure pas la personnalisation : une baseline de popularité peut "
                "obtenir un bon score sans connaître le client.",
                _HIGHER_IS_BETTER),
        _metric("ndcg", "NDCG@10", metrics.get("ndcg"), "ratio", "higher",
                "Même idée que le Recall, mais un produit bien classé compte plus "
                "qu'un produit en fin de liste.",
                "Comparable uniquement à l'intérieur d'un même périmètre.",
                _HIGHER_IS_BETTER),
        _metric("coverage", "Couverture catalogue", metrics.get("coverage"), "ratio", "higher",
                "Part des 300 produits qui apparaissent au moins une fois dans un Top-10.",
                "Une couverture faible signale une concentration sur quelques produits, "
                "pas une erreur de modèle.",
                _HIGHER_IS_BETTER),
    ]


def build_metrics_payload(raw_status: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Charge utile de `GET /metrics`, entièrement dérivée des fichiers officiels."""
    status = unwrap(raw_status)
    return {
        "source": "models/FINAL_STATUS.json + models/api_bundle/metadata.json",
        "corrected_after_audit": True,
        "data_nature": "Données synthétiques — projet académique",
        "perimeter_warning": metadata.get("perimeter_warning"),
        "domains": build_domains(raw_status, metadata),
        "invalidated_history": {
            "pricing": {
                "status": status["pricing_previous_result_status"],
                "note": "L'ancienne WAPE pricing de 0,4164 utilisait une variable "
                        "contemporaine de la cible. Elle n'est jamais affichée comme "
                        "résultat courant.",
            },
            "basket": {
                "status": status["basket_previous_results_status"],
                "note": "Les anciennes métriques de complément panier provenaient d'un "
                        "scoring utilisant la catégorie de l'article masqué, puis d'une "
                        "évaluation sans découpe temporelle.",
            },
        },
        "guardrails": {
            "automatic_pricing_allowed": status["automatic_pricing_allowed"],
            "human_validation_required": True,
            "causal_effect_estimated": False,
            "minimum_margin_rate": 0.05,
            "price_never_below_cost": True,
        },
        "session_model_status": status["session_model_status"],
        "rrf_status": status["rrf_status"],
    }


def build_models_payload(raw_status: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Charge utile de `GET /models`."""
    status = unwrap(raw_status)
    return {
        "active_models": metadata.get("active_models", []),
        "models": [
            {"key": "forecasting_30d", "name": status["forecasting_30d_model"],
             "domain": "forecasting", "status": status["forecasting_status"],
             "exposed": bool(metadata.get("forecasting", {}).get("exposed")),
             "usage": "planification cumulée 30 jours"},
            {"key": "forecasting_daily", "name": status["forecasting_daily_model"],
             "domain": "forecasting", "status": status["forecasting_status"],
             "exposed": False,
             "usage": "opération quotidienne, non exposée par l'API"},
            {"key": "pricing_volume", "name": status["pricing_operational_volume_model"],
             "domain": "pricing", "status": status["pricing_status"], "exposed": True,
             "usage": "simulation de remise sous garde-fous"},
            {"key": "recommendation_general", "name": status["general_recommendation_model"],
             "domain": "recommendation", "status": "validated_baseline", "exposed": True,
             "usage": "baseline de popularité, prochain achat"},
            {"key": "basket_complement", "name": status["basket_complement_baseline"],
             "domain": "recommendation", "status": status["basket_complement_model"],
             "exposed": True,
             "usage": "aucun modèle personnalisé validé ; repli sur la popularité"},
            {"key": "session", "name": None, "domain": "recommendation",
             "status": status["session_model_status"], "exposed": False,
             "usage": "non utilisable"},
        ],
        "not_exposed": [
            {"key": "pricing_accuracy", "name": status["pricing_accuracy_model"],
             "reason": "biais de volume de -18,14 % : interdit pour toute simulation de marge"},
        ],
        "no_model_promoted": True,
    }


def assert_no_invalidated_metric(payload: Any) -> None:
    """Refuse toute charge utile contenant une métrique invalidée non étiquetée."""
    import json as _json

    text = _json.dumps(payload, ensure_ascii=False)
    for value, reason in FORBIDDEN_METRICS.items():
        if value in text and "invalidated" not in text:
            raise ValueError("Métrique invalidée exposée : " + value + " (" + reason + ")")
