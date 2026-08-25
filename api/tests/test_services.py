from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date

import pytest

from api.errors import ApiError
from api.services.pricing import simulate
from api.services.recommendation import recommend


def registry_with_mutable_product(registry, product_key):
    pricing_catalog = dict(registry.catalog["pricing_catalog"])
    pricing_catalog[product_key] = copy.deepcopy(pricing_catalog[product_key])
    catalog = {**registry.catalog, "pricing_catalog": pricing_catalog}
    return replace(registry, catalog=catalog)


def test_model_has_exactly_70_honest_features(registry):
    features = registry.pricing_artifact["features"]
    assert len(features) == 70
    assert "n_lignes" not in features


def test_recommendation_has_no_duplicates(registry):
    results = recommend(registry, 50, [], [])
    keys = [item.product_key for item in results]
    assert len(keys) == len(set(keys))


def test_basket_context_is_excluded(registry):
    context = registry.catalog["recommendation_popularity"][0]["product_key"]
    results = recommend(registry, 10, [], [context])
    assert context not in {item.product_key for item in results}


def test_unsupported_discount(registry, valid_pricing_payload):
    with pytest.raises(ApiError) as caught:
        simulate(registry, valid_pricing_payload["product_key"], date(2026, 8, 18),
                 [99], valid_pricing_payload["features"])
    assert caught.value.status_code == 409
    assert caught.value.code == "unsupported_discount"


def test_price_below_cost_guard(registry, valid_pricing_payload):
    modified = registry_with_mutable_product(registry, valid_pricing_payload["product_key"])
    row = modified.catalog["pricing_catalog"][valid_pricing_payload["product_key"]]
    row["supported_discounts_pct"] = [50.0]
    row["cost_xof"] = row["catalog_price_xof"] * 0.75
    with pytest.raises(ApiError) as caught:
        simulate(modified, valid_pricing_payload["product_key"], date(2026, 8, 18),
                 [50], valid_pricing_payload["features"])
    assert caught.value.code == "price_below_cost"


def test_margin_floor_guard(registry, valid_pricing_payload):
    modified = registry_with_mutable_product(registry, valid_pricing_payload["product_key"])
    row = modified.catalog["pricing_catalog"][valid_pricing_payload["product_key"]]
    row["supported_discounts_pct"] = [0.0]
    row["cost_xof"] = row["catalog_price_xof"] * 0.96
    with pytest.raises(ApiError) as caught:
        simulate(modified, valid_pricing_payload["product_key"], date(2026, 8, 18),
                 [0], valid_pricing_payload["features"])
    assert caught.value.code == "margin_below_floor"


def test_forbidden_target_feature(registry, valid_pricing_payload):
    features = {**valid_pricing_payload["features"], "n_lignes": 2}
    with pytest.raises(ApiError) as caught:
        simulate(registry, valid_pricing_payload["product_key"], date(2026, 8, 18),
                 [0], features)
    assert caught.value.code == "forbidden_features"
