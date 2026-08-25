"""Tests API du produit V4 : reponses valides, entrees invalides, modele
absent, repli, doublons, produits inconnus, prix sous le cout,
serialisation/rechargement des modeles, determinisme."""
from __future__ import annotations

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api_v4.config import MODELS_DIR
from api_v4.main import app
from api_v4.registry import REGISTRY
from api_v4.services import recommendation as recommendation_service
from src.recsys_v4.models import predict as predict_recommendation

client = TestClient(app)


@pytest.fixture(scope="module")
def known_products() -> list[str]:
    products = sorted(REGISTRY.recommendation_catalog.keys())
    assert len(products) >= 5, "le catalogue de recommandation doit contenir au moins 5 produits"
    return products[:5]


@pytest.fixture(scope="module")
def known_pricing_product() -> str:
    return sorted(REGISTRY.pricing_catalog.keys())[0]


# --------------------------------------------------------------------- health


def test_health_returns_ok_and_loaded_models():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data_status"] == "synthetic_academic_experiment"
    assert "purchased_after" in body["models_loaded"]["recommendation"]
    assert "added_to_cart_after" in body["models_loaded"]["recommendation"]


def test_health_identifies_the_v4_service_and_deployed_commit():
    """Permet de verifier depuis l'exterieur que c'est bien l'API V4 qui
    repond, et non l'API V2 deployee separement."""
    body = client.get("/health").json()
    assert body["service"] == "api_v4"
    assert "deployed_commit" in body


def test_metadata_identifies_the_v4_service_and_deployed_commit():
    body = client.get("/metadata").json()
    assert body["service"] == "api_v4"
    assert "deployed_commit" in body


def test_no_v2_route_is_exposed_by_this_service():
    """L'API V2 expose des routes `/api/v1/...` et une sonde `/ready` ; aucune
    ne doit exister ici. C'est le critere d'identification fiable, plus sur
    qu'un simple `/health` present dans les deux services."""
    paths = {route.path for route in app.routes}
    assert not any(p.startswith("/api/v1") for p in paths)
    assert "/ready" not in paths
    for expected in ("/health", "/metadata", "/metrics",
                     "/recommendations", "/recommendations/cart", "/pricing/simulation"):
        assert expected in paths, f"route V4 manquante : {expected}"


def test_metadata_lists_all_models_with_required_fields():
    response = client.get("/metadata")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "synthetic_academic_experiment"
    required = {"domain", "target", "model_name", "version", "metrics",
               "evaluation_window", "limits", "status", "generated_at"}
    for entry in body["models"]:
        assert required <= set(entry.keys()), entry


def test_metadata_marks_viewed_after_impression_exploratory_and_not_default():
    body = client.get("/metadata").json()
    entry = next(e for e in body["models"] if e.get("target") == "viewed_after_impression")
    assert entry["status"] == "exploratory"
    assert entry.get("used_by_default") is False


def test_metadata_marks_purchase_and_cart_models_validated():
    body = client.get("/metadata").json()
    for target in ("purchased_after", "added_to_cart_after"):
        entry = next(e for e in body["models"] if e.get("target") == target)
        assert entry["status"] == "validated_academic"
        assert entry["fallback"] == "popularite_globale_v1"


def test_docs_endpoint_available():
    response = client.get("/docs")
    assert response.status_code == 200


def test_metrics_endpoint_reports_counters():
    """Les compteurs operationnels restent exposes, sous la clef `service`.

    `/metrics` a ete etendu pour servir aussi les scores des trois domaines ;
    les compteurs ont donc ete deplaces a la racine `service` plutot que
    supprimes.
    """
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "service" in body
    assert body["service"]["requests_total"] >= 1
    assert "uptime_seconds" in body["service"]


# ------------------------------------------------------------ recommandation


def test_recommendation_purchase_valid_response(known_products):
    response = client.post("/recommendations", json={"candidate_products": known_products})
    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "purchased_after"
    assert body["model_used"] == "CatBoostRanker"
    assert body["fallback_used"] is False
    assert len(body["results"]) == len(known_products)
    ranks = sorted(item["rank"] for item in body["results"])
    assert ranks == list(range(1, len(known_products) + 1))


def test_recommendation_cart_valid_response(known_products):
    response = client.post("/recommendations/cart", json={"candidate_products": known_products})
    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "added_to_cart_after"
    assert body["model_used"] == "pointwise_conversion"
    assert body["fallback_used"] is False


def test_recommendation_with_known_client_context(known_products):
    payload = {
        "client_id": "CLI_TEST_001",
        "candidate_products": known_products,
        "device": "mobile",
        "source": "recherche",
        "channel": "web",
        "client_purchase_count_before": 3,
        "client_recency_days": 12,
        "client_frequency_90d": 2,
        "client_category_affinity": 1,
    }
    response = client.post("/recommendations", json=payload)
    assert response.status_code == 200


def test_recommendation_rejects_duplicate_candidates(known_products):
    duplicated = known_products + [known_products[0]]
    response = client.post("/recommendations", json={"candidate_products": duplicated})
    assert response.status_code == 422


def test_recommendation_drops_unknown_products_but_scores_known_ones(known_products):
    candidates = known_products + ["PRD_INCONNU_XYZ"]
    response = client.post("/recommendations", json={"candidate_products": candidates})
    assert response.status_code == 200
    body = response.json()
    assert "PRD_INCONNU_XYZ" in body["dropped_products"]
    assert len(body["results"]) == len(known_products)


def test_recommendation_all_unknown_products_is_rejected():
    response = client.post("/recommendations", json={"candidate_products": ["PRD_X1", "PRD_X2"]})
    assert response.status_code == 422


def test_recommendation_rejects_empty_candidate_list():
    response = client.post("/recommendations", json={"candidate_products": []})
    assert response.status_code == 422


def test_recommendation_missing_required_field_is_rejected():
    response = client.post("/recommendations", json={})
    assert response.status_code == 422


def test_recommendation_fallback_when_model_missing(known_products, monkeypatch):
    monkeypatch.setitem(REGISTRY.recommendation_models, "purchased_after", None)
    original = dict(REGISTRY.recommendation_models)
    del REGISTRY.recommendation_models["purchased_after"]
    try:
        response = client.post("/recommendations", json={"candidate_products": known_products})
        assert response.status_code == 200
        body = response.json()
        assert body["fallback_used"] is True
        assert body["model_used"] == "popularite_globale_v1"
        assert body["fallback_reason"] == "modele_indisponible"
        assert len(body["results"]) == len(known_products)
    finally:
        REGISTRY.recommendation_models.clear()
        REGISTRY.recommendation_models.update(original)


def test_recommendation_fallback_when_scoring_raises(known_products, monkeypatch):
    def _boom(model, frame):
        raise RuntimeError("echec simule de scoring")

    monkeypatch.setattr(recommendation_service, "predict_recommendation", _boom)
    response = client.post("/recommendations", json={"candidate_products": known_products})
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "echec_scoring"
    assert body["model_used"] == "popularite_globale_v1"


# ------------------------------------------- contrat de statut lors d'un repli


@pytest.mark.parametrize("endpoint,target,expected_model", [
    ("/recommendations", "purchased_after", "CatBoostRanker"),
    ("/recommendations/cart", "added_to_cart_after", "pointwise_conversion"),
])
def test_status_contract_when_primary_model_is_available(endpoint, target, expected_model, known_products):
    """Modele principal disponible : le modele demande est bien celui servi, et
    les deux statuts coincident."""
    body = client.post(endpoint, json={"candidate_products": known_products}).json()
    assert body["target"] == target
    assert body["fallback_used"] is False
    assert body["model_requested"] == expected_model
    assert body["model_used"] == expected_model
    assert body["target_status"] == "validated_academic"
    assert body["served_model_status"] == "validated_academic"
    assert body["status"] == body["target_status"], "compatibilite ascendante rompue"


@pytest.mark.parametrize("endpoint,target,expected_model", [
    ("/recommendations", "purchased_after", "CatBoostRanker"),
    ("/recommendations/cart", "added_to_cart_after", "pointwise_conversion"),
])
def test_status_contract_when_model_unavailable_triggers_fallback(
        endpoint, target, expected_model, known_products):
    """Modele indisponible : `model_requested` conserve le modele prevu,
    `model_used` designe le repli, et `served_model_status` qualifie le repli
    et non la cible."""
    original = dict(REGISTRY.recommendation_models)
    REGISTRY.recommendation_models.pop(target, None)
    try:
        body = client.post(endpoint, json={"candidate_products": known_products}).json()
        assert body["target"] == target
        assert body["fallback_used"] is True
        assert body["fallback_reason"] == "modele_indisponible"
        assert body["model_requested"] == expected_model
        assert body["model_used"] == "popularite_globale_v1"
        assert body["target_status"] == "validated_academic"
        assert body["served_model_status"] == "validated_academic"
        assert body["status"] == body["target_status"], "compatibilite ascendante rompue"
    finally:
        REGISTRY.recommendation_models.clear()
        REGISTRY.recommendation_models.update(original)


def test_status_contract_when_scoring_fails_triggers_fallback(known_products, monkeypatch):
    def _boom(model, frame):
        raise RuntimeError("echec simule de scoring")

    monkeypatch.setattr(recommendation_service, "predict_recommendation", _boom)
    body = client.post("/recommendations", json={"candidate_products": known_products}).json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "echec_scoring"
    assert body["model_requested"] == "CatBoostRanker"
    assert body["model_used"] == "popularite_globale_v1"
    assert body["served_model_status"] == "validated_academic"


@pytest.mark.parametrize("endpoint", ["/recommendations", "/recommendations/cart"])
def test_served_model_status_always_matches_the_model_actually_used(endpoint, known_products):
    """Coherence stricte : `served_model_status` doit toujours etre le statut
    declare, dans FINAL_STATUS.json, du modele nomme par `model_used` — que le
    repli ait ete declenche ou non."""
    declared = {}
    for entry in client.get("/metadata").json()["models"]:
        if entry["domain"] == "recommendation":
            declared.setdefault(entry["model_name"], set()).add(entry["status"])

    for remove_model in (False, True):
        original = dict(REGISTRY.recommendation_models)
        if remove_model:
            target = "purchased_after" if endpoint == "/recommendations" else "added_to_cart_after"
            REGISTRY.recommendation_models.pop(target, None)
        try:
            body = client.post(endpoint, json={"candidate_products": known_products}).json()
            assert body["served_model_status"] in declared[body["model_used"]], (
                f"served_model_status={body['served_model_status']} incoherent avec "
                f"model_used={body['model_used']}")
        finally:
            REGISTRY.recommendation_models.clear()
            REGISTRY.recommendation_models.update(original)


def test_openapi_documents_the_new_status_fields():
    schema = client.get("/openapi.json").json()
    properties = schema["components"]["schemas"]["RecommendationResponse"]["properties"]
    for field in ("target_status", "model_requested", "model_used", "served_model_status"):
        assert field in properties, f"champ {field} absent de la documentation OpenAPI"
        assert properties[field].get("description"), f"champ {field} sans description OpenAPI"


def test_recommendation_never_uses_exposure_probability_as_feature():
    from src.recsys_v4.dataset import ALL_FEATURES
    assert "product_exposure_probability" not in ALL_FEATURES


def test_recommendation_response_is_deterministic(known_products):
    payload = {"candidate_products": known_products}
    first = client.post("/recommendations", json=payload).json()
    second = client.post("/recommendations", json=payload).json()
    assert first["results"] == second["results"]
    assert first["model_used"] == second["model_used"]


# --------------------------------------------------------------------- pricing


def test_pricing_simulation_valid_response(known_pricing_product):
    response = client.post("/pricing/simulation",
                           json={"produit_key": known_pricing_product, "discount_proposed": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["produit_key"] == known_pricing_product
    assert body["modele"] == "baseline_mediane_produit"
    assert body["garde_fous"]["prix_sous_cout"] is False
    assert body["prix_simule_xof"] >= body["cout_xof"]


def test_pricing_simulation_default_discount_is_zero(known_pricing_product):
    response = client.post("/pricing/simulation", json={"produit_key": known_pricing_product})
    assert response.status_code == 200
    body = response.json()
    assert body["remise_proposee_pct"] == 0.0
    assert body["prix_simule_xof"] == pytest.approx(body["prix_catalogue_xof"], rel=1e-6)


def test_pricing_simulation_unknown_product_returns_404():
    response = client.post("/pricing/simulation", json={"produit_key": "PRD_INCONNU"})
    assert response.status_code == 404


def test_pricing_simulation_rejects_price_below_cost(known_pricing_product):
    response = client.post("/pricing/simulation",
                           json={"produit_key": known_pricing_product, "discount_proposed": 100})
    assert response.status_code == 422


def test_pricing_simulation_rejects_out_of_range_discount(known_pricing_product):
    response = client.post("/pricing/simulation",
                           json={"produit_key": known_pricing_product, "discount_proposed": 150})
    assert response.status_code == 422


def test_pricing_simulation_never_causal_wording(known_pricing_product):
    response = client.post("/pricing/simulation", json={"produit_key": known_pricing_product})
    text = response.json()["avertissement"].lower()
    assert "aucune revendication causale" in text


def test_pricing_simulation_is_deterministic(known_pricing_product):
    payload = {"produit_key": known_pricing_product, "discount_proposed": 5}
    first = client.post("/pricing/simulation", json=payload).json()
    second = client.post("/pricing/simulation", json=payload).json()
    assert first == second


# --------------------------------------------------------- serialisation modeles


@pytest.mark.parametrize("target,expected_model", [
    ("purchased_after", "CatBoostRanker"),
    ("added_to_cart_after", "pointwise_conversion"),
])
def test_recommendation_models_reload_and_score_identically(target, expected_model, known_products):
    path = MODELS_DIR / "recommendation" / target / "model.joblib"
    payload = joblib.load(path)
    reloaded = payload["fitted_model"]
    assert reloaded.name == expected_model

    frame, dropped = recommendation_service._build_feature_frame(known_products, {})
    assert not dropped
    reloaded_scores = predict_recommendation(reloaded, frame)
    live_scores = predict_recommendation(REGISTRY.recommendation_models[target], frame)
    np.testing.assert_allclose(reloaded_scores, live_scores)


def test_pricing_models_reload_and_score_identically(known_pricing_product):
    from src.pricing_v4.models import predict as predict_pricing
    import pandas as pd

    frame = pd.DataFrame([{"produit_key": known_pricing_product}])
    for target in ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j"):
        path = MODELS_DIR / "pricing" / target / "model.joblib"
        reloaded = joblib.load(path)["fitted_model"]
        reloaded_value = predict_pricing(reloaded, frame)
        live_value = predict_pricing(REGISTRY.pricing_models[target], frame)
        np.testing.assert_allclose(reloaded_value, live_value)
