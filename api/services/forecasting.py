"""Consultation des prévisions de demande.

Aucune prévision n'est calculée à la volée. L'API republie la **dernière fenêtre
du backtest validé** du modèle `LightGBM_direct_per_horizon` (cutoff
2026-07-01, 30 jours, 300 produits), telle qu'elle a été mesurée. C'est une
consultation de résultats validés, pas une inférence en direct, et l'API le
déclare explicitement via `kind = "backtest_valide"`.

Un produit absent de la fenêtre n'obtient jamais une prévision inventée : il
reçoit un repli documenté (`fallback_used = true`) construit sur la moyenne du
catalogue, avec son motif.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from api.errors import ApiError
from api.schemas import ForecastPoint
from api.services.model_loader import ModelRegistry


def _series(registry: ModelRegistry, product_key: str) -> dict | None:
    return registry.forecast.get("series", {}).get(product_key)


def forecast(registry: ModelRegistry, product_key: str, horizon_days: int) -> dict:
    if not registry.forecast:
        raise ApiError(503, "forecast_unavailable",
                       "Les prévisions ne sont pas disponibles sur ce déploiement.")
    catalog = registry.catalog.get("pricing_catalog", {})
    if product_key not in catalog:
        raise ApiError(404, "unknown_product", "Le produit demandé est introuvable.")

    block = registry.metadata.get("forecasting", {})
    cutoff = date.fromisoformat(registry.forecast["cutoff"])
    series = _series(registry, product_key)

    fallback_used = False
    fallback_reason = None
    if series is None:
        # Repli explicite : profil moyen du catalogue, jamais une valeur inventée
        # pour ce produit precis.
        fallback_used = True
        fallback_reason = ("Ce produit n'a pas d'historique dans la fenêtre de backtest "
                           "validée. Le profil moyen du catalogue est affiché à titre "
                           "indicatif.")
        all_series = list(registry.forecast.get("series", {}).values())
        if not all_series:
            raise ApiError(503, "forecast_unavailable",
                           "Aucune série de prévision n'est disponible.")
        length = len(all_series[0]["predicted"])
        averaged = [
            round(sum(item["predicted"][index] for item in all_series) / len(all_series), 4)
            for index in range(length)
        ]
        series = {"dates": all_series[0]["dates"], "predicted": averaged, "actual": None}

    horizon = min(horizon_days, len(series["predicted"]))
    dates = series["dates"][:horizon]
    predicted = series["predicted"][:horizon]
    actual = series["actual"][:horizon] if series.get("actual") else None

    points = [
        ForecastPoint(
            date=date.fromisoformat(day),
            predicted_quantity=round(float(value), 4),
            actual_quantity=None if actual is None else round(float(actual[index]), 4),
        )
        for index, (day, value) in enumerate(zip(dates, predicted, strict=True))
    ]
    return {
        "product_key": product_key,
        "horizon_days": horizon,
        "cutoff": cutoff,
        "total_predicted_quantity": round(sum(float(value) for value in predicted), 4),
        "total_actual_quantity": None if actual is None else round(
            sum(float(value) for value in actual), 4),
        "points": points,
        "model_name": block.get("model_name", "LightGBM_direct_per_horizon"),
        "model_status": block.get("status", "validated"),
        "kind": block.get("kind", "backtest_valide"),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
