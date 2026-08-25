"""Chemins et constantes de l'API produit V4."""
from __future__ import annotations

from pathlib import Path

from src.config.settings import PROJECT_ROOT

MODELS_DIR = PROJECT_ROOT / "models" / "v4"
FINAL_STATUS_PATH = MODELS_DIR / "FINAL_STATUS.json"
API_DATA_DIR = Path(__file__).resolve().parent / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

RECOMMENDATION_CATALOG_PATH = API_DATA_DIR / "recommendation_catalog.json"
PRICING_CATALOG_PATH = API_DATA_DIR / "pricing_catalog.json"
CATEGORICAL_MAPPINGS_PATH = API_DATA_DIR / "categorical_mappings.json"
FORECAST_SNAPSHOT_PATH = API_DATA_DIR / "forecast_snapshot.json"

RECOMMENDATION_TARGETS = ("purchased_after", "added_to_cart_after", "viewed_after_impression")
PRICING_TARGETS = ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j")

FALLBACK_MODEL_NAME = "popularite_globale_v1"
MAX_CANDIDATE_PRODUCTS = 50
MARGIN_FLOOR_RATE = 0.05
