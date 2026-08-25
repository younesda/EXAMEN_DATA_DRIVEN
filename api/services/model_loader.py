from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib

INVALIDATED = "invalidated_due_to_target_leakage"
RUNTIME_ALLOWLIST = frozenset(
    {
        "FINAL_STATUS.json",
        "FINAL_STATUS.sha256.json",
        "api_bundle/metadata.json",
        "api_bundle/manifest.sha256.json",
        "api_bundle/catalog.json",
        "api_bundle/forecast_backtest.json",
        "api_bundle/pricing_model.joblib",
    }
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON racine invalide: {path.name}")
    return value


@dataclass(slots=True)
class ModelRegistry:
    ready: bool
    checks: dict[str, bool]
    error: str | None
    status: dict[str, Any]
    metadata: dict[str, Any]
    catalog: dict[str, Any]
    pricing_artifact: dict[str, Any]
    forecast: dict[str, Any]

    @classmethod
    def unavailable(cls, message: str) -> ModelRegistry:
        return cls(False, {"models_loaded": False, "metadata_present": False,
                           "sha256_valid": False, "versions_consistent": False,
                           "forecast_available": False},
                   message, {}, {}, {}, {}, {})


@lru_cache(maxsize=4)
def load_registry(model_root: Path) -> ModelRegistry:
    model_root = model_root.resolve()
    final_status_path = model_root / "FINAL_STATUS.json"
    final_manifest_path = model_root / "FINAL_STATUS.sha256.json"
    bundle_root = model_root / "api_bundle"
    metadata_path = bundle_root / "metadata.json"
    manifest_path = bundle_root / "manifest.sha256.json"

    status = _read_json(final_status_path)
    final_manifest = _read_json(final_manifest_path)
    if final_manifest.get("FINAL_STATUS.json") != sha256(final_status_path):
        raise ValueError("SHA-256 invalide pour FINAL_STATUS.json")
    selected_status = status.get("status", {})
    if selected_status.get("pricing_previous_result_status") == INVALIDATED and (
        selected_status.get("pricing_operational_volume_model") != "lgbm_tweedie_moyenne"
    ):
        raise RuntimeError("Un modèle pricing invalidé a été sélectionné")
    if selected_status.get("general_recommendation_model") != "popularite_globale":
        raise RuntimeError("Le modèle de recommandation n'est pas autorisé")

    metadata = _read_json(metadata_path)
    manifest = _read_json(manifest_path)
    for name, expected in manifest.items():
        relative = f"api_bundle/{name}"
        if relative not in RUNTIME_ALLOWLIST:
            raise ValueError(f"Artefact hors allowlist: {relative}")
        path = bundle_root / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"SHA-256 invalide pour {relative}")

    if metadata.get("bundle_version") != metadata.get("model_version"):
        raise ValueError("Versions du bundle incohérentes")
    if metadata.get("pricing", {}).get("model_name") != selected_status.get(
        "pricing_operational_volume_model"
    ):
        raise ValueError("Version pricing incohérente avec FINAL_STATUS.json")
    if metadata.get("recommendation", {}).get("model_name") != selected_status.get(
        "general_recommendation_model"
    ):
        raise ValueError("Version recommandation incohérente avec FINAL_STATUS.json")

    catalog = _read_json(bundle_root / "catalog.json")
    for product_key, row in catalog.get("pricing_catalog", {}).items():
        if row.get("catalog_price_xof", -1) < 0 or row.get("cost_xof", -1) < 0:
            raise ValueError(f"Prix ou coût catalogue invalide pour {product_key}")
    artifact = joblib.load(bundle_root / "pricing_model.joblib")
    if not isinstance(artifact, dict) or artifact.get("model_name") != "lgbm_tweedie_moyenne":
        raise ValueError("Artefact pricing inattendu")
    if "n_lignes" in artifact.get("features", []):
        raise ValueError("Feature interdite détectée: n_lignes")
    if artifact.get("features") != metadata.get("pricing", {}).get("features"):
        raise ValueError("Features du modèle et métadonnées incohérentes")
    metadata["artifact_sha256"] = manifest

    # Le forecasting est SECONDAIRE : son absence degrade la readiness sans
    # empecher le demarrage, conformement a la regle de readiness degradee.
    forecast: dict[str, Any] = {}
    forecast_path = bundle_root / "forecast_backtest.json"
    if forecast_path.is_file():
        try:
            forecast = _read_json(forecast_path)
        except ValueError:
            forecast = {}

    return ModelRegistry(
        ready=True,
        checks={"models_loaded": True, "metadata_present": True,
                "sha256_valid": True, "versions_consistent": True,
                "forecast_available": bool(forecast)},
        error=None,
        status=status,
        metadata=metadata,
        catalog=catalog,
        pricing_artifact=artifact,
        forecast=forecast,
    )
