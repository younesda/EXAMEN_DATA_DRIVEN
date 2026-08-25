"""Tests d'integration du produit V4 : lancement reel du serveur (processus
uvicorn separe, pas seulement le client de test en memoire) et coherence
bout en bout entre `models/v4/FINAL_STATUS.json` et les artefacts sur
disque. Ne reentraine rien, ne modifie aucun fichier forecasting.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
from contextlib import closing

import httpx
import pytest

from api_v4.config import FINAL_STATUS_PATH, MODELS_DIR
from src.config.settings import PROJECT_ROOT


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_v4.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    last_error = None
    try:
        ready = False
        while time.time() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"le serveur s'est arrete prematurement:\n{output}")
            try:
                response = httpx.get(f"{base_url}/health", timeout=1.0)
                if response.status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.5)
        if not ready:
            raise RuntimeError(f"le serveur n'a jamais repondu dans le delai imparti: {last_error}")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def test_every_endpoint_responds_on_a_real_running_server(live_server):
    """Contrairement aux tests API en memoire (TestClient), ce test demarre un
    vrai processus uvicorn : il valide le demarrage reel, l'import du module,
    le chargement du registre et le liage du port, pas seulement le routage
    ASGI en memoire."""
    catalog = json.loads((PROJECT_ROOT / "api_v4" / "data" / "recommendation_catalog.json").read_text(encoding="utf-8"))
    pricing_catalog = json.loads((PROJECT_ROOT / "api_v4" / "data" / "pricing_catalog.json").read_text(encoding="utf-8"))
    products = sorted(catalog.keys())[:5]
    pricing_product = sorted(pricing_catalog.keys())[0]

    assert httpx.get(f"{live_server}/health", timeout=10.0).status_code == 200
    assert httpx.get(f"{live_server}/metadata", timeout=10.0).status_code == 200
    assert httpx.get(f"{live_server}/metrics", timeout=10.0).status_code == 200
    assert httpx.get(f"{live_server}/docs", timeout=10.0).status_code == 200

    reco = httpx.post(f"{live_server}/recommendations", json={"candidate_products": products}, timeout=10.0)
    assert reco.status_code == 200
    assert reco.json()["model_used"] == "CatBoostRanker"

    cart = httpx.post(f"{live_server}/recommendations/cart", json={"candidate_products": products}, timeout=10.0)
    assert cart.status_code == 200
    assert cart.json()["model_used"] == "pointwise_conversion"

    pricing = httpx.post(
        f"{live_server}/pricing/simulation",
        json={"produit_key": pricing_product, "discount_proposed": 10}, timeout=10.0)
    assert pricing.status_code == 200
    assert pricing.json()["modele"] == "baseline_mediane_produit"


def test_final_status_sha256_matches_actual_model_files_on_disk():
    """Coherence bout en bout : l'empreinte consignee dans FINAL_STATUS.json
    pour chaque modele retenu doit correspondre exactement au fichier
    `model.joblib` reellement present sur disque."""
    status = json.loads(FINAL_STATUS_PATH.read_text(encoding="utf-8"))
    checked = 0
    for entry in status["models"]:
        if not entry.get("sha256"):
            continue
        model_path = MODELS_DIR / entry["domain"] / entry["target"] / "model.joblib"
        assert model_path.is_file(), f"artefact manquant pour {entry['domain']}/{entry['target']}"
        assert _sha256(model_path) == entry["sha256"], (
            f"empreinte divergente pour {entry['domain']}/{entry['target']}")
        checked += 1
    assert checked == 6, "les 3 cibles pricing et les 3 cibles recommandation doivent avoir une empreinte"


def test_forecast_is_exposed_in_read_only_mode():
    """La prevision est desormais consultable, mais en lecture seule.

    Ce test remplace un controle anterieur qui exigeait l'absence totale de
    route de prevision. L'invariant qui compte n'est pas l'absence de route :
    c'est qu'aucun modele de forecasting ne soit charge, reentraine ou
    modifie par ce service. Les routes servent un instantane deja calcule.
    """
    from api_v4.main import app
    paths = {route.path for route in app.routes}
    assert "/forecast" in paths
    assert "/forecast/{produit_key}" in paths


def test_no_forecasting_model_is_loaded_by_this_service():
    """Le service ne doit charger aucun artefact de forecasting : la prevision
    provient d'un instantane JSON, jamais d'un modele reexecute."""
    from api_v4.registry import REGISTRY
    charges = set(REGISTRY.recommendation_models) | set(REGISTRY.pricing_models)
    assert not any("forecast" in nom.lower() for nom in charges)

    import sys
    modules_forecasting = [m for m in sys.modules
                           if m.startswith(("src.forecasting", "src.experiments.advanced_forecasting",
                                            "src.pipelines.final_forecasting"))]
    assert not modules_forecasting, (
        f"modules d'entrainement forecasting importes : {modules_forecasting}")


def test_forecast_snapshot_metrics_match_the_validated_decision():
    """Les metriques servies doivent etre exactement celles de la decision V2
    deja validee, sans recalcul ni derive."""
    import json

    from fastapi.testclient import TestClient

    from api_v4.main import app

    statut_v2 = json.loads(
        (PROJECT_ROOT / "models" / "FINAL_STATUS.json").read_text(encoding="utf-8"))["status"]
    servi = TestClient(app).get("/forecast").json()
    assert servi["modele_planification_30j"] == statut_v2["forecasting_30d_model"]
    assert servi["modele_quotidien"] == statut_v2["forecasting_daily_model"]
    assert servi["metriques"]["wape30_macro"] == statut_v2["forecasting_wape30_macro"]
    assert servi["metriques"]["forecast_bias_macro"] == statut_v2["forecasting_bias"]
