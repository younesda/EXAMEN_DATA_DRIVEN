import pytest
from pydantic import ValidationError

from api.schemas import BasketRecommendationRequest, GeneralRecommendationRequest, PricingSimulationRequest


@pytest.mark.parametrize("k", [0, 51, 1.5, "10"])
def test_k_is_strict_and_bounded(k):
    with pytest.raises(ValidationError):
        GeneralRecommendationRequest.model_validate({"k": k})


def test_duplicate_products_rejected():
    with pytest.raises(ValidationError):
        BasketRecommendationRequest.model_validate({"product_keys": ["PRD1", "PRD1"]})


def test_duplicate_discounts_rejected():
    with pytest.raises(ValidationError):
        PricingSimulationRequest.model_validate({
            "product_key": "PRD1", "decision_date": "2026-08-18",
            "candidate_discounts_pct": [5, 5], "features": {"stock_at_cutoff": 1},
        })


def test_invalid_iso_date_rejected():
    with pytest.raises(ValidationError):
        PricingSimulationRequest.model_validate({
            "product_key": "PRD1", "decision_date": "18/08/2026",
            "candidate_discounts_pct": [5], "features": {"stock_at_cutoff": 1},
        })

