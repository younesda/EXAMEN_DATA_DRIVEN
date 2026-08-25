from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app


@pytest.fixture(scope="session")
def model_root() -> Path:
    return Path(__file__).resolve().parents[2] / "models"


@pytest.fixture()
def client(model_root: Path):
    app = create_app(Settings(model_root=model_root))
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


@pytest.fixture()
def registry(client: TestClient):
    return cast(FastAPI, client.app).state.registry


@pytest.fixture()
def valid_pricing_payload(registry):
    product_key, row = next(
        (key, value) for key, value in registry.catalog["pricing_catalog"].items()
        if 0.0 in value["supported_discounts_pct"]
    )
    low, high = row["feature_ranges"]["stock_at_cutoff"]
    return {
        "product_key": product_key,
        "decision_date": "2026-08-18",
        "candidate_discounts_pct": [0],
        "features": {"stock_at_cutoff": (low + high) / 2},
    }
