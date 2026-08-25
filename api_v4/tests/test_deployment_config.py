"""Controles de la configuration de deploiement V4.

Objet : empecher la reapparition du defaut observe en production, ou la
plateforme construisait l'API V2 (copie de `api/` et `models/api_bundle/`,
sonde `/ready`) en croyant deployer la V4.

Ces tests portent sur les fichiers de configuration eux-memes ; ils ne
construisent pas d'image (le demon de conteneurisation n'est pas disponible
dans l'environnement de developpement) et ne deploient rien.
"""
from __future__ import annotations

import yaml

from src.config.settings import PROJECT_ROOT

DOCKERFILE_V4 = PROJECT_ROOT / "Dockerfile.api_v4"
DOCKERFILE_V2 = PROJECT_ROOT / "Dockerfile"
RENDER_YAML = PROJECT_ROOT / "render.yaml"


def _v4_text() -> str:
    return DOCKERFILE_V4.read_text(encoding="utf-8")


def _v4_instructions() -> str:
    """Instructions executables du Dockerfile, commentaires exclus.

    Les commentaires mentionnent volontairement `/ready` et `api/` pour
    expliquer ce qui doit etre evite : les controles doivent donc porter sur
    les instructions reelles, pas sur la documentation qui les accompagne.
    """
    lignes = [l for l in DOCKERFILE_V4.read_text(encoding="utf-8").splitlines()
              if not l.strip().startswith("#")]
    return "\n".join(lignes)


def _render() -> dict:
    return yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))


def _service() -> dict:
    return _render()["services"][0]


# ------------------------------------------------------------- Dockerfile V4


def test_v4_dockerfile_exists():
    assert DOCKERFILE_V4.is_file()


def test_v4_dockerfile_starts_the_v4_application():
    text = _v4_instructions()
    assert "uvicorn api_v4.main:app" in text
    assert "--host 0.0.0.0" in text
    assert "${PORT}" in text or "$PORT" in text


def test_v4_dockerfile_copies_v4_assets_only():
    text = _v4_instructions()
    assert "COPY api_v4 ./api_v4" in text
    assert "models/v4/FINAL_STATUS.json" in text
    assert "models/v4/recommendation/purchased_after/model.joblib" in text


def test_v4_dockerfile_never_copies_v2_assets():
    """Le defaut observe : le conteneur embarquait `api/` et
    `models/api_bundle/`, donc l'API V2."""
    lines = [l.strip() for l in _v4_instructions().splitlines()
             if l.strip().startswith("COPY") and not l.strip().startswith("#")]
    for line in lines:
        assert "models/api_bundle" not in line, line
        # `COPY api/...` est interdit ; `COPY api_v4` est attendu.
        assert not line.startswith("COPY api/"), line
        assert " api/" not in line.replace(" api_v4", " "), line


def test_v4_dockerfile_probes_health_not_ready():
    text = _v4_instructions()
    assert "/health" in text
    assert "/ready" not in text, "/ready appartient a l'API V2"


def test_v4_dockerfile_does_not_start_the_v2_application():
    assert "uvicorn api.main:app" not in _v4_instructions()


# ------------------------------------------------------- Dockerfile V2 intact


def test_v2_dockerfile_is_untouched_and_still_targets_v2():
    """Le service V2 existant ne doit pas etre affecte par la correction."""
    text = DOCKERFILE_V2.read_text(encoding="utf-8")
    assert "uvicorn api.main:app" in text
    assert "models/api_bundle" in text


# --------------------------------------------------------------- render.yaml


def test_render_selects_the_v4_dockerfile_explicitly():
    """Sans designation explicite, le `Dockerfile` racine (V2) serait
    selectionne automatiquement."""
    service = _service()
    assert service["dockerfilePath"] == "./Dockerfile.api_v4"


def test_render_targets_the_working_branch():
    assert _service()["branch"] == "v4/pricing-recommendation-training"


def test_render_health_check_is_the_v4_path():
    assert _service()["healthCheckPath"] == "/health"


def test_render_declares_no_secret():
    """Aucune variable d'environnement ne doit porter de valeur sensible."""
    interdits = ("password", "secret", "token", "api_key", "apikey",
                 "database_url", "supabase")
    for env in _service().get("envVars", []):
        assert "value" in env, f"variable sans valeur explicite : {env}"
        assert env["key"].lower() not in interdits
        assert "postgresql://" not in str(env["value"])


def test_render_service_name_differs_from_the_v2_service():
    assert "v4" in _service()["name"]
