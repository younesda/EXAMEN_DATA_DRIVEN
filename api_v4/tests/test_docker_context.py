"""Verification du contexte de construction des images.

Objet : empecher la reapparition de l'echec de construction observe, ou des
instructions `COPY` designaient des chemins pourtant versionnes mais retires
du contexte par `.dockerignore` (`src`, `models/*`).

Les controles portent sur trois niveaux, car un seul ne suffit pas :
1. la source existe sur le disque ;
2. elle est suivie par la gestion de versions (sinon absente apres un clone) ;
3. elle survit a `.dockerignore` (sinon absente du contexte de construction).

C'est le troisieme niveau qui manquait et qui a laisse passer l'incident.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from src.config.settings import PROJECT_ROOT

DOCKERFILES = {
    "V4": PROJECT_ROOT / "Dockerfile.api_v4",
    "V2": PROJECT_ROOT / "Dockerfile",
}
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"


# --------------------------------------------------------------- utilitaires


def _copy_sources(dockerfile: Path) -> list[str]:
    """Sources de chaque instruction COPY, hors `--from=` (etapes internes)."""
    texte = dockerfile.read_text(encoding="utf-8")
    texte = texte.replace("\\\n", " ")  # recoller les continuations de ligne
    sources: list[str] = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne.upper().startswith("COPY "):
            continue
        if "--from=" in ligne:
            continue  # provient d'une etape precedente, pas du contexte
        jetons = ligne.split()[1:]
        sources.extend(jetons[:-1])  # le dernier jeton est la destination
    return sources


def _tracked_files() -> set[str]:
    sortie = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout
    return {l for l in sortie.splitlines() if l}


def _ignore_rules() -> list[tuple[str, bool]]:
    """Regles de `.dockerignore` : (motif, est_une_exception)."""
    regles = []
    for ligne in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        exception = ligne.startswith("!")
        regles.append((ligne[1:].strip() if exception else ligne, exception))
    return regles


def _segment_match(motif: str, chemin: str) -> bool:
    """Correspondance d'un motif avec un chemin ou l'un de ses parents.

    Reproduit le comportement retenu par le moteur de construction : un motif
    designant un repertoire exclut ce qu'il contient. `**` traverse les
    separateurs, `*` ne les traverse pas.
    """
    motif_regex = re.escape(motif).replace(r"\*\*", "\x00").replace(r"\*", "[^/]*")
    motif_regex = motif_regex.replace("\x00", ".*").replace(r"\?", "[^/]")
    # le motif s'applique au chemin lui-meme ou a n'importe lequel de ses parents
    return re.fullmatch(motif_regex, chemin) is not None or any(
        re.fullmatch(motif_regex, parent) is not None
        for parent in _parents(chemin))


def _parents(chemin: str) -> list[str]:
    morceaux = chemin.split("/")
    return ["/".join(morceaux[:i]) for i in range(1, len(morceaux))]


def _is_excluded(chemin: str) -> bool:
    """Le chemin est-il retire du contexte ? La derniere regle qui correspond
    l'emporte, comme dans le moteur de construction."""
    exclu = False
    for motif, exception in _ignore_rules():
        if _segment_match(motif, chemin):
            exclu = not exception
    return exclu


def _files_under(source: str) -> list[str]:
    chemin = PROJECT_ROOT / source
    if chemin.is_file():
        return [source]
    if chemin.is_dir():
        return [str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
                for p in chemin.rglob("*") if p.is_file()]
    return []


# ----------------------------------------------------- existence et suivi git


@pytest.mark.parametrize("nom", sorted(DOCKERFILES))
def test_every_copy_source_exists_on_disk(nom):
    manquants = [s for s in _copy_sources(DOCKERFILES[nom])
                 if not (PROJECT_ROOT / s).exists()]
    assert not manquants, f"[{nom}] sources COPY absentes du disque : {manquants}"


@pytest.mark.parametrize("nom", sorted(DOCKERFILES))
def test_every_copy_source_is_tracked_by_git(nom):
    """Une source presente en local mais non versionnee serait absente du
    contexte de construction distant."""
    suivis = _tracked_files()
    non_suivis = []
    for source in _copy_sources(DOCKERFILES[nom]):
        fichiers = _files_under(source)
        assert fichiers, f"[{nom}] source vide ou introuvable : {source}"
        if not any(f in suivis for f in fichiers):
            non_suivis.append(source)
    assert not non_suivis, f"[{nom}] sources COPY non versionnees : {non_suivis}"


# ------------------------------------------------------- survie a dockerignore


@pytest.mark.parametrize("nom", sorted(DOCKERFILES))
def test_every_copy_source_survives_dockerignore(nom):
    """Controle central : c'est l'exclusion par `.dockerignore` de chemins
    pourtant versionnes qui a fait echouer la construction."""
    exclus = []
    for source in _copy_sources(DOCKERFILES[nom]):
        fichiers = [f for f in _files_under(source) if f in _tracked_files()]
        if not fichiers:
            continue
        if all(_is_excluded(f) for f in fichiers):
            exclus.append(source)
    assert not exclus, (
        f"[{nom}] sources COPY retirees du contexte par .dockerignore : {exclus}")


def test_v4_critical_paths_are_in_the_build_context():
    """Chemins nommement exiges pour l'image V4."""
    requis = [
        "src/__init__.py",
        "src/config/settings.py",
        "src/recsys_v4/models.py",
        "src/pricing_v4/models.py",
        "api_v4/main.py",
        "models/v4/FINAL_STATUS.json",
        "models/v4/FINAL_STATUS.sha256.json",
        "models/v4/recommendation/viewed_after_impression/model.joblib",
        "models/v4/recommendation/purchased_after/model.joblib",
        "models/v4/recommendation/added_to_cart_after/model.joblib",
        "models/v4/pricing/units_sold_window_7j/model.joblib",
        "models/v4/pricing/revenue_window_xof_7j/model.joblib",
        "models/v4/pricing/margin_window_xof_7j/model.joblib",
    ]
    suivis = _tracked_files()
    for chemin in requis:
        assert (PROJECT_ROOT / chemin).is_file(), f"absent du disque : {chemin}"
        assert chemin in suivis, f"non versionne : {chemin}"
        assert not _is_excluded(chemin), f"retire du contexte par .dockerignore : {chemin}"


def test_v2_copy_paths_still_survive_dockerignore():
    """La correction du contexte ne doit pas priver l'image V2 de ses fichiers."""
    for chemin in ("api/main.py", "models/FINAL_STATUS.json",
                   "models/api_bundle/metadata.json",
                   "models/api_bundle/pricing_model.joblib"):
        assert not _is_excluded(chemin), f"[V2] retire du contexte : {chemin}"


def test_heavy_reproducibility_artefacts_stay_out_of_the_context():
    """Les CSV de reproductibilite (environ 104 Mo) n'ont pas leur place dans
    une image de service."""
    for chemin in ("models/v4/recommendation/purchased_after/oos_predictions.csv",
                   "models/v4/pricing/units_sold_window_7j/segment_metrics.csv"):
        assert _is_excluded(chemin), f"devrait etre exclu du contexte : {chemin}"


def test_sensitive_paths_stay_out_of_the_context():
    for chemin in (".env", ".git/config", "data/raw/dim_produit.parquet"):
        assert _is_excluded(chemin), f"devrait etre exclu du contexte : {chemin}"


# ------------------------------- fichiers lus au runtime vs fichiers copies


def _copied_paths_v4() -> set[str]:
    """Ensemble des chemins reellement embarques dans l'image V4."""
    embarques = set()
    for source in _copy_sources(DOCKERFILES["V4"]):
        for fichier in _files_under(source):
            embarques.add(fichier)
    return embarques


def test_every_file_read_at_runtime_is_copied_into_the_image():
    """Regression : le service lisait `models/FINAL_STATUS.json` pour servir
    les modeles et scores de prevision, mais l'image ne le copiait pas. En
    local le fichier existe, donc rien ne se voyait ; en production les
    champs concernes valaient silencieusement null.

    Ce controle recense les chemins que le code lit au demarrage ou pendant
    une requete, et exige que chacun soit embarque.
    """
    from api_v4 import config as api_config
    from api_v4.services import metrics as metrics_service

    requis = [
        api_config.FINAL_STATUS_PATH,
        api_config.RECOMMENDATION_CATALOG_PATH,
        api_config.PRICING_CATALOG_PATH,
        api_config.CATEGORICAL_MAPPINGS_PATH,
        api_config.FORECAST_SNAPSHOT_PATH,
        metrics_service.STATUT_V2_PATH,
    ]

    embarques = _copied_paths_v4()
    manquants = []
    for chemin in requis:
        relatif = str(chemin.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if relatif not in embarques:
            manquants.append(relatif)
    assert not manquants, (
        "fichiers lus a l'execution mais absents de l'image V4 : " + str(manquants))


def test_the_v2_decision_file_is_embedded():
    """Controle nomme, car c'est precisement celui qui manquait."""
    assert "models/FINAL_STATUS.json" in _copied_paths_v4()
