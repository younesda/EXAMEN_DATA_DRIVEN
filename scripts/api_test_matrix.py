"""Matrice de tests fonctionnels de l'API, sans mutation.

Rejoue une batterie de scenarios (requete valide, champs manquants, mauvais
types, identifiants inexistants, bornes invalides, corps vide) contre une base
URL, et enregistre pour chaque cas : statut HTTP, temps de reponse, extrait de
reponse, exception eventuelle et caractere attendu ou non.

Usage :
    python -m scripts.api_test_matrix --base https://examen-data-driven.onrender.com \
        --label render --out reports/product_v2/api_test_matrix_before.json
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

TIMEOUT = 90
SAMPLE_DATE = str(date(2026, 7, 15))


def _call(base: str, path: str, method: str = "GET", body: Any = None,
          headers: dict[str, str] | None = None, timeout: int = TIMEOUT) -> dict:
    url = base.rstrip("/") + path
    payload = None
    if body is not None:
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=payload, method=method, headers=request_headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            elapsed = time.perf_counter() - started
            return {"status": response.status, "elapsed_s": round(elapsed, 3),
                    "body": raw[:1200].decode("utf-8", "replace"), "exception": None}
    except urllib.error.HTTPError as error:
        raw = error.read()
        return {"status": error.code, "elapsed_s": round(time.perf_counter() - started, 3),
                "body": raw[:1200].decode("utf-8", "replace"), "exception": None}
    except Exception as error:  # noqa: BLE001 - on veut capturer tout incident reseau
        return {"status": None, "elapsed_s": round(time.perf_counter() - started, 3),
                "body": "", "exception": type(error).__name__ + ": " + str(error)[:200]}


def scenarios(product: str, other_product: str) -> list[dict]:
    """Chaque scenario declare les statuts consideres comme acceptables."""
    valid_features = {"stock_at_cutoff": 120.0}
    return [
        # --- sante et metadonnees -------------------------------------------------
        {"id": "health", "path": "/health", "method": "GET", "expected": [200],
         "note": "processus vivant"},
        {"id": "ready", "path": "/ready", "method": "GET", "expected": [200, 503],
         "note": "modeles charges"},
        {"id": "version", "path": "/version", "method": "GET", "expected": [200],
         "note": "version API et commit"},
        {"id": "metrics", "path": "/metrics", "method": "GET", "expected": [200],
         "note": "metriques officielles centralisees"},
        {"id": "models", "path": "/models", "method": "GET", "expected": [200],
         "note": "modeles exposes et statuts"},
        {"id": "models_status_v1", "path": "/api/v1/models/status", "method": "GET",
         "expected": [200], "note": "endpoint modeles existant"},
        {"id": "docs", "path": "/docs", "method": "GET", "expected": [200],
         "note": "documentation Swagger"},
        {"id": "openapi", "path": "/openapi.json", "method": "GET", "expected": [200],
         "note": "schema OpenAPI"},
        {"id": "ui_root", "path": "/", "method": "GET", "expected": [200],
         "note": "interface web"},
        {"id": "route_absente", "path": "/api/v1/inexistant", "method": "GET",
         "expected": [404], "note": "routage inconnu"},
        # --- catalogue et recherche ----------------------------------------------
        {"id": "catalogue", "path": "/api/v1/catalog/products", "method": "GET",
         "expected": [200], "note": "catalogue produit"},
        {"id": "recherche_produit", "path": "/api/v1/catalog/search?q=PRD0000",
         "method": "GET", "expected": [200], "note": "autocompletion produit"},
        # --- recommandation generale ----------------------------------------------
        {"id": "reco_valide", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": {"k": 5}, "expected": [200], "note": "requete valide"},
        {"id": "reco_corps_vide", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": {}, "expected": [200], "note": "corps vide, defauts appliques"},
        {"id": "reco_k_invalide", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": {"k": 0}, "expected": [422], "note": "borne k invalide"},
        {"id": "reco_k_trop_grand", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": {"k": 9999}, "expected": [422], "note": "borne k invalide"},
        {"id": "reco_mauvais_type", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": {"k": "dix"}, "expected": [422], "note": "mauvais type"},
        {"id": "reco_champ_inconnu", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": {"k": 5, "champ_inexistant": 1}, "expected": [422], "note": "extra interdit"},
        {"id": "reco_produit_inexistant", "path": "/api/v1/recommendations/general",
         "method": "POST", "body": {"k": 5, "eligible_product_keys": ["PRD999999"]},
         "expected": [400, 404], "note": "identifiant produit inexistant"},
        {"id": "reco_client_inexistant", "path": "/api/v1/recommendations/general",
         "method": "POST", "body": {"k": 5, "client_key": "CLI999999"},
         "expected": [200, 404], "note": "identifiant client inexistant"},
        {"id": "reco_json_malforme", "path": "/api/v1/recommendations/general", "method": "POST",
         "body": b"{ceci n'est pas du json", "expected": [400, 422], "note": "JSON malforme"},
        # --- complement panier -----------------------------------------------------
        {"id": "panier_valide", "path": "/api/v1/recommendations/basket", "method": "POST",
         "body": {"product_keys": [product], "k": 5}, "expected": [200], "note": "requete valide"},
        {"id": "panier_vide", "path": "/api/v1/recommendations/basket", "method": "POST",
         "body": {"product_keys": [], "k": 5}, "expected": [422], "note": "liste vide"},
        {"id": "panier_produit_inexistant", "path": "/api/v1/recommendations/basket",
         "method": "POST", "body": {"product_keys": ["PRD999999"], "k": 5},
         "expected": [404], "note": "produit inexistant"},
        # --- sessionnel --------------------------------------------------------------
        {"id": "session_non_utilisable", "path": "/api/v1/recommendations/session",
         "method": "POST", "body": {}, "expected": [501], "note": "modele non utilisable"},
        # --- pricing --------------------------------------------------------------
        {"id": "pricing_valide", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [0], "features": valid_features},
         "expected": [200], "note": "requete valide"},
        {"id": "pricing_corps_vide", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {}, "expected": [422], "note": "corps vide"},
        {"id": "pricing_champs_manquants", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product}, "expected": [422], "note": "champs manquants"},
        {"id": "pricing_produit_inexistant", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": "PRD999999", "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [0], "features": valid_features},
         "expected": [404], "note": "produit inexistant"},
        {"id": "pricing_remise_invalide", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [150], "features": valid_features},
         "expected": [422], "note": "remise hors bornes"},
        {"id": "pricing_remise_negative", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [-10], "features": valid_features},
         "expected": [422], "note": "remise negative"},
        {"id": "pricing_remise_non_supportee", "path": "/api/v1/pricing/simulate",
         "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [7], "features": valid_features},
         "expected": [409], "note": "remise hors support historique"},
        {"id": "pricing_feature_interdite", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [0],
                  "features": {"stock_at_cutoff": 120.0, "n_lignes": 3}},
         "expected": [400], "note": "feature contemporaine interdite"},
        {"id": "pricing_sans_features", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [0], "features": {}},
         "expected": [200], "note": "contexte optionnel : repli sur le snapshot catalogue"},
        {"id": "pricing_date_invalide", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": "pas-une-date",
                  "candidate_discounts_pct": [0], "features": valid_features},
         "expected": [422], "note": "date invalide"},
        {"id": "pricing_nan", "path": "/api/v1/pricing/simulate", "method": "POST",
         "body": {"product_key": product, "decision_date": SAMPLE_DATE,
                  "candidate_discounts_pct": [0],
                  "features": {"stock_at_cutoff": float("nan")}},
         "expected": [400, 422], "note": "NaN dans les features"},
        # --- forecasting ------------------------------------------------------------
        {"id": "forecast_valide", "path": "/api/v1/forecast", "method": "POST",
         "body": {"product_key": product, "horizon_days": 30},
         "expected": [200, 404, 501], "note": "forecasting expose ou non"},
        {"id": "forecast_horizon_invalide", "path": "/api/v1/forecast", "method": "POST",
         "body": {"product_key": product, "horizon_days": 999},
         "expected": [422, 404, 501], "note": "horizon invalide"},
    ]


def run(base: str, label: str, product: str, other_product: str,
        headers: dict[str, str] | None = None) -> dict:
    results = []
    for scenario in scenarios(product, other_product):
        outcome = _call(base, scenario["path"], scenario.get("method", "GET"),
                        scenario.get("body"), headers)
        expected = scenario["expected"]
        matched = outcome["status"] in expected
        results.append({
            "id": scenario["id"], "path": scenario["path"],
            "method": scenario.get("method", "GET"), "note": scenario["note"],
            "expected_status": expected, "status": outcome["status"],
            "elapsed_s": outcome["elapsed_s"],
            "response_excerpt": outcome["body"][:400],
            "exception": outcome["exception"],
            "as_expected": matched,
            "is_500": outcome["status"] == 500,
        })
    unexpected = [row for row in results if not row["as_expected"]]
    return {
        "target": base, "label": label,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_scenarios": len(results),
        "n_as_expected": len(results) - len(unexpected),
        "n_unexpected": len(unexpected),
        "n_http_500": sum(1 for row in results if row["is_500"]),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--product", default="PRD000000")
    parser.add_argument("--other-product", default="PRD000001")
    parser.add_argument("--api-key", default="")
    arguments = parser.parse_args()
    headers = {"X-API-Key": arguments.api_key} if arguments.api_key else None
    report = run(arguments.base, arguments.label, arguments.product,
                 arguments.other_product, headers)
    out = Path(arguments.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print("cible :", report["target"])
    print("scenarios :", report["n_scenarios"],
          "| conformes :", report["n_as_expected"],
          "| non conformes :", report["n_unexpected"],
          "| erreurs 500 :", report["n_http_500"])
    print()
    for row in report["results"]:
        flag = "OK " if row["as_expected"] else "!! "
        status = str(row["status"] if row["status"] is not None else "ERR")
        print(f"  {flag}{row['id']:28} {row['method']:5} {status:>4}"
              f" attendu={row['expected_status']} {row['elapsed_s']:>6.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
