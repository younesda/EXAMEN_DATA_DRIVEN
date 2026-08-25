"""Format d'erreur unique, stable et lisible par un humain.

Toute erreur renvoyée par l'API a exactement cette forme :

    {
      "success": false,
      "error": {
        "code": "PRODUCT_NOT_FOUND",
        "message": "Le produit demandé est introuvable.",
        "details": {},
        "request_id": "..."
      }
    }

`message` est en français et destiné à être affiché tel quel à l'utilisateur ;
`code` est stable et destiné au code appelant ; `details` reste une structure
libre pour le diagnostic. Aucune trace d'exécution, aucun chemin local et aucun
secret ne transitent par ce canal.
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

#: Traduction des codes internes vers un code stable en majuscules.
CODE_ALIASES: dict[str, str] = {
    "unknown_product": "PRODUCT_NOT_FOUND",
    "unknown_eligible_products": "PRODUCT_NOT_FOUND",
    "unknown_client": "CLIENT_NOT_FOUND",
    "validation_error": "VALIDATION_ERROR",
    "missing_required_features": "MISSING_CONTEXT",
    "forbidden_features": "FORBIDDEN_FEATURE",
    "unknown_features": "UNKNOWN_FEATURE",
    "unsupported_discount": "DISCOUNT_NOT_SUPPORTED",
    "feature_extrapolation": "CONTEXT_OUT_OF_RANGE",
    "price_below_cost": "PRICE_BELOW_COST",
    "margin_below_floor": "MARGIN_BELOW_FLOOR",
    "non_finite_feature": "NON_FINITE_VALUE",
    "non_finite_discount": "NON_FINITE_VALUE",
    "models_not_ready": "MODELS_NOT_READY",
    "forecast_unavailable": "FORECAST_UNAVAILABLE",
    "session_model_unavailable": "SESSION_MODEL_UNAVAILABLE",
    "invalid_api_key": "INVALID_API_KEY",
    "internal_error": "INTERNAL_ERROR",
    "not_found": "NOT_FOUND",
}

#: Message utilisateur par défaut, en français, si l'appelant n'en fournit pas.
DEFAULT_MESSAGES: dict[str, str] = {
    "PRODUCT_NOT_FOUND": "Le produit demandé est introuvable.",
    "CLIENT_NOT_FOUND": "Le client demandé est introuvable.",
    "VALIDATION_ERROR": "La requête est incomplète ou mal formée.",
    "MODELS_NOT_READY": "Les modèles ne sont pas encore disponibles. Réessayez dans un instant.",
    "INTERNAL_ERROR": "Une erreur interne est survenue. L'incident a été enregistré.",
    "NOT_FOUND": "La ressource demandée n'existe pas.",
}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def public_code(code: str) -> str:
    return CODE_ALIASES.get(code, code.upper())


def error_response(request: Request, status_code: int, code: str, message: str,
                   details: Any = None) -> JSONResponse:
    stable = public_code(code)
    body = {
        "success": False,
        "error": {
            "code": stable,
            "message": message or DEFAULT_MESSAGES.get(stable, "Une erreur est survenue."),
            "details": details if details is not None else {},
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    }
    return JSONResponse(status_code=status_code, content=body,
                        headers={"X-Request-ID": body["error"]["request_id"]})
