"""Contrôles SQL agrégés, strictement en lecture seule, sans identifiants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.connection import get_data_source
from v2.data.checks import expurger


def main() -> int:
    try:
        with get_data_source() as source:
            counts = source.query(
                """
                SELECT count(*) AS rows,
                       count(DISTINCT event_id) AS unique_event_ids,
                       count(*) - count(DISTINCT event_id) AS duplicate_rows,
                       count(DISTINCT session_id) AS sessions
                FROM fact_evenements_web
                """
            )
            constraints = source.query(
                """
                SELECT tc.table_name, tc.constraint_type, kcu.column_name,
                       kcu.ordinal_position
                FROM information_schema.table_constraints AS tc
                LEFT JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name IN (
                      'fact_evenements_web', 'fact_ventes', 'fact_stock'
                  )
                  AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE')
                ORDER BY tc.table_name, tc.constraint_type, kcu.ordinal_position
                """
            )
        print(json.dumps({
            "counts": counts.to_dict(orient="records"),
            "constraints": constraints.to_dict(orient="records"),
        }, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(expurger(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
