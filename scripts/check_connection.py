"""Vérification rapide de l'accès à la base — lecture seule, aucun secret affiché.

    python scripts/check_connection.py

Affiche : backend utilisé, tables lisibles, nombre de lignes, colonnes détectées.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import get_credentials, load_config  # noqa: E402
from src.data.connection import RestSource, get_data_source  # noqa: E402
from src.utils.logging_utils import setup_logging  # noqa: E402
from v2.data.checks import expurger  # noqa: E402


def main() -> int:
    setup_logging(level="INFO")
    creds = get_credentials()
    print("Identifiants détectés (sans secret) :", creds.safe_summary())

    cfg = load_config()
    expected = list(cfg.get("database.fact_tables", [])) + list(cfg.get("database.dim_tables", []))

    try:
        source = get_data_source()
    except RuntimeError as exc:
        print(f"\n[ÉCHEC] {exc}")
        return 1

    try:
        print(f"\nBackend actif : {source.backend}")
        try:
            if isinstance(source, RestSource):
                tables = source.probe_tables(expected)
                print(f"Tables attendues : {expected}")
            else:
                tables = source.list_tables()
            print(f"Tables lisibles  : {tables}\n")

            if not tables:
                print("[ÉCHEC] Aucune table lisible. Vérifiez la clé, le schéma et les RLS.")
                return 1

            for table in tables:
                try:
                    n = source.count_rows(table)
                    sample = source.sample(table, n=1)
                    cols = list(sample.columns)
                    print(f"  {table:<24} {n:>10,} lignes | {len(cols):>2} colonnes")
                    print(f"      -> {cols}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  {table:<24} ERREUR : {expurger(exc)}")
            print("\n[OK] Connexion fonctionnelle en lecture.")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"\n[ÉCHEC] Connexion ou inspection impossible : {expurger(exc)}")
            return 1
    finally:
        source.close()


if __name__ == "__main__":
    raise SystemExit(main())
