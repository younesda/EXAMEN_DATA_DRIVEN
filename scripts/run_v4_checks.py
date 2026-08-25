"""Point d'entree unique de verification du produit V4.

Enchaine, dans l'ordre, sans reseau et sans reentrainement :
1. le garde-fou d'immutabilite du forecasting ;
2. les tests unitaires pricing V4 et recommandation V4 ;
3. les tests de deploiement, d'API et d'integration du produit V4 ;
4. la validation de tous les manifestes SHA-256 du depot.

Sort avec un code non nul des la premiere etape en echec.

Deux modes
----------
Par defaut, toutes les etapes sont executees.

Avec `--sans-donnees`, les etapes qui lisent `data/raw/` sont ignorees. Ce
mode existe pour l'integration continue : les donnees brutes ne sont
volontairement pas versionnees, un executeur distant ne peut donc pas
reconstruire les jeux d'entrainement. Les etapes concernees sont annoncees
comme ignorees, jamais presentees comme reussies.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from src.config.settings import PROJECT_ROOT

#: (libelle, commande, requiert les donnees brutes non versionnees)
STEPS: list[tuple[str, list[str], bool]] = [
    ("Garde-fou forecasting (aucun fichier modifie)",
     [sys.executable, "-m", "pytest", "tests/test_forecasting_unchanged.py", "-v"], False),
    ("Tests unitaires pricing V4",
     [sys.executable, "-m", "pytest", "tests/test_v4_pricing.py", "-q"], True),
    ("Tests unitaires recommandation V4",
     [sys.executable, "-m", "pytest", "tests/test_v4_recommendation.py", "-q"], True),
    ("Configuration de deploiement V4",
     [sys.executable, "-m", "pytest", "api_v4/tests/test_deployment_config.py", "-q"], False),
    ("Contexte de construction (chemins COPY)",
     [sys.executable, "-m", "pytest", "api_v4/tests/test_docker_context.py", "-q"], False),
    ("Tests API produit V4",
     [sys.executable, "-m", "pytest", "api_v4/tests/test_api.py", "-q"], False),
    ("Simulation pricing (volume, CA, marge)",
     [sys.executable, "-m", "pytest", "api_v4/tests/test_pricing_simulation.py", "-q"], False),
    ("Scores et route /metrics",
     [sys.executable, "-m", "pytest", "api_v4/tests/test_metrics_scores.py", "-q"], False),
    ("Tests d'integration produit V4",
     [sys.executable, "-m", "pytest", "api_v4/tests/test_integration.py", "-q"], False),
    ("Validation des manifestes SHA-256",
     [sys.executable, "-m", "scripts.validate_manifests"], False),
]


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--sans-donnees", action="store_true",
        help="ignorer les etapes qui lisent data/raw (mode integration continue)")
    options = analyseur.parse_args(argv)

    debut = time.perf_counter()
    ignorees: list[str] = []

    for libelle, commande, requiert_donnees in STEPS:
        if options.sans_donnees and requiert_donnees:
            print(f"\n=== {libelle} ===")
            print(f"--- {libelle} : IGNOREE "
                  "(necessite data/raw, non versionne) ---")
            ignorees.append(libelle)
            continue

        print(f"\n=== {libelle} ===")
        depart = time.perf_counter()
        resultat = subprocess.run(commande, cwd=PROJECT_ROOT)
        duree = time.perf_counter() - depart
        etat = "OK" if resultat.returncode == 0 else "ECHEC"
        print(f"--- {libelle} : {etat} ({duree:.1f}s) ---")
        if resultat.returncode != 0:
            print(f"\nArret : etape en echec -> {libelle}")
            return resultat.returncode

    total = time.perf_counter() - debut
    if ignorees:
        print(f"\n{len(ignorees)} etape(s) ignoree(s), faute de donnees brutes "
              "versionnees. A executer en local :")
        for libelle in ignorees:
            print(f"  - {libelle}")
        print("  commande : python -m scripts.run_v4_checks")
    print(f"\nVerifications executees passees ({total:.1f}s au total).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
