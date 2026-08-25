"""Extraction en lecture seule des tables V4 vers une copie locale versionnée.

Ce script ne modifie jamais Supabase : il lit `fact_experimentation_prix` et
`fact_exposition_reco` (les tables que la consigne désigne comme « V4 » ; elles
ne portent pas ce suffixe dans le schéma Postgres, mais leur volumétrie et leur
schéma diffèrent des livraisons précédentes déjà auditées) et les fige dans
`data/raw/v4/`, horodaté et empreint en SHA-256, pour que toute la suite du
pipeline travaille sur un instantané reproductible plutôt que sur la base
vivante.

Les tables historiques déjà validées (`dim_produit`, `dim_promotion`,
`fact_ventes`, `fact_stock`, `fact_evenements_web`, `dim_date`, `dim_client`)
ne sont pas re-tirées : leur cache local (`data/raw/*.parquet`, extrait lors de
l'audit V2) est vérifié par comparaison de volumétrie avec la base vivante, puis
référencé tel quel dans le manifeste.

`fact_ventes` est en outre exporté en CSV (`data/raw/v4/fact_ventes.csv`) car la
documentation pricing V4 le cite explicitement comme une entrée du contrôle de
cohérence remise/chiffre d'affaires.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.data.connection import get_data_source

V4_DIR = PROJECT_ROOT / "data" / "raw" / "v4"
LEGACY_DIR = PROJECT_ROOT / "data" / "raw"
MANIFEST_OUT = PROJECT_ROOT / "models" / "v4" / "manifests" / "raw_data_manifest.json"

FRESH_TABLES = ("fact_experimentation_prix", "fact_exposition_reco")
REUSED_TABLES = ("dim_client", "dim_date", "dim_produit", "dim_promotion",
                 "fact_evenements_web", "fact_stock", "fact_ventes")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def _extract_fresh(source, table: str) -> dict:
    """Extraction complète et paginée d'une table V4, sans cache."""
    live_count = int(source.query(f"SELECT COUNT(*) AS n FROM {table}").n.iloc[0])
    frame = source.fetch_table(table, page_size=1000)
    if len(frame) != live_count:
        raise AssertionError(
            f"Pagination incomplète pour {table} : {len(frame)} lignes extraites "
            f"contre {live_count} annoncées par COUNT(*)."
        )
    target = V4_DIR / f"{table}.parquet"
    frame.to_parquet(target, index=False)
    return {
        "table": table, "source": "fresh_extraction", "rows": len(frame),
        "columns": list(frame.columns), "sha256": _sha256(target),
        "path": str(target.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "live_row_count_at_extraction": live_count,
    }


def _reuse_legacy(source, table: str) -> dict:
    """Réutilise le cache V2 après vérification de volumétrie contre la base vivante."""
    cached_path = LEGACY_DIR / f"{table}.parquet"
    if not cached_path.is_file():
        raise FileNotFoundError(
            f"Table historique {table} absente du cache local ; extraction fraîche requise."
        )
    cached = pd.read_parquet(cached_path)
    live_count = int(source.query(f"SELECT COUNT(*) AS n FROM {table}").n.iloc[0])
    matches = len(cached) == live_count
    return {
        "table": table, "source": "reused_v2_validated_cache", "rows": len(cached),
        "columns": list(cached.columns), "sha256": _sha256(cached_path),
        "path": str(cached_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "live_row_count_at_extraction": live_count,
        "volume_matches_live": matches,
    }


def main() -> int:
    V4_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    source = get_data_source()

    entries = []
    for table in FRESH_TABLES:
        entries.append(_extract_fresh(source, table))
    for table in REUSED_TABLES:
        entry = _reuse_legacy(source, table)
        entries.append(entry)
        if not entry["volume_matches_live"]:
            raise AssertionError(
                f"Volumétrie divergente pour la table historique {table} : "
                f"cache={entry['rows']} vs base vivante={entry['live_row_count_at_extraction']}. "
                "Une table réputée validée a changé ; ré-extraction complète requise avant "
                "de poursuivre."
            )

    # Export CSV explicite de fact_ventes, cite comme entree de la documentation pricing.
    ventes = pd.read_parquet(LEGACY_DIR / "fact_ventes.parquet")
    csv_path = V4_DIR / "fact_ventes.csv"
    ventes.to_csv(csv_path, index=False, encoding="utf-8")
    entries.append({
        "table": "fact_ventes", "source": "csv_export_for_pricing_documentation",
        "rows": len(ventes), "columns": list(ventes.columns),
        "sha256": _sha256(csv_path),
        "path": str(csv_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    })

    manifest = {
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "note": (
            "Les tables 'V4' (fact_experimentation_prix, fact_exposition_reco) ne portent "
            "pas de suffixe _v4 dans le schema Postgres ; leur volumetrie et leur schema "
            "different des livraisons precedentes deja auditees (16797 puis 12996 lignes "
            "pour le pricing, 12996 puis 221080 pour la reco), ce qui identifie la livraison "
            "couramment presente en base comme la V4 visee par la consigne."
        ),
        "tables": entries,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8", newline="\n")
    print(json.dumps({e["table"]: {"rows": e["rows"], "source": e["source"]} for e in entries},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
