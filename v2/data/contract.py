"""Chargement du contrat de données et comparaison de schémas.

Le contrat vit dans ``v2/config/expected_new_data_schema.yaml``. Ce module ne
contient aucune logique d'accès à la base : il travaille sur des structures
Python, ce qui le rend testable sans connexion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from src.config.settings import PROJECT_ROOT

CONTRACT_PATH = PROJECT_ROOT / "v2" / "config" / "expected_new_data_schema.yaml"


class ChangeKind(str, Enum):
    AJOUT = "ajout"
    SUPPRESSION = "suppression"
    RENOMMAGE_PROBABLE = "renommage_probable"
    TYPE = "changement_de_type"
    NULLABILITE = "changement_de_nullabilite"
    CLE = "changement_de_cle"
    GRAIN = "changement_de_grain"


@dataclass(frozen=True)
class SchemaChange:
    kind: ChangeKind
    table: str
    colonne: str | None
    avant: Any
    apres: Any
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "type_de_changement": self.kind.value, "table": self.table,
            "colonne": self.colonne, "avant": self.avant, "apres": self.apres,
            "detail": self.detail,
        }


@dataclass
class Contract:
    raw: dict

    @property
    def schema_actuel(self) -> dict:
        return self.raw["schema_actuel"]

    @property
    def champs_attendus(self) -> dict:
        return self.raw["champs_attendus"]

    @property
    def renommages_probables(self) -> list[dict]:
        return self.raw.get("renommages_probables", [])

    @property
    def seuils_couverture(self) -> dict:
        return self.raw["seuils_couverture"]

    @property
    def controles_integrite(self) -> dict:
        return self.raw["controles_integrite"]

    def champs_obligatoires(self) -> list[tuple[str, str]]:
        """(table, colonne) de tous les champs marqués obligatoires."""
        return [
            (table, champ["nom"])
            for table, champs in self.champs_attendus.items()
            for champ in champs
            if champ.get("obligatoire")
        ]

    def champ(self, table: str, nom: str) -> dict | None:
        for c in self.champs_attendus.get(table, []):
            if c["nom"] == nom:
                return c
        return None

    def comportement_si_absent(self, table: str, nom: str) -> str:
        c = self.champ(table, nom)
        return (c or {}).get("si_absent", "non documenté dans le contrat")


def load_contract(path: Path | None = None) -> Contract:
    p = path or CONTRACT_PATH
    return Contract(yaml.safe_load(p.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# Comparaison de schémas
# --------------------------------------------------------------------------- #
def _normalise_type(t: str) -> str:
    """Regroupe les alias de type sous une forme canonique.

    On ne cherche pas à être exhaustif : seulement à éviter de signaler
    `int4` contre `integer` comme un changement de type, ce qui noierait les
    vrais changements dans du bruit.
    """
    t = (t or "").strip().lower()
    alias = {
        "int2": "integer", "int4": "integer", "int8": "integer", "bigint": "integer",
        "smallint": "integer", "serial": "integer",
        "float4": "numeric", "float8": "numeric", "double precision": "numeric",
        "real": "numeric", "decimal": "numeric",
        "varchar": "text", "character varying": "text", "char": "text", "bpchar": "text",
        "bool": "boolean",
        "timestamp with time zone": "timestamptz",
        "timestamp without time zone": "timestamp",
    }
    return alias.get(t, t)


def compare_schemas(
    avant: dict, apres: dict, renommages_probables: list[dict] | None = None
) -> list[SchemaChange]:
    """Compare deux inventaires de schéma et classe chaque divergence.

    ``avant`` et ``apres`` ont la même forme que la section ``schema_actuel``
    du contrat : ``{table: {colonnes: {nom: {type, nullable}}, cle_primaire,
    grain}}``.

    Les renommages déclarés dans le contrat sont détectés en priorité : une
    colonne disparue et une colonne apparue qui correspondent à un couple connu
    sont fusionnées en un seul `RENOMMAGE_PROBABLE`, au lieu d'être signalées
    comme une suppression et un ajout sans lien — ce qui masquerait la rupture.
    """
    changes: list[SchemaChange] = []
    renommages = renommages_probables or []

    for table in sorted(set(avant) | set(apres)):
        a, b = avant.get(table), apres.get(table)

        if a is None:
            changes.append(SchemaChange(ChangeKind.AJOUT, table, None, None, "table",
                                        "table entièrement nouvelle"))
            continue
        if b is None:
            changes.append(SchemaChange(ChangeKind.SUPPRESSION, table, None, "table", None,
                                        "table disparue — rupture majeure"))
            continue

        cols_a = a.get("colonnes", {}) or {}
        cols_b = b.get("colonnes", {}) or {}
        disparues = set(cols_a) - set(cols_b)
        apparues = set(cols_b) - set(cols_a)

        # Renommages connus d'abord, pour ne pas les compter deux fois.
        apparies: set[str] = set()
        for r in renommages:
            if r.get("table") != table:
                continue
            anc, nouv = r.get("ancien"), r.get("nouveau")
            if anc in disparues and nouv in apparues:
                changes.append(SchemaChange(
                    ChangeKind.RENOMMAGE_PROBABLE, table, anc, anc, nouv,
                    r.get("risque", "renommage déclaré dans le contrat — à confirmer explicitement"),
                ))
                apparies |= {anc, nouv}

        for c in sorted(disparues - apparies):
            changes.append(SchemaChange(ChangeKind.SUPPRESSION, table, c, cols_a[c], None,
                                        "colonne disparue"))
        for c in sorted(apparues - apparies):
            changes.append(SchemaChange(ChangeKind.AJOUT, table, c, None, cols_b[c],
                                        "colonne nouvelle"))

        for c in sorted(set(cols_a) & set(cols_b)):
            ta, tb = _normalise_type(cols_a[c].get("type")), _normalise_type(cols_b[c].get("type"))
            if ta != tb:
                changes.append(SchemaChange(ChangeKind.TYPE, table, c,
                                            cols_a[c].get("type"), cols_b[c].get("type")))
            na, nb = bool(cols_a[c].get("nullable")), bool(cols_b[c].get("nullable"))
            if na != nb:
                detail = ("colonne devenue nullable — des valeurs manquantes peuvent apparaître"
                          if nb else "colonne devenue non nullable — contrainte renforcée")
                changes.append(SchemaChange(ChangeKind.NULLABILITE, table, c, na, nb, detail))

        pk_a, pk_b = a.get("cle_primaire"), b.get("cle_primaire")
        if pk_a != pk_b:
            changes.append(SchemaChange(ChangeKind.CLE, table, None, pk_a, pk_b,
                                        "clé primaire modifiée"))

        gr_a, gr_b = a.get("grain"), b.get("grain")
        if gr_a is not None and gr_b is not None and gr_a != gr_b:
            changes.append(SchemaChange(
                ChangeKind.GRAIN, table, None, gr_a, gr_b,
                "CHANGEMENT DE GRAIN — aucune métrique n'est comparable d'une version à l'autre "
                "tant que les baselines n'ont pas été recalculées sur le nouveau grain",
            ))

    return changes


def changements_bloquants(changes: list[SchemaChange]) -> list[SchemaChange]:
    """Changements qui invalident une comparaison directe avec les baselines V1."""
    return [
        c for c in changes
        if c.kind in (ChangeKind.GRAIN, ChangeKind.CLE, ChangeKind.SUPPRESSION,
                      ChangeKind.RENOMMAGE_PROBABLE)
    ]
