"""Registre des modeles et instantanes charges par l'API produit V4.

Charge, une seule fois, les artefacts deja entraines
(`models/v4/{pricing,recommendation}/{cible}/model.joblib`), les
instantanes de catalogue (`api_v4/data/*.json`) et la fiche de statut
consolidee (`models/v4/FINAL_STATUS.json`). Aucun entrainement, aucun acces
reseau : tout est local et deja versionne.

Le chargement de chaque modele est isole : l'echec d'un seul modele ne
bloque pas les autres et est consigne dans `load_errors`, consulte par
`GET /health` et utilise par les services pour declencher le repli sur
`popularite_globale_v1`.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import joblib

from api_v4.config import (
    CATEGORICAL_MAPPINGS_PATH, FINAL_STATUS_PATH, FORECAST_SNAPSHOT_PATH, MODELS_DIR,
    PRICING_CATALOG_PATH, PRICING_TARGETS, RECOMMENDATION_CATALOG_PATH,
    RECOMMENDATION_TARGETS,
)


class ModelRegistry:
    def __init__(self) -> None:
        self.final_status: dict = {}
        self.recommendation_models: dict[str, Any] = {}
        self.pricing_models: dict[str, Any] = {}
        self.recommendation_catalog: dict = {}
        self.pricing_catalog: dict = {}
        self.categorical_mappings: dict = {"device": {}, "source": {}, "channel": {}}
        self.forecast_snapshot: dict = {}
        self.load_errors: dict[str, str] = {}
        self.started_at = time.time()
        self.loaded = False

    def load(self) -> None:
        self.load_errors = {}
        try:
            self.final_status = json.loads(FINAL_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - un statut absent ne doit pas empecher l'API de repondre
            self.load_errors["final_status"] = str(exc)
            self.final_status = {"product": "v4_pricing_recommendation",
                                 "status": "synthetic_academic_experiment", "models": []}

        for path, attr in ((RECOMMENDATION_CATALOG_PATH, "recommendation_catalog"),
                          (PRICING_CATALOG_PATH, "pricing_catalog"),
                          (CATEGORICAL_MAPPINGS_PATH, "categorical_mappings"),
                          (FORECAST_SNAPSHOT_PATH, "forecast_snapshot")):
            try:
                setattr(self, attr, json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:  # noqa: BLE001
                self.load_errors[f"catalogue:{path.name}"] = str(exc)

        for target in RECOMMENDATION_TARGETS:
            self._load_recommendation_model(target)
        for target in PRICING_TARGETS:
            self._load_pricing_model(target)

        self.loaded = True

    def _load_recommendation_model(self, target: str) -> None:
        path = MODELS_DIR / "recommendation" / target / "model.joblib"
        try:
            payload = joblib.load(path)
            self.recommendation_models[target] = payload["fitted_model"]
        except Exception as exc:  # noqa: BLE001 - isolation deliberee, un modele indisponible declenche le repli
            self.load_errors[f"recommendation:{target}"] = str(exc)

    def _load_pricing_model(self, target: str) -> None:
        path = MODELS_DIR / "pricing" / target / "model.joblib"
        try:
            payload = joblib.load(path)
            self.pricing_models[target] = payload["fitted_model"]
        except Exception as exc:  # noqa: BLE001
            self.load_errors[f"pricing:{target}"] = str(exc)

    def model_entry(self, domain: str, target: str) -> Optional[dict]:
        for entry in self.final_status.get("models", []):
            if entry.get("domain") == domain and entry.get("target") == target:
                return entry
        return None

    def model_status(self, domain: str, target: str) -> str:
        entry = self.model_entry(domain, target)
        return entry.get("status", "unknown") if entry else "unknown"

    def model_version(self, domain: str, target: str) -> str:
        entry = self.model_entry(domain, target)
        return entry.get("version", "unknown") if entry else "unknown"

    def model_name_for_target(self, domain: str, target: str) -> str:
        """Nom du modele prevu pour cette cible, independamment de ce qui est
        reellement servi (le repli peut differer)."""
        entry = self.model_entry(domain, target)
        return entry.get("model_name", "unknown") if entry else "unknown"

    def entry_by_model_name(self, domain: str, model_name: str) -> Optional[dict]:
        """Fiche d'un modele designe par son nom.

        Reservee aux noms non ambigus dans un domaine donne — typiquement le
        modele de repli `popularite_globale_v1`. Un meme nom peut servir
        plusieurs cibles (`CatBoostRanker` couvre `purchased_after` et
        `viewed_after_impression`) : pour ces cas, passer par la cible.
        """
        for entry in self.final_status.get("models", []):
            if entry.get("domain") == domain and entry.get("model_name") == model_name:
                return entry
        return None

    def status_of_model_name(self, domain: str, model_name: str) -> str:
        entry = self.entry_by_model_name(domain, model_name)
        return entry.get("status", "unknown") if entry else "unknown"

    def uptime_seconds(self) -> float:
        return time.time() - self.started_at


REGISTRY = ModelRegistry()
REGISTRY.load()
