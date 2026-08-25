"""Construit le bundle runtime autorisé à partir des sources locales vérifiées."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from src.pricing.feature_registry import allowed_features, validate_matrix

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "models"
OUTPUT = MODEL_ROOT / "api_bundle"
PRICING_DATA = ROOT / "data/cache/advanced_pricing_features.parquet"
RECOMMENDER = MODEL_ROOT / "advanced/recommendation/general_recommender.joblib"
PRICING_METADATA = MODEL_ROOT / "advanced/pricing_corrected/metadata.json"
FINAL_STATUS = MODEL_ROOT / "FINAL_STATUS.json"
VERSION = "1.0.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    status = json.loads(FINAL_STATUS.read_text(encoding="utf-8"))["status"]
    pricing_meta = json.loads(PRICING_METADATA.read_text(encoding="utf-8"))
    if status["pricing_operational_volume_model"] != "lgbm_tweedie_moyenne":
        raise RuntimeError("Le modèle pricing autorisé n'est pas lgbm_tweedie_moyenne")
    if status["general_recommendation_model"] != "popularite_globale":
        raise RuntimeError("La baseline officielle n'est pas popularite_globale")
    if status["pricing_previous_result_status"] != "invalidated_due_to_target_leakage":
        raise RuntimeError("Le statut d'invalidation historique est absent")

    features = allowed_features()
    validate_matrix(features)
    if len(features) != 70 or "n_lignes" in features:
        raise RuntimeError("Registre de features pricing invalide")
    data = pd.read_parquet(PRICING_DATA).sort_values(["produit_key", "ds"])
    model = LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.3, n_estimators=250,
        learning_rate=0.04, num_leaves=31, min_child_samples=40,
        random_state=42, n_jobs=2, verbosity=-1,
    )
    model.fit(data[features], data["quantite"])

    medians = data[features].median(numeric_only=True).to_dict()
    latest = data.groupby("produit_key", sort=True).tail(1).set_index("produit_key")
    pricing_catalog: dict[str, object] = {}
    for product_key, row in latest.iterrows():
        product_rows = data[data["produit_key"] == product_key]
        snapshot: dict[str, float] = {}
        feature_ranges: dict[str, list[float]] = {}
        for feature in features:
            value = row[feature]
            if pd.isna(value):
                value = medians.get(feature, 0.0)
            snapshot[feature] = float(value)
            observed = product_rows[feature].dropna().astype(float)
            minimum = float(observed.min()) if len(observed) else snapshot[feature]
            maximum = float(observed.max()) if len(observed) else snapshot[feature]
            feature_ranges[feature] = [minimum, maximum]
        price = float(row["prix_base_xof"])
        cost = float(row["cout_xof"])
        if price < 0 or cost < 0:
            raise RuntimeError(f"Prix ou coût négatif pour {product_key}")
        pricing_catalog[str(product_key)] = {
            "catalog_price_xof": price,
            "cost_xof": cost,
            "supported_discounts_pct": sorted(float(value) for value in product_rows["remise_pct"].unique()),
            "feature_snapshot": snapshot,
            "feature_ranges": feature_ranges,
        }

    recommendation_artifact = joblib.load(RECOMMENDER)
    products = recommendation_artifact["products"]
    popularities = np.asarray(recommendation_artifact["popularities"], dtype=float)
    maximum = max(float(popularities.max()), 1.0)
    ranking = sorted(zip(products, popularities, strict=True), key=lambda item: (-item[1], item[0]))
    recommendation_popularity = [
        {"product_key": str(product), "score": round(float(score) / maximum, 8)}
        for product, score in ranking
    ]

    OUTPUT.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model_name": "lgbm_tweedie_moyenne", "model": model,
                 "features": features, "model_version": VERSION},
                OUTPUT / "pricing_model.joblib", compress=3)
    write_json(OUTPUT / "catalog.json", {
        "recommendation_popularity": recommendation_popularity,
        "pricing_catalog": pricing_catalog,
    })
    decision = pricing_meta["decisions"]["meilleur_volume_biais_acceptable"]
    metadata = {
        "bundle_version": VERSION,
        "model_version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_sha256": {
            "FINAL_STATUS.json": sha256(FINAL_STATUS),
            "pricing_metadata.json": sha256(PRICING_METADATA),
            "general_recommender.joblib": sha256(RECOMMENDER),
        },
        "active_models": ["popularite_globale", "lgbm_tweedie_moyenne"],
        "recommendation": {
            "model_name": "popularite_globale",
            "status": "validated_baseline",
            "personalization_validated": False,
            "catalog_coverage_warning": True,
            "metrics": {"recall": 0.06685764600105439, "ndcg": 0.0377118374378624},
            "limits": ["baseline globale", "aucune forte personnalisation", "couverture catalogue limitée"],
        },
        "basket": {
            "model_name": "popularite_globale",
            "status": "baseline_only",
            "personalization_validated": False,
            "limits": ["aucun modèle de complément personnalisé validé", "fallback popularité globale"],
        },
        "pricing": {
            "model_name": "lgbm_tweedie_moyenne",
            "status": "exploratory_non_causal",
            "metrics": {"wape": round(float(decision["wape"]), 4),
                        "forecast_bias": round(float(decision["forecast_bias"]), 4)},
            "features": features,
            "feature_count": len(features),
            "forbidden_features": ["n_lignes", "quantite", "ca_xof", "marge_xof",
                                   "prix_unitaire_paye_xof", "niveau_stock"],
            "limits": ["effet non causal", "remises historiquement supportées uniquement",
                       "aucune application automatique", "validation humaine obligatoire"],
            "training_period": {"from": str(pd.to_datetime(data.ds).min().date()),
                                "to": str(pd.to_datetime(data.ds).max().date())},
        },
        "session": {"status": "non_utilisable", "exposed": False},
        "forecasting": {"exposed": False},
        "automatic_decision_allowed": False,
    }
    write_json(OUTPUT / "metadata.json", metadata)
    manifest = {name: sha256(OUTPUT / name)
                for name in ("metadata.json", "catalog.json", "pricing_model.joblib")}
    write_json(OUTPUT / "manifest.sha256.json", manifest)
    print(json.dumps({"output": str(OUTPUT), "products": len(pricing_catalog),
                      "features": len(features), "model": "lgbm_tweedie_moyenne"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
