"""Regeneration des manifestes SHA-256, portables entre plateformes.

Convention (identique a celle de `scripts/validate_manifests.py`)
----------------------------------------------------------------
1. L'empreinte est un SHA-256 des **octets exacts du fichier dans l'arbre de
   travail**, sans transformation.
2. `.gitattributes` impose `eol=lf` a tout type textuel couvert par un manifeste
   et `binary` aux `.parquet` / `.joblib`. Les octets sont donc identiques sur
   Windows, Linux et macOS : une empreinte calculee ici reste verifiable apres
   n'importe quel clone.
3. Un manifeste ne couvre que des fichiers **versionnes** (`git ls-files`). Un
   artefact regenerable mais ignore par Git (parquet de predictions, CSV
   volumineux) ne peut pas etre verifie apres un clone ; il est donc consigne a
   part dans `<prefixe>local.json`, avec la commande qui le reproduit.
4. Les cles sont relatives au repertoire du manifeste, ou a la racine du depot
   lorsqu'elles commencent par `data/`. Aucun chemin absolu, aucune dependance
   au nom d'utilisateur ni au repertoire local.

Deux modes
----------
* ``rebuild`` — le jeu de fichiers a change ; le manifeste est reconstruit.
* ``update``  — le jeu de fichiers est inchange, seules les empreintes bougent ;
  la structure des cles est preservee a l'identique.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from src.config.settings import PROJECT_ROOT

MANIFEST_SUFFIX = "manifest.sha256.json"
LOCAL_SUFFIX = "local.json"
REPRODUCE = {
    "models/advanced/recommendation_ranking": "python -m src.experiments.complement_end_to_end",
    "models/advanced/complement_honest": "python -m src.experiments.complement_honest_baseline",
    "models/advanced/pricing_corrected": "python -m src.experiments.pricing_corrected",
    "models/pricing": "python -m src.pipelines.final_pricing",
    "models/campaign_level_pricing": "python -m src.experiments.pricing_campaign_level",
    "models/advanced/pricing": "python -m src.experiments.advanced_pricing",
    "models/advanced/forecasting": "python -m src.experiments.advanced_forecasting",
}
REBUILD = (
    "models/advanced/recommendation_ranking",
    "models/advanced/complement_honest",
    "models/advanced/pricing_corrected",
    "models/pricing",
)
UPDATE = (
    "models/advanced/pricing",
    "models/campaign_level_pricing",
    # Divergence anterieure a la branche : le commit 9e2eb58 a modifie
    # metadata.json sans regenerer le manifeste. Seul l'enregistrement de
    # checksum est corrige ; l'artefact et ses metriques sont inchanges.
    "models/advanced/forecasting",
    # Manifestes herites d'origin/main : la renormalisation LF du 2026-08-18 a
    # change les octets des fichiers textuels, donc leurs empreintes.
    "models/advanced/recommendation",
    "models/forecasting",
    "models/recommendation",
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_files() -> set[str]:
    """Chemins versionnes, relatifs a la racine, separateur `/`."""
    output = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True).stdout
    return {line for line in output.split("\n") if line}


def _relative(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def _files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir()
                  if path.is_file() and MANIFEST_SUFFIX not in path.name
                  and not path.name.endswith(LOCAL_SUFFIX))


def _manifests(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir()
                  if path.is_file() and MANIFEST_SUFFIX in path.name)


def _write_local(directory: Path, untracked: dict[str, str]) -> str | None:
    """Consigne les artefacts locaux non versionnes, sans les manifester.

    La fusion est non destructive : un releve deja etabli lors d'un passage
    precedent est conserve. En mode `update`, une cle retiree du manifeste ne
    peut plus etre redecouverte, et l'effacer ferait perdre la tracabilite.
    """
    target = directory / ("artifacts." + LOCAL_SUFFIX)
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8")).get("sha256_local", {})
        merged = dict(previous)
        merged.update(untracked)
        untracked = merged
    if not untracked:
        return None
    key = _relative(directory)
    payload = {
        "convention": "artefacts regenerables, ignores par Git, non verifiables apres un clone",
        "reproduce": REPRODUCE.get(key, "voir reports/45_final_corrected_decision.md"),
        "sha256_local": untracked,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return target.name


def rebuild(directory: Path, tracked: set[str]) -> dict:
    versioned, local = {}, {}
    for path in _files(directory):
        (versioned if _relative(path) in tracked else local)[path.name] = _digest(path)
    written = []
    for path in _manifests(directory) or [directory / MANIFEST_SUFFIX]:
        prefix = path.name.replace(MANIFEST_SUFFIX, "").rstrip("_.")
        scoped = {name: value for name, value in versioned.items()
                  if not prefix or name.startswith(prefix)}
        path.write_text(json.dumps(scoped, indent=2) + "\n", encoding="utf-8", newline="\n")
        written.append(path.name)
    local_file = _write_local(directory, local)
    invalidated = directory / "invalidated"
    if invalidated.is_dir():
        archive = {path.name: _digest(path) for path in _files(invalidated)
                   if _relative(path) in tracked}
        archive_local = {path.name: _digest(path) for path in _files(invalidated)
                         if _relative(path) not in tracked}
        (invalidated / MANIFEST_SUFFIX).write_text(
            json.dumps(archive, indent=2) + "\n", encoding="utf-8", newline="\n")
        _write_local(invalidated, archive_local)
        written.append("invalidated/" + MANIFEST_SUFFIX)
    return {"directory": _relative(directory), "mode": "rebuild",
            "versionnes": len(versioned), "locaux_non_versionnes": len(local),
            "manifests": written, "local_file": local_file}


def update(directory: Path, tracked: set[str]) -> dict:
    written, dropped, local = [], [], {}
    for path in _manifests(directory):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        refreshed = {}
        for key in manifest:
            target = PROJECT_ROOT / key if key.startswith("data/") else directory / key
            if not target.exists():
                dropped.append(key + " (absent)")
                continue
            if _relative(target) not in tracked:
                dropped.append(key + " (non versionne)")
                local[key] = _digest(target)
                continue
            refreshed[key] = _digest(target)
        path.write_text(json.dumps(refreshed, indent=2) + "\n", encoding="utf-8", newline="\n")
        written.append(path.name)
    local_file = _write_local(directory, local)
    return {"directory": _relative(directory), "mode": "update",
            "manifests": written, "entrees_retirees": dropped, "local_file": local_file}


def main() -> int:
    tracked = tracked_files()
    report = []
    for target in REBUILD:
        directory = PROJECT_ROOT / target
        if directory.is_dir():
            report.append(rebuild(directory, tracked))
    for target in UPDATE:
        directory = PROJECT_ROOT / target
        if directory.is_dir():
            report.append(update(directory, tracked))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
