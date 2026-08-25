from __future__ import annotations

from api.errors import ApiError
from api.schemas import RecommendationItem
from api.services.model_loader import ModelRegistry


def recommend(
    registry: ModelRegistry,
    k: int,
    eligible: list[str],
    excluded: list[str],
) -> list[RecommendationItem]:
    popularity: list[dict] = registry.catalog["recommendation_popularity"]
    known = {row["product_key"] for row in popularity}
    unknown_eligible = set(eligible) - known
    if unknown_eligible:
        raise ApiError(400, "unknown_eligible_products", "La liste éligible contient des produits inconnus")
    pool = set(eligible) if eligible else known
    pool.difference_update(excluded)
    selected = [row for row in popularity if row["product_key"] in pool][:k]
    return [
        RecommendationItem(rank=index, product_key=row["product_key"], score=row["score"],
                           reason="popularite_globale")
        for index, row in enumerate(selected, 1)
    ]

