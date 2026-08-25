"""Validation de tous les manifestes SHA-256 du depot.

Convention de calcul des SHA-256
--------------------------------
1. **Octets bruts.** L'empreinte est un SHA-256 du contenu du fichier tel qu'il
   existe dans l'arbre de travail, lu en binaire, sans aucune transformation :
   pas de normalisation d'encodage, pas de reserialisation JSON, pas de
   reecriture de fins de ligne au moment du calcul.

2. **Portabilite garantie par `.gitattributes`.** C'est le checkout, et non le
   calcul, qui garantit des octets identiques partout :

   * tout type textuel couvert par un manifeste (`.json`, `.md`, `.csv`,
     `.jsonl`, `.py`, `.yaml`...) est declare `text eol=lf` ; le fichier est
     donc en LF dans l'arbre de travail quelle que soit la plateforme ;
   * `.parquet` et `.joblib` sont declares `binary` : jamais convertis.

   Sans cette declaration, un checkout Windows produirait des CRLF et donc des
   empreintes differentes de celles calculees sous Linux, pour un contenu
   pourtant identique. C'est le defaut qui affectait les manifestes avant la
   normalisation du 2026-08-18.

3. **Perimetre : fichiers versionnes uniquement.** Un manifeste ne reference que
   des fichiers suivis par Git. Un artefact regenerable mais ignore (parquet de
   predictions, CSV volumineux) n'existe pas apres un clone : le manifester
   rendrait la validation impossible pour un tiers. Ces artefacts sont consignes
   separement dans `artifacts.local.json`, avec la commande qui les reproduit ;
   ce fichier est informatif et n'est jamais une condition de succes.

4. **Cles relatives.** Une cle est relative au repertoire du manifeste, ou a la
   racine du depot si elle commence par `data/`. Aucun chemin absolu, aucune
   dependance au nom d'utilisateur ni au repertoire local.

Sortie non nulle si une empreinte diverge, si une cible est absente, si une cle
est un chemin absolu, ou si un manifeste reference un fichier non versionne.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys

from src.config.settings import PROJECT_ROOT

ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~)")


def _digest(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked() -> set[str]:
    output = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True).stdout
    return {line for line in output.split("\n") if line}


def main() -> int:
    tracked = _tracked()
    # Les repertoires caches (.git, .venv, .pytest_cache, .test-tmp-api...) sont
    # ignores : ils contiennent des copies temporaires d'artefacts, non versionnees.
    manifests = [p for p in sorted(set(PROJECT_ROOT.rglob("*sha256.json")))
                 if not any(part.startswith(".") for part in p.parts)]
    total_entries = 0
    crlf_in_text = []
    ok_manifests, problems = [], []

    for manifest in manifests:
        relative = str(manifest.relative_to(PROJECT_ROOT)).replace("\\", "/")
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            problems.append((relative, "json_illisible", str(error)))
            continue
        if not isinstance(entries, dict):
            problems.append((relative, "format_inattendu", type(entries).__name__))
            continue
        local = []
        for key, expected in entries.items():
            if ABSOLUTE.match(key):
                local.append((key, "chemin_absolu", ""))
                continue
            if not isinstance(expected, str) or len(expected) != 64:
                local.append((key, "empreinte_malformee", str(expected)[:40]))
                continue
            target = PROJECT_ROOT / key if key.startswith("data/") else manifest.parent / key
            if not target.exists():
                local.append((key, "cible_absente", ""))
                continue
            target_relative = str(target.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if target_relative not in tracked:
                local.append((key, "cible_non_versionnee", "non verifiable apres un clone"))
                continue
            actual = _digest(target)
            if actual != expected:
                local.append((key, "empreinte_divergente", actual[:16] + " != " + expected[:16]))
                continue
            # Controle de portabilite : un fichier textuel ne doit pas contenir de CRLF.
            if target.suffix.lower() in {".json", ".md", ".csv", ".jsonl", ".py",
                                         ".yaml", ".yml", ".txt"}:
                if b"\r\n" in target.read_bytes():
                    crlf_in_text.append(target_relative)
            total_entries += 1
        if local:
            problems.append((relative, "entrees_invalides", local))
        else:
            ok_manifests.append((relative, len(entries)))

    print("Convention : SHA-256 des octets bruts ; portabilite assuree par")
    print("`.gitattributes` (eol=lf sur le texte, binary sur parquet/joblib) ;")
    print("perimetre limite aux fichiers versionnes.")
    print()
    print("manifestes analyses :", len(manifests))
    print("entrees verifiees   :", total_entries)
    print()
    for relative, count in ok_manifests:
        print("  OK   " + str(count).rjust(3) + " entrees  " + relative)
    for item in problems:
        print("  KO   " + str(item))
    if crlf_in_text:
        print()
        print("  CRLF detecte dans des fichiers textuels manifestes (non portable) :")
        for name in crlf_in_text:
            print("     ", name)

    local_files = [p for p in sorted(PROJECT_ROOT.rglob("artifacts.local.json"))
                   if not any(part.startswith(".") for part in p.parts)]
    if local_files:
        print()
        print("artefacts locaux non versionnes (informatif, hors validation) :")
        for path in local_files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            print("  " + str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                  + " -> " + str(len(payload["sha256_local"])) + " artefact(s)")

    failed = bool(problems or crlf_in_text)
    print()
    print("VERDICT :", "tous les manifestes sont valides et portables" if not failed
          else "echec de validation")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
