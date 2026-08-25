"""Accès aux données Supabase / PostgreSQL — **strictement en lecture seule**.

Deux backends interchangeables :

* ``PostgresSource`` (recommandé) : connexion SQL directe via SQLAlchemy/psycopg2.
  La session est forcée en ``default_transaction_read_only=on`` : toute tentative
  d'écriture est rejetée par le serveur lui-même.
* ``RestSource`` (repli) : API PostgREST de Supabase. Seules les lectures
  paginées sont exposées ; aucune méthode d'écriture n'est implémentée.

Aucun identifiant n'est écrit ici : tout provient de ``src.config.settings``.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Any, Iterator, Sequence

import pandas as pd

from src.config.settings import DbCredentials, get_credentials
from src.utils.logging_utils import get_logger

logger = get_logger(__name__)

# Mots-clés interdits : garde-fou applicatif en plus du read-only serveur.
_WRITE_PATTERN = re.compile(
    r"\b(insert|update|delete|truncate|drop|alter|create|grant|revoke|copy|vacuum)\b",
    re.IGNORECASE,
)
_IDENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ReadOnlyViolation(RuntimeError):
    """Levée quand une requête non lecture-seule est soumise."""


def assert_read_only(sql: str) -> None:
    """Rejette toute requête contenant un mot-clé d'écriture."""
    # On ignore les commentaires pour éviter les faux positifs.
    stripped = re.sub(r"--[^\n]*", " ", sql)
    stripped = re.sub(r"/\*.*?\*/", " ", stripped, flags=re.DOTALL)
    if _WRITE_PATTERN.search(stripped):
        raise ReadOnlyViolation(
            "Requête refusée : le projet interdit toute écriture sur la base de production."
        )


def quote_ident(name: str) -> str:
    """Valide puis échappe un identifiant SQL (protection injection)."""
    if not _IDENT_PATTERN.match(name):
        raise ValueError(f"Identifiant SQL invalide : {name!r}")
    return f'"{name}"'


class DataSource(ABC):
    """Interface commune aux deux backends."""

    schema: str
    backend: str

    @abstractmethod
    def list_tables(self) -> list[str]:
        """Noms des tables/vues lisibles dans le schéma."""

    @abstractmethod
    def describe_columns(self, table: str) -> pd.DataFrame:
        """Colonnes : nom, type, nullable, défaut, position."""

    @abstractmethod
    def count_rows(self, table: str) -> int:
        """Nombre exact de lignes."""

    @abstractmethod
    def fetch_table(
        self,
        table: str,
        columns: Sequence[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        page_size: int = 1000,
    ) -> pd.DataFrame:
        """Extraction paginée complète (ou tronquée à ``limit``)."""

    def sample(self, table: str, n: int = 5) -> pd.DataFrame:
        return self.fetch_table(table, limit=n, page_size=max(n, 1))

    def supports_sql(self) -> bool:
        return False

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        raise NotImplementedError("Ce backend n'accepte pas de SQL arbitraire.")

    def close(self) -> None:  # pragma: no cover - trivial
        pass

    def __enter__(self) -> "DataSource":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Backend PostgreSQL
# ---------------------------------------------------------------------------
class PostgresSource(DataSource):
    backend = "postgres"

    def __init__(self, database_url: str, schema: str = "public") -> None:
        from sqlalchemy import create_engine

        self.schema = schema
        url = database_url
        if url.startswith("postgres://"):  # normalisation SQLAlchemy
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

        self._engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={
                # Lecture seule imposée côté serveur, plus des garde-fous de
                # durée : une inspection ne doit jamais bloquer la production.
                "options": (
                    "-c default_transaction_read_only=on "
                    "-c statement_timeout=60000 "
                    "-c lock_timeout=5000 "
                    "-c idle_in_transaction_session_timeout=120000"
                ),
                "connect_timeout": 20,
                "application_name": "forecasting-audit-readonly",
            },
        )
        logger.info("Backend PostgreSQL initialisé (schéma=%s, read-only forcé)", schema)

    # -- primitives ---------------------------------------------------------
    def supports_sql(self) -> bool:
        return True

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        assert_read_only(sql)
        from sqlalchemy import text

        with self._engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            rows = result.fetchall()
            return pd.DataFrame(rows, columns=list(result.keys()))

    def close(self) -> None:
        self._engine.dispose()

    # -- métadonnées --------------------------------------------------------
    def list_tables(self) -> list[str]:
        df = self.query(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
            """,
            {"schema": self.schema},
        )
        return df["table_name"].tolist()

    def describe_columns(self, table: str) -> pd.DataFrame:
        return self.query(
            """
            SELECT column_name,
                   data_type,
                   udt_name,
                   is_nullable,
                   column_default,
                   character_maximum_length,
                   numeric_precision,
                   numeric_scale,
                   ordinal_position
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
            """,
            {"schema": self.schema, "table": table},
        )

    def all_columns(self) -> pd.DataFrame:
        """Toutes les colonnes du schéma en une requête."""
        return self.query(
            """
            SELECT table_name, column_name, data_type, udt_name,
                   is_nullable, column_default, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = :schema
            ORDER BY table_name, ordinal_position
            """,
            {"schema": self.schema},
        )

    def primary_keys(self) -> pd.DataFrame:
        return self.query(
            """
            SELECT tc.table_name, kcu.column_name, kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = :schema
            ORDER BY tc.table_name, kcu.ordinal_position
            """,
            {"schema": self.schema},
        )

    def foreign_keys(self) -> pd.DataFrame:
        return self.query(
            """
            SELECT tc.table_name        AS source_table,
                   kcu.column_name      AS source_column,
                   ccu.table_name       AS target_table,
                   ccu.column_name      AS target_column,
                   tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = :schema
            ORDER BY tc.table_name, kcu.column_name
            """,
            {"schema": self.schema},
        )

    def indexes(self) -> pd.DataFrame:
        return self.query(
            """
            SELECT tablename AS table_name, indexname AS index_name, indexdef
            FROM pg_indexes
            WHERE schemaname = :schema
            ORDER BY tablename, indexname
            """,
            {"schema": self.schema},
        )

    def count_rows(self, table: str) -> int:
        ident = f"{quote_ident(self.schema)}.{quote_ident(table)}"
        df = self.query(f"SELECT COUNT(*) AS n FROM {ident}")  # noqa: S608 - identifiant validé
        return int(df.iloc[0]["n"])

    # -- extraction ---------------------------------------------------------
    def fetch_table(
        self,
        table: str,
        columns: Sequence[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        page_size: int = 50_000,
    ) -> pd.DataFrame:
        ident = f"{quote_ident(self.schema)}.{quote_ident(table)}"
        cols = "*" if not columns else ", ".join(quote_ident(c) for c in columns)
        if order_by:
            order_columns = [order_by]
        else:
            # LIMIT/OFFSET sans ORDER BY n'est pas déterministe : PostgreSQL
            # peut renvoyer les pages dans des ordres différents et créer des
            # doublons/omissions dans l'extrait. La PK déclarée fournit l'ordre
            # stable, y compris pour les clés composites (stock produit-jour).
            pk = self.primary_keys()
            order_columns = pk.loc[pk["table_name"] == table, "column_name"].tolist()
            if not order_columns:
                raise RuntimeError(
                    f"Extraction paginée refusée pour {table!r} : aucune clé primaire "
                    "déclarée ne permet de garantir un ordre stable."
                )
        order = "ORDER BY " + ", ".join(quote_ident(c) for c in order_columns)
        frames: list[pd.DataFrame] = []
        offset = 0
        started = time.time()
        while True:
            take = page_size if limit is None else min(page_size, limit - offset)
            if take <= 0:
                break
            sql = f"SELECT {cols} FROM {ident} {order} LIMIT {int(take)} OFFSET {int(offset)}"  # noqa: S608
            chunk = self.query(sql)
            if chunk.empty:
                break
            frames.append(chunk)
            offset += len(chunk)
            if len(chunk) < take:
                break
        result = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=list(columns or []))
        )
        logger.info(
            "Extraction %s : %s lignes en %.1fs", table, f"{len(result):,}", time.time() - started
        )
        return result


# ---------------------------------------------------------------------------
# Backend REST (PostgREST / Supabase)
# ---------------------------------------------------------------------------
class RestSource(DataSource):
    """Accès via l'API PostgREST de Supabase.

    ``information_schema`` n'est pas interrogeable, mais PostgREST publie un
    **schéma OpenAPI** à la racine de l'API : il porte les types PostgreSQL
    réels ainsi que les clés primaires et étrangères déclarées. Les métadonnées
    sont donc *lues*, et non devinées ; l'inférence depuis un échantillon ne
    sert que de repli si l'OpenAPI est indisponible.

    Limite qui subsiste : les commentaires de colonnes ne sont pas exposés.
    """

    backend = "rest"

    def __init__(self, url: str, key: str, schema: str = "public") -> None:
        from supabase import create_client

        self.schema = schema
        self._url = url
        self._key = key
        self._client = create_client(url, key)
        self._known_tables: list[str] | None = None
        self._openapi: dict[str, Any] | None = None
        logger.info("Backend REST Supabase initialisé (schéma=%s)", schema)

    def _table(self, table: str):
        client = self._client
        if self.schema != "public":
            client = client.schema(self.schema)
        return client.table(table)

    # -- métadonnées via OpenAPI -------------------------------------------
    def openapi(self) -> dict[str, Any]:
        """Schéma OpenAPI publié par PostgREST à la racine de l'API.

        Il porte les **types PostgreSQL réels** ainsi que les clés primaires et
        étrangères, que l'API de données seule n'expose pas. C'est la différence
        entre un schéma inféré depuis un échantillon et un schéma déclaré.
        """
        if self._openapi is not None:
            return self._openapi
        import httpx

        response = httpx.get(
            self._url.rstrip("/") + "/rest/v1/",
            headers={"apikey": self._key, "Authorization": f"Bearer {self._key}"},
            timeout=60,
        )
        response.raise_for_status()
        self._openapi = response.json()
        return self._openapi

    def _definitions(self) -> dict[str, Any]:
        spec = self.openapi()
        return spec.get("definitions") or spec.get("components", {}).get("schemas", {})

    def declared_columns(self, table: str) -> pd.DataFrame | None:
        """Colonnes et types déclarés ; ``None`` si l'OpenAPI est indisponible."""
        try:
            definition = self._definitions().get(table)
        except Exception as exc:  # noqa: BLE001 - l'OpenAPI reste optionnel
            logger.warning("OpenAPI illisible : %s", exc)
            return None
        if not definition:
            return None
        rows = []
        for position, (col, meta) in enumerate(definition.get("properties", {}).items(), 1):
            rows.append(
                {
                    "column_name": col,
                    "data_type": meta.get("format", "inconnu"),
                    "udt_name": meta.get("type", ""),
                    "is_nullable": "NO" if col in definition.get("required", []) else "YES",
                    "column_default": meta.get("default"),
                    "ordinal_position": position,
                    "inferred": False,
                }
            )
        return pd.DataFrame(rows)

    def declared_keys(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Clés primaires et étrangères déclarées, extraites de l'OpenAPI."""
        pk_rows, fk_rows = [], []
        try:
            definitions = self._definitions()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAPI illisible : %s", exc)
            return pd.DataFrame(), pd.DataFrame()
        for table, definition in definitions.items():
            for col, meta in definition.get("properties", {}).items():
                description = meta.get("description", "") or ""
                if "Primary Key" in description:
                    pk_rows.append(
                        {"table_name": table, "column_name": col, "ordinal_position": 1}
                    )
                if "Foreign Key" in description:
                    match = re.search(r"`([^`]+)`", description)
                    if match and "." in match.group(1):
                        target_table, target_column = match.group(1).rsplit(".", 1)
                        fk_rows.append(
                            {
                                "source_table": table,
                                "source_column": col,
                                "target_table": target_table,
                                "target_column": target_column,
                                "constraint_name": "déclarée (OpenAPI)",
                            }
                        )
        return pd.DataFrame(pk_rows), pd.DataFrame(fk_rows)

    def probe_tables(self, candidates: Sequence[str]) -> list[str]:
        """Teste la lisibilité de chaque table candidate (REST n'énumère pas)."""
        available: list[str] = []
        for name in candidates:
            try:
                self._table(name).select("*").limit(1).execute()
                available.append(name)
            except Exception as exc:  # noqa: BLE001 - on veut juste savoir si c'est lisible
                logger.warning("Table %s inaccessible via REST : %s", name, exc)
        self._known_tables = available
        return available

    def list_tables(self) -> list[str]:
        if self._known_tables is None:
            raise RuntimeError(
                "L'API REST ne permet pas d'énumérer les tables. "
                "Appelez probe_tables(candidates) avec la liste attendue."
            )
        return list(self._known_tables)

    def describe_columns(self, table: str) -> pd.DataFrame:
        # Types déclarés en priorité ; inférence depuis un échantillon en repli.
        declared = self.declared_columns(table)
        if declared is not None and not declared.empty:
            return declared

        from src.data.coercion import coerce_datetime_columns

        logger.warning(
            "Types de %s inférés depuis un échantillon (OpenAPI indisponible).", table
        )
        sample = coerce_datetime_columns(self.fetch_table(table, limit=200, page_size=200))
        rows = []
        for position, col in enumerate(sample.columns, start=1):
            series = sample[col]
            non_null = series.dropna()
            rows.append(
                {
                    "column_name": col,
                    "data_type": str(series.dtype),
                    "udt_name": type(non_null.iloc[0]).__name__ if len(non_null) else "unknown",
                    "is_nullable": "YES" if series.isna().any() else "UNKNOWN",
                    "column_default": None,
                    "ordinal_position": position,
                    "inferred": True,
                }
            )
        return pd.DataFrame(rows)

    def count_rows(self, table: str) -> int:
        response = self._table(table).select("*", count="exact").limit(1).execute()
        return int(response.count or 0)

    def fetch_table(
        self,
        table: str,
        columns: Sequence[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        page_size: int = 1000,
    ) -> pd.DataFrame:
        """Pagination via l'en-tête Range de PostgREST (plafond usuel : 1000)."""
        select_expr = ",".join(columns) if columns else "*"
        frames: list[pd.DataFrame] = []
        offset = 0
        started = time.time()
        while True:
            take = page_size if limit is None else min(page_size, limit - offset)
            if take <= 0:
                break
            query = self._table(table).select(select_expr)
            if order_by:
                query = query.order(order_by)
            response = query.range(offset, offset + take - 1).execute()
            data = response.data or []
            if not data:
                break
            frames.append(pd.DataFrame(data))
            offset += len(data)
            if len(data) < take:
                break
        result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        logger.info(
            "Extraction REST %s : %s lignes en %.1fs",
            table,
            f"{len(result):,}",
            time.time() - started,
        )
        return result

    def iter_pages(
        self, table: str, page_size: int = 1000, order_by: str | None = None
    ) -> Iterator[pd.DataFrame]:
        offset = 0
        while True:
            query = self._table(table).select("*")
            if order_by:
                query = query.order(order_by)
            response = query.range(offset, offset + page_size - 1).execute()
            data = response.data or []
            if not data:
                return
            yield pd.DataFrame(data)
            offset += len(data)
            if len(data) < page_size:
                return


# ---------------------------------------------------------------------------
def get_data_source(credentials: DbCredentials | None = None) -> DataSource:
    """Instancie le backend adapté aux identifiants disponibles."""
    creds = credentials or get_credentials()
    backend = creds.resolved_backend()
    logger.info("Connexion : %s", creds.safe_summary())
    if backend == "postgres":
        assert creds.database_url  # garanti par resolved_backend
        from src.config.settings import resolve_reachable_url

        url, mode = resolve_reachable_url(creds.database_url)
        logger.info("Connexion PostgreSQL en mode : %s", mode)
        return PostgresSource(url, schema=creds.schema)
    assert creds.supabase_url and creds.supabase_key
    return RestSource(creds.supabase_url, creds.supabase_key, schema=creds.schema)
