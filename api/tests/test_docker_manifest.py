"""Contrôles statiques de l'image Docker, sans démon Docker.

Un module oublié dans une instruction `COPY` casse l'image en production sans
faire échouer le moindre test local : c'est exactement ce qui s'était produit
pour `api/status.py` et `api/static/`. Ces contrôles tournent partout.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_dockerfile_copies_every_runtime_module():
    dockerfile = _dockerfile()
    modules = sorted(path.name for path in (ROOT / "api").glob("*.py"))
    manquants = [name for name in modules if name not in dockerfile]
    assert not manquants, "modules absents du Dockerfile : " + str(manquants)
    assert "api/static" in dockerfile, "le répertoire statique de l'interface n'est pas copié"
    assert "api/services" in dockerfile


def test_dockerfile_never_copies_sensitive_paths():
    dockerfile = _dockerfile()
    for interdit in (".env", "api/tests", "data/raw", "data/processed", "data/cache"):
        assert "COPY " + interdit not in dockerfile, interdit


def test_dockerfile_declares_healthcheck_and_configurable_port():
    dockerfile = _dockerfile()
    assert "HEALTHCHECK" in dockerfile
    assert "/ready" in dockerfile
    assert "${API_PORT}" in dockerfile
    assert "USER api" in dockerfile, "le conteneur ne doit pas tourner en root"


def test_dockerignore_excludes_secrets_and_data():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for motif in (".env", "data", "tests"):
        assert motif in ignore, "motif absent du .dockerignore : " + motif


def test_every_static_asset_referenced_by_the_page_exists():
    page = (ROOT / "api" / "static" / "index.html").read_text(encoding="utf-8")
    for nom in ("styles.css", "app.js"):
        assert "/static/" + nom in page, nom
        assert (ROOT / "api" / "static" / nom).is_file(), nom
