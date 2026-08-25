from __future__ import annotations

import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import Settings
from api.errors import ApiError, error_response
from api.status import (
    assert_no_invalidated_metric,
    build_domains,
    build_metrics_payload,
    build_models_payload,
)
from api.logging import configure_logging
from api.schemas import (
    BasketRecommendationRequest,
    BasketRecommendationResponse,
    CatalogProduct,
    CatalogResponse,
    ForecastRequest,
    ForecastResponse,
    GeneralRecommendationRequest,
    PricingSimulationRequest,
    PricingSimulationResponse,
    RecommendationResponse,
)
from api.services.forecasting import forecast as forecast_service
from api.services.model_loader import ModelRegistry, load_registry
from api.services.pricing import simulate
from api.services.recommendation import recommend
from api.ui import UI_HTML

STATIC_ROOT = Path(__file__).resolve().parent / "static"

LOGGER = logging.getLogger("model_api")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _catalog_page(request: Request, value: ModelRegistry, limit: int, offset: int,
                  query: str | None):
    """Page de catalogue, triee par popularite puis par reference."""
    pricing_catalog = value.catalog.get("pricing_catalog", {})
    ranks = {row["product_key"]: index
             for index, row in enumerate(value.catalog.get("recommendation_popularity", []), 1)}
    series = value.forecast.get("series", {})
    keys = sorted(pricing_catalog, key=lambda key: (ranks.get(key, 10**6), key))
    if query:
        keys = [key for key in keys if query in key.upper()]
    total = len(keys)
    selected = keys[offset:offset + limit]
    products = [
        CatalogProduct(
            product_key=key,
            catalog_price_xof=float(pricing_catalog[key]["catalog_price_xof"]),
            cost_xof=float(pricing_catalog[key]["cost_xof"]),
            supported_discounts_pct=[float(v) for v in pricing_catalog[key]["supported_discounts_pct"]],
            popularity_rank=ranks.get(key),
            has_forecast=key in series,
        )
        for key in selected
    ]
    return CatalogResponse(request_id=request.state.request_id, total=total,
                           returned=len(products), products=products)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = time.perf_counter()
        try:
            app.state.registry = load_registry(resolved.model_root)
            LOGGER.info(
                "model_registry_loaded",
                extra={"duration_ms": round((time.perf_counter() - started) * 1000, 2)},
            )
        except RuntimeError:
            LOGGER.exception("forbidden_model_selected")
            raise
        except Exception:
            LOGGER.exception("model_registry_unavailable")
            app.state.registry = ModelRegistry.unavailable("Manifeste ou artefact modèle invalide")
        yield

    app = FastAPI(
        title="E-commerce Recommendation & Pricing API",
        version="1.0.0",
        description="Baselines de recommandation et simulations pricing exploratoires non causales.",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        LOGGER.info("request_complete", extra={"request_id": request_id, "method": request.method,
                    "path": request.url.path, "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2)})
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        details = [{"loc": list(item["loc"]), "type": item["type"], "msg": item["msg"]}
                   for item in exc.errors()]
        return error_response(request, 422, "validation_error", "Requête invalide", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = ("La ressource demandée n'existe pas." if exc.status_code == 404
                   else str(exc.detail))
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        LOGGER.exception(
            "internal_error",
            extra={"request_id": getattr(request.state, "request_id", "unknown")},
        )
        return error_response(request, 500, "internal_error", "Erreur interne")

    async def authorize(request: Request, supplied: str | None = Security(API_KEY_HEADER)) -> None:
        expected = request.app.state.settings.api_key
        if expected and (not supplied or not secrets.compare_digest(supplied, expected)):
            raise ApiError(401, "invalid_api_key", "Clé API absente ou invalide")

    def registry(request: Request) -> ModelRegistry:
        value: ModelRegistry = request.app.state.registry
        if not value.ready:
            raise ApiError(503, "models_not_ready", "Modèles non prêts ou manifeste invalide")
        return value

    protected = [Depends(authorize)]

    if STATIC_ROOT.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/ui", include_in_schema=False)
    async def interface():
        page = STATIC_ROOT / "index.html"
        if page.is_file():
            return FileResponse(page, media_type="text/html; charset=utf-8")
        return HTMLResponse(UI_HTML)

    @app.get("/console", response_class=HTMLResponse, include_in_schema=False)
    async def console_historique():
        """Console technique d'origine, conservee pour les tests existants."""
        return UI_HTML

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def ready(request: Request):
        value: ModelRegistry = request.app.state.registry
        if not value.ready:
            return JSONResponse(status_code=503, content={"status": "not_ready", "checks": value.checks})
        return {"status": "ready", "checks": value.checks}

    @app.get("/api/v1/models/status", dependencies=protected, tags=["models"])
    async def models_status(value: ModelRegistry = Depends(registry)):
        return value.metadata

    @app.post("/api/v1/recommendations/general", response_model=RecommendationResponse,
              dependencies=protected, tags=["recommendations"])
    async def general(payload: GeneralRecommendationRequest, request: Request,
                      value: ModelRegistry = Depends(registry)):
        recommendations = recommend(value, payload.k, payload.eligible_product_keys,
                                    payload.exclude_product_keys)
        return RecommendationResponse(
            request_id=request.state.request_id,
            recommendations=recommendations,
            model_name="popularite_globale",
            model_status="validated_baseline",
            personalization_validated=False,
            catalog_coverage_warning=True,
        )

    @app.post("/api/v1/recommendations/basket", response_model=BasketRecommendationResponse,
              dependencies=protected, tags=["recommendations"])
    async def basket(payload: BasketRecommendationRequest, request: Request,
                     value: ModelRegistry = Depends(registry)):
        known = set(value.catalog["pricing_catalog"])
        if unknown := set(payload.product_keys) - known:
            raise ApiError(
                404,
                "unknown_product",
                "Produit du panier inconnu",
                {"product_keys": sorted(unknown)},
            )
        recommendations = recommend(value, payload.k, payload.eligible_product_keys, payload.product_keys)
        return BasketRecommendationResponse(
            request_id=request.state.request_id,
            recommendations=recommendations,
            model_name="popularite_globale",
            model_status="baseline_only",
            personalization_validated=False,
            catalog_coverage_warning=True,
            fallback_used=True,
        )

    @app.post("/api/v1/pricing/simulate", response_model=PricingSimulationResponse,
              dependencies=protected, tags=["pricing"])
    async def pricing(payload: PricingSimulationRequest, request: Request,
                      value: ModelRegistry = Depends(registry)):
        simulations = simulate(value, payload.product_key, payload.decision_date,
                               payload.candidate_discounts_pct, payload.features,
                               strict=not payload.partial_results)
        return PricingSimulationResponse(
            request_id=request.state.request_id,
            product_key=payload.product_key,
            decision_date=payload.decision_date,
            simulations=simulations,
            model_name="lgbm_tweedie_moyenne",
            model_status="exploratory_non_causal",
            automatic_application_allowed=False,
            human_validation_required=True,
            causal_effect_estimated=False,
            pricing_wape=0.5526,
            pricing_bias=0.0013,
        )

    # ------------------------------------------------------------------ metadonnees
    # Lecture publique : aucun de ces endpoints ne calcule ni ne mute quoi que ce
    # soit. Les garder derriere une cle rendrait l'interface inutilisable sans
    # apporter de securite (donnees synthetiques, aucun secret).

    @app.get("/version", tags=["health"])
    async def version(request: Request):
        value: ModelRegistry = request.app.state.registry
        settings_value = request.app.state.settings
        return {
            "api_version": app.version,
            "bundle_version": value.metadata.get("bundle_version"),
            "model_version": value.metadata.get("model_version"),
            "commit": settings_value.git_commit,
            "environment": settings_value.app_env,
            "ready": value.ready,
        }

    @app.get("/metrics", tags=["models"])
    async def metrics(value: ModelRegistry = Depends(registry)):
        payload = build_metrics_payload(value.status, value.metadata)
        assert_no_invalidated_metric(payload)
        return payload

    @app.get("/models", tags=["models"])
    async def models(value: ModelRegistry = Depends(registry)):
        return build_models_payload(value.status, value.metadata)

    @app.get("/api/v1/catalog/products", response_model=CatalogResponse, tags=["catalogue"])
    async def catalog_products(request: Request, limit: int = 300, offset: int = 0,
                               value: ModelRegistry = Depends(registry)):
        limit = max(1, min(int(limit), 300))
        offset = max(0, int(offset))
        return _catalog_page(request, value, limit, offset, None)

    @app.get("/api/v1/catalog/search", response_model=CatalogResponse, tags=["catalogue"])
    async def catalog_search(request: Request, q: str = "", limit: int = 20,
                             value: ModelRegistry = Depends(registry)):
        limit = max(1, min(int(limit), 50))
        return _catalog_page(request, value, limit, 0, q.strip().upper())

    @app.post("/api/v1/forecast", response_model=ForecastResponse,
              dependencies=protected, tags=["forecasting"])
    async def forecast_endpoint(payload: ForecastRequest, request: Request,
                                value: ModelRegistry = Depends(registry)):
        result = forecast_service(value, payload.product_key, payload.horizon_days)
        return ForecastResponse(request_id=request.state.request_id, **result)

    @app.post("/api/v1/recommendations/session", status_code=501,
              dependencies=protected, tags=["recommendations"])
    async def session(request: Request):
        return JSONResponse(status_code=501, content={
            "request_id": request.state.request_id,
            "error": {"code": "session_model_unavailable",
                      "message": "Le modèle sessionnel n'est pas utilisable."},
            "session_model_status": "non_utilisable",
        })

    return app


app = create_app()
