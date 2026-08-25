"""API produit V4 : pricing (simulation) et recommandation (achat, panier).

Statut : `synthetic_academic_experiment`. Service de scoring academique sur
donnees synthetiques, distinct du produit V2 deja publie. Aucune ecriture
Supabase, aucun entrainement declenche par une requete, aucune application
automatique d'un prix ou d'une recommandation.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api_v4.config import STATIC_DIR
from api_v4.registry import REGISTRY
from api_v4.schemas import (
    HealthResponse, PricingSimulationRequest, PricingSimulationResponse,
    RecommendationItem, RecommendationRequest, RecommendationResponse,
)
from api_v4.services import forecast as forecast_service
from api_v4.services import metrics as metrics_service
from api_v4.services import pricing as pricing_service
from api_v4.services import recommendation as recommendation_service

START_TIME = time.time()
METRICS = {"requests_total": 0, "fallback_triggered_total": 0, "errors_total": 0,
          "by_endpoint": {}}

#: Identifiant stable du service, permettant de distinguer sans ambiguite cette
#: API de l'API V2 deployee separement (qui expose des routes `/api/v1/...`).
SERVICE_NAME = "api_v4"


def deployed_commit() -> str:
    """Commit reellement deploye.

    Lit en priorite la variable injectee par la plateforme de deploiement, puis
    celle fixee au build du conteneur. Retourne `unknown` en execution locale,
    ou aucune des deux n'est definie.
    """
    return (os.environ.get("RENDER_GIT_COMMIT")
            or os.environ.get("DEPLOYED_GIT_COMMIT")
            or "unknown")

app = FastAPI(
    title="API produit V4 - pricing et recommandation",
    version="1.0.0",
    description=(
        "Service de scoring academique sur donnees synthetiques "
        "(statut synthetic_academic_experiment). Aucune performance "
        "commerciale reelle n'est revendiquee, aucun resultat n'est "
        "presente comme causal, aucune action n'est appliquee "
        "automatiquement."
    ),
)


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    METRICS["requests_total"] += 1
    endpoint = request.url.path
    METRICS["by_endpoint"][endpoint] = METRICS["by_endpoint"].get(endpoint, 0) + 1
    response = await call_next(request)
    if response.status_code >= 400:
        METRICS["errors_total"] += 1
    return response


STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def console() -> FileResponse:
    """Console web de demonstration. La documentation OpenAPI reste sur /docs."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        deployed_commit=deployed_commit(),
        product=REGISTRY.final_status.get("product", "v4_pricing_recommendation"),
        data_status=REGISTRY.final_status.get("status", "synthetic_academic_experiment"),
        models_loaded={
            "recommendation": sorted(REGISTRY.recommendation_models.keys()),
            "pricing": sorted(REGISTRY.pricing_models.keys()),
        },
        load_errors=dict(REGISTRY.load_errors),
        uptime_seconds=round(REGISTRY.uptime_seconds(), 3),
    )


@app.get("/metadata")
def metadata() -> dict:
    """Fiche de statut consolidee, enrichie de l'identite du service deploye.

    `service` et `deployed_commit` permettent de verifier, depuis l'exterieur,
    que c'est bien cette API (et non l'API V2) qui repond, et sur quelle
    version du code.
    """
    return {
        "service": SERVICE_NAME,
        "deployed_commit": deployed_commit(),
        **REGISTRY.final_status,
    }


@app.get("/metrics")
def metrics() -> dict:
    """Scores des trois domaines, plus les compteurs operationnels.

    Toutes les valeurs de score proviennent des metadonnees finales ; aucune
    n'est ecrite en dur. Une metrique absente vaut `null`, jamais zero.
    Les compteurs operationnels restent disponibles sous la clef `service`.
    """
    compteurs = {**METRICS, "uptime_seconds": round(time.time() - START_TIME, 3)}
    return metrics_service.tous_les_scores(compteurs)


def _handle_recommendation(target: str, request: RecommendationRequest) -> RecommendationResponse:
    context = request.model_dump(exclude={"candidate_products"})
    try:
        outcome = recommendation_service.score_target(target, request.candidate_products, context)
    except recommendation_service.NoValidCandidatesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if outcome.fallback_used:
        METRICS["fallback_triggered_total"] += 1
    return RecommendationResponse(
        target=outcome.target, target_status=outcome.target_status,
        model_requested=outcome.model_requested, model_used=outcome.model_used,
        served_model_status=outcome.served_model_status,
        fallback_used=outcome.fallback_used, fallback_reason=outcome.fallback_reason,
        status=outcome.status, version=outcome.version,
        dropped_products=outcome.dropped_products,
        results=[RecommendationItem(**row) for row in outcome.results],
    )


@app.post("/recommendations", response_model=RecommendationResponse)
def recommendations_achat(request: RecommendationRequest) -> RecommendationResponse:
    """Recommandation d'achat (`purchased_after`) : `CatBoostRanker`, repli
    automatique sur `popularite_globale_v1`."""
    return _handle_recommendation("purchased_after", request)


@app.post("/recommendations/cart", response_model=RecommendationResponse)
def recommendations_panier(request: RecommendationRequest) -> RecommendationResponse:
    """Recommandation d'ajout au panier (`added_to_cart_after`) :
    `pointwise_conversion`, repli automatique sur `popularite_globale_v1`."""
    return _handle_recommendation("added_to_cart_after", request)


@app.get("/catalogue")
def catalogue() -> dict:
    """Listes de produits alimentant les menus de la console.

    Les deux catalogues different : la recommandation ne couvre que les
    produits reellement exposes pendant l'experience (208 sur 300), le
    pricing couvre les 300 produits ayant fait l'objet d'une decision.
    """
    return {
        "recommandation": sorted(REGISTRY.recommendation_catalog.keys()),
        "pricing": sorted(REGISTRY.pricing_catalog.keys()),
    }


@app.get("/pricing/produits")
def pricing_products() -> dict:
    """Liste plate des produits pricing, pour consommation analytique.

    Pendant de `/forecast/produits` : une ligne par produit, directement
    exploitable dans un tableur ou un outil de restitution. Contient le prix
    catalogue, le cout, la marge unitaire au prix catalogue et le volume
    median predit par la baseline.

    Aucune remise n'y est appliquee : pour simuler une remise, utiliser
    `POST /pricing/simulation`.
    """
    lignes = pricing_service.catalogue_complet()
    return {
        "n_produits": len(lignes),
        "modele": "baseline_mediane_produit",
        "statut": "simulation_only",
        "produits": lignes,
        "avertissement": (
            "Volumes issus de la mediane historique par produit. Aucun effet "
            "causal n'est estime et aucun prix optimal n'est calcule. Un volume "
            "nul est une prediction reelle, signalee par le champ volume_nul."),
    }


@app.get("/recommendations/produits")
def recommendation_products() -> dict:
    """Liste plate des produits couverts par la recommandation.

    Ce ne sont PAS des recommandations : une recommandation est contextuelle
    et reclasse des candidats pour un client donne. Cette liste expose les
    scores de popularite alimentant le modele de repli
    `popularite_globale_v1`, utiles pour un tableau de bord.

    Pour un classement reel, utiliser `POST /recommendations` ou
    `POST /recommendations/cart`.
    """
    lignes = recommendation_service.catalogue_complet()
    return {
        "n_produits": len(lignes),
        "modele": "popularite_globale_v1",
        "nature": "scores_de_popularite",
        "produits": lignes,
        "avertissement": (
            "Scores de popularite figes a la fin de la fenetre d'entrainement, "
            "issus du modele de repli. Ils ne constituent pas une recommandation "
            "personnalisee : celle-ci depend du client et des candidats soumis. "
            "Le catalogue de recommandation ne couvre que les produits reellement "
            "exposes pendant l'experience, soit moins que le catalogue pricing."),
    }


@app.get("/forecast")
def forecast_summary() -> dict:
    """Synthese de la prevision 30 jours deja validee.

    Lecture seule : aucun modele de forecasting n'est charge ni reentraine.
    Les valeurs proviennent du backtest hors echantillon du modele V2.
    """
    try:
        return forecast_service.summary()
    except forecast_service.ForecastUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/forecast/produits")
def forecast_products(limite: int = 300) -> dict:
    """Produits couverts par la prevision, avec leur ecart cumule sur 30 jours."""
    try:
        return {"n_produits": len(forecast_service.product_list(limite)),
                "produits": forecast_service.product_list(limite)}
    except forecast_service.ForecastUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/forecast/{produit_key}")
def forecast_by_product(produit_key: str) -> dict:
    """Courbe realise contre prevu, horizon 1 a 30, pour un produit."""
    try:
        return forecast_service.product_forecast(produit_key)
    except forecast_service.ForecastUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except forecast_service.UnknownForecastProductError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"produit inconnu de l'instantane de prevision : {exc}") from exc


@app.post("/pricing/simulation", response_model=PricingSimulationResponse)
def pricing_simulation(request: PricingSimulationRequest) -> PricingSimulationResponse:
    """Simulation pricing uniquement : baseline mediane produit, aucun prix
    optimal automatique, aucune application du resultat."""
    try:
        outcome = pricing_service.simulate(request.produit_key, request.discount_proposed)
    except pricing_service.UnknownProductError as exc:
        raise HTTPException(status_code=404, detail=f"produit inconnu du catalogue pricing : {exc}") from exc
    except pricing_service.PriceBelowCostError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"prix simule ({exc.prix_simule:.2f} XOF) inferieur au cout produit ({exc.cout:.2f} XOF)",
        ) from exc
    except pricing_service.VolumeUnavailableError as exc:
        # Jamais converti en zero : un volume indisponible est une erreur
        # explicite, distincte d'une prediction reellement nulle.
        raise HTTPException(
            status_code=503,
            detail=f"volume non disponible pour {exc.produit_key} : {exc.raison}",
        ) from exc
    return PricingSimulationResponse(**outcome.__dict__)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    METRICS["errors_total"] += 1
    return JSONResponse(status_code=500, content={"detail": "erreur interne inattendue"})
