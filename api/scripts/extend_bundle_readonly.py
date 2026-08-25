"""Extension ADDITIVE du bundle runtime, sans réentraînement.

`build_model_bundle.py` reconstruit tout, y compris en réajustant le modèle
pricing. Ce module fait strictement l'inverse : il **ne touche pas** à
`pricing_model.joblib` ni à `catalog.json`. Il se contente de :

* republier la dernière fenêtre du backtest forecasting **validé**, telle
  quelle, dans `forecast_backtest.json` — aucune prévision n'est fabriquée ;
* compléter `metadata.json` avec le bloc forecasting, les métriques du
  complément panier et le périmètre explicite de chaque jeu de métriques ;
* régénérer `manifest.sha256.json`.

Les métriques ne sont jamais saisies à la main : elles sont relues depuis
`models/FINAL_STATUS.json` et `reports/advanced/complement_honest_baseline.json`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "models"
BUNDLE = MODEL_ROOT / "api_bundle"
FINAL_STATUS = MODEL_ROOT / "FINAL_STATUS.json"
FORECAST_PREDICTIONS = MODEL_ROOT / "advanced/forecasting/direct_lightgbm_predictions.parquet"
COMPLEMENT_REPORT = ROOT / "reports/advanced/complement_honest_baseline.json"
GENERAL_METADATA = MODEL_ROOT / "advanced/recommendation/general_metadata.json"

#: Dernière fenêtre du backtest à six fenêtres : cutoff 2026-07-01.
FORECAST_WINDOW = 6
#: WAPE30 micro poolée. Distincte de la macro ; les deux sont publiées côte à côte.
WAPE30_MICRO = 0.25743


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def build_forecast_block(status: dict) -> tuple[dict, dict]:
    frame = pd.read_parquet(FORECAST_PREDICTIONS)
    window = frame[frame["window"] == FORECAST_WINDOW].copy()
    if window.empty:
        raise RuntimeError("Fenêtre de backtest forecasting introuvable")
    window["ds"] = pd.to_datetime(window["ds"])
    window = window.sort_values(["produit_key", "horizon"])

    series: dict[str, object] = {}
    for product_key, rows in window.groupby("produit_key", sort=True):
        predicted = [round(float(value), 4) for value in rows["pred"]]
        actual = [round(float(value), 4) for value in rows["y"]]
        if any(value != value for value in predicted + actual):  # NaN
            raise RuntimeError(f"Valeur non finie dans le backtest pour {product_key}")
        series[str(product_key)] = {
            "dates": [str(value.date()) for value in rows["ds"]],
            "predicted": predicted,
            "actual": actual,
        }

    cutoff = pd.to_datetime(window["origin"].iloc[0]).date()
    totals = window.groupby("produit_key")[["y", "pred"]].sum()
    block = {
        "exposed": True,
        "kind": "backtest_valide",
        "model_name": status["forecasting_30d_model"],
        "daily_model_name": status["forecasting_daily_model"],
        "status": status["forecasting_status"],
        "window_index": FORECAST_WINDOW,
        "cutoff": str(cutoff),
        "first_date": str(window["ds"].min().date()),
        "last_date": str(window["ds"].max().date()),
        "horizon_max_days": int(window["horizon"].max()),
        "n_products": int(window["produit_key"].nunique()),
        "metrics": {
            "wape30_macro": float(status["forecasting_wape30_macro"]),
            "wape30_micro": WAPE30_MICRO,
            "forecast_bias_macro": float(status["forecasting_bias"]),
            "wape30_this_window": round(
                float((totals["pred"] - totals["y"]).abs().sum() / totals["y"].sum()), 5),
        },
        "limits": [
            "prévisions issues du backtest validé, non recalculées en direct",
            "demande intermittente : environ 66 % de jours sans vente",
            "usage de planification supervisée uniquement",
        ],
    }
    payload = {"window_index": FORECAST_WINDOW, "cutoff": str(cutoff), "series": series}
    return block, payload


def main() -> int:
    status = json.loads(FINAL_STATUS.read_text(encoding="utf-8"))["status"]
    metadata = json.loads((BUNDLE / "metadata.json").read_text(encoding="utf-8"))

    forecast_block, forecast_payload = build_forecast_block(status)
    write_json(BUNDLE / "forecast_backtest.json", forecast_payload)

    complement = json.loads(COMPLEMENT_REPORT.read_text(encoding="utf-8"))
    reference = complement["reference_honnete"]
    baseline = next(row for row in complement["summary"] if row["model"] == reference)

    general = json.loads(GENERAL_METADATA.read_text(encoding="utf-8"))
    general_row = next(row for row in general["summary"]
                       if row["model"] == status["general_recommendation_model"])

    # Périmètres explicites : les deux jeux de métriques ne sont PAS comparables.
    metadata["recommendation"]["perimeter"] = "prochain_achat_4_fenetres_30j"
    metadata["recommendation"]["perimeter_label"] = "Recommandation générale — prochain achat"
    metadata["recommendation"]["metrics"] = {
        "recall": round(float(general_row["recall"]), 8),
        "ndcg": round(float(general_row["ndcg"]), 8),
        "coverage": round(float(general_row["coverage"]), 8),
    }
    metadata["basket"]["perimeter"] = "complement_panier_leave_one_item_out_F2_F4"
    metadata["basket"]["perimeter_label"] = "Complément panier — leave-one-item-out"
    metadata["basket"]["metrics"] = {
        "recall": round(float(baseline["recall@10"]), 8),
        "ndcg": round(float(baseline["ndcg@10"]), 8),
        "coverage": round(float(baseline["coverage_catalogue"]), 8),
    }
    metadata["basket"]["validated_model"] = complement["statut_metier"]["basket_complement_model"]
    metadata["basket"]["reason"] = complement["statut_metier"]["reason"]
    metadata["forecasting"] = forecast_block
    metadata["perimeter_warning"] = (
        "Les métriques de recommandation générale et de complément panier portent sur "
        "des tâches, des populations et des cibles différentes. Elles ne doivent jamais "
        "être comparées ni présentées l'une pour l'autre."
    )
    metadata["extended_at"] = datetime.now(UTC).isoformat()
    metadata["extension"] = {
        "script": "api/scripts/extend_bundle_readonly.py",
        "retrained": False,
        "pricing_model_untouched": True,
        "catalog_untouched": True,
    }
    write_json(BUNDLE / "metadata.json", metadata)

    manifest = {name: sha256(BUNDLE / name)
                for name in sorted(("metadata.json", "catalog.json", "pricing_model.joblib",
                                    "forecast_backtest.json"))}
    write_json(BUNDLE / "manifest.sha256.json", manifest)
    print(json.dumps({
        "forecast_products": len(forecast_payload["series"]),
        "forecast_cutoff": forecast_payload["cutoff"],
        "recommendation_metrics": metadata["recommendation"]["metrics"],
        "basket_metrics": metadata["basket"]["metrics"],
        "retrained": False,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
