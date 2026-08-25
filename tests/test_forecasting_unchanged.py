"""Garde-fou : le forecasting V2 valide ne doit jamais etre modifie par les
travaux V4 (pricing/recommandation). Ce test ne relit ni ne reentraine
aucun modele de forecasting ; il verifie seulement que les fichiers deja
versionnes n'ont pas bouge.

Trois niveaux de verification independants :
1. Les valeurs de decision et de metrique macro figees dans
   `models/FINAL_STATUS.json` (modeles retenus, WAPE30, biais) restent
   exactement celles validees.
2. Les empreintes SHA-256 des artefacts forecasting correspondent aux
   manifestes deja commit (`models/forecasting/manifest.sha256.json`,
   `models/advanced/forecasting/manifest.sha256.json`), qui datent d'avant
   le debut des travaux V4.
3. Aucun commit poste sur la branche V4 (depuis le commit de depart
   `40bdfae`, premier commit portant ces fichiers) ne touche un chemin
   forecasting.
"""
from __future__ import annotations

import hashlib
import json
import subprocess

from src.config.settings import PROJECT_ROOT

FINAL_STATUS_PATH = PROJECT_ROOT / "models" / "FINAL_STATUS.json"

FORECASTING_DIRS = (
    PROJECT_ROOT / "models" / "forecasting",
    PROJECT_ROOT / "models" / "advanced" / "forecasting",
)

#: Artefacts de forecasting proprement dits : strictement immuables. Aucun
#: commit ne doit les toucher, pour aucune raison.
FORECASTING_ARTIFACT_PATHS = (
    "models/forecasting",
    "models/advanced/forecasting",
)

#: `models/FINAL_STATUS.json` est un fichier de STATUT, pas un artefact de
#: modele : il porte a la fois la decision forecasting et des metadonnees de
#: provenance (dates, branche, chemins de rapports). Ces metadonnees peuvent
#: legitimement etre corrigees sans que le forecasting change.
#:
#: Il n'est donc pas soumis a l'interdiction de commit, mais a une garantie
#: plus forte et plus ciblee : les valeurs de decision forecasting qu'il
#: contient sont verifiees une par une
#: (`test_final_status_declares_the_expected_forecasting_decision`), et son
#: empreinte est epinglee pour rendre toute modification visible et
#: deliberee (`test_final_status_file_hash_is_unchanged`).
FINAL_STATUS_PATHS = (
    "models/FINAL_STATUS.json",
    "models/FINAL_STATUS.sha256.json",
)

# Empreinte figee de models/FINAL_STATUS.json au moment ou ce garde-fou a ete
# ecrit (branche v4/pricing-recommendation-training, apres finalisation du
# produit V4). Toute divergence signale une modification du fichier de
# decision forecasting/pricing/recommandation V2, ce qui n'est jamais
# attendu pendant les travaux V4.
# Empreinte mise a jour le 2026-08-22 apres une modification STRICTEMENT
# documentaire de `models/FINAL_STATUS.json` : le champ `provenance.branch`
# portait un nom de branche a reformuler. Aucune valeur de decision
# forecasting n'a change — les assertions de
# `test_final_status_declares_the_expected_forecasting_decision` le
# verifient explicitement et restent la garantie de fond.
# Empreinte precedente : a33747a4d483528f9c0d900e39f21e17f09f463656c5fe21acfc1099525eea1b
EXPECTED_FINAL_STATUS_SHA256 = "b5ed1749f2a97a295e246ca44db839aaceb6e964944c264104f1f745d8e6d3b0"

# Commit a partir duquel les fichiers forecasting actuels existent sous cette
# forme (premier commit de l'historique squash portant ces artefacts).
FORECASTING_BASELINE_COMMIT = "40bdfae"


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_final_status_declares_the_expected_forecasting_decision():
    status = json.loads(FINAL_STATUS_PATH.read_text(encoding="utf-8"))["status"]
    assert status["forecasting_status"] == "validated"
    assert status["forecasting_daily_model"] == "CrostonOptimized"
    assert status["forecasting_30d_model"] == "LightGBM_direct_per_horizon"
    assert status["forecasting_wape30_macro"] == 0.25831
    assert status["forecasting_bias"] == -0.02589


def test_final_status_file_hash_is_unchanged():
    actual = _sha256(FINAL_STATUS_PATH)
    assert actual == EXPECTED_FINAL_STATUS_SHA256, (
        "models/FINAL_STATUS.json a change depuis la finalisation du produit V4 : "
        f"empreinte actuelle {actual}, attendue {EXPECTED_FINAL_STATUS_SHA256}"
    )


def test_final_status_hash_matches_its_own_manifest():
    manifest_path = PROJECT_ROOT / "models" / "FINAL_STATUS.sha256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert _sha256(FINAL_STATUS_PATH) == manifest["FINAL_STATUS.json"]


def test_forecasting_artifacts_match_their_committed_manifests():
    mismatches = []
    for directory in FORECASTING_DIRS:
        manifest_path = directory / "manifest.sha256.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative_name, expected_hash in manifest.items():
            actual_hash = _sha256(directory / relative_name)
            if actual_hash != expected_hash:
                mismatches.append(f"{directory / relative_name}: attendu {expected_hash}, obtenu {actual_hash}")
    assert not mismatches, "artefacts forecasting modifies :\n" + "\n".join(mismatches)


def test_no_commit_since_baseline_touches_forecasting_artifacts():
    """Aucun commit ne doit toucher les artefacts de forecasting eux-memes."""
    result = subprocess.run(
        ["git", "diff", "--name-only", FORECASTING_BASELINE_COMMIT, "HEAD", "--",
         *FORECASTING_ARTIFACT_PATHS],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    )
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    assert not changed, (
        "des commits posterieurs au demarrage des travaux V4 modifient des "
        f"artefacts forecasting : {changed}"
    )


def test_forecasting_artifacts_have_no_uncommitted_changes():
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *FORECASTING_ARTIFACT_PATHS],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "", (
        "modifications non commit detectees sur des artefacts forecasting : " + result.stdout
    )


def test_final_status_forecasting_values_never_changed_since_baseline():
    """Garantie de fond sur le fichier de statut : quelles que soient les
    corrections de metadonnees, les valeurs de decision forecasting qu'il
    porte doivent etre identiques a celles du commit de reference."""
    ancien = subprocess.run(
        ["git", "show", f"{FORECASTING_BASELINE_COMMIT}:models/FINAL_STATUS.json"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout
    origine = json.loads(ancien)["status"]
    actuel = json.loads(FINAL_STATUS_PATH.read_text(encoding="utf-8"))["status"]
    for clef in ("forecasting_status", "forecasting_daily_model",
                 "forecasting_30d_model", "forecasting_wape30_macro",
                 "forecasting_bias"):
        assert actuel[clef] == origine[clef], (
            f"valeur forecasting modifiee depuis {FORECASTING_BASELINE_COMMIT} : "
            f"{clef} vaut {actuel[clef]}, valait {origine[clef]}")
