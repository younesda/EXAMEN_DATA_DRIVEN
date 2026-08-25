"""Chargement de la configuration (YAML) et des secrets (variables d'environnement).

Règle du projet : aucun identifiant en dur dans le code ni dans le YAML.
Les secrets viennent uniquement de l'environnement (fichier `.env` local ou
variables réellement exportées).
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def _load_dotenv_once() -> None:
    """Charge `.env` sans écraser les variables déjà présentes dans l'environnement."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)


@dataclass(frozen=True)
class DbCredentials:
    """Identifiants d'accès, lus exclusivement depuis l'environnement."""

    database_url: str | None
    supabase_url: str | None = None
    supabase_key: str | None = None
    database_url_source: str | None = None
    supabase_key_source: str | None = None
    schema: str = "public"
    backend: str = "auto"

    @property
    def has_postgres(self) -> bool:
        return bool(self.database_url)

    @property
    def has_rest(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    def resolved_backend(self) -> str:
        """Backend effectivement utilisable ('postgres' ou 'rest')."""
        if self.backend == "postgres":
            if not self.has_postgres:
                raise RuntimeError(
                    "DB_BACKEND=postgres mais DATABASE_URL (ou PGHOST/PGUSER/...) est absent."
                )
            return "postgres"
        if self.backend == "rest":
            if not self.has_rest:
                raise RuntimeError(
                    "DB_BACKEND=rest mais SUPABASE_URL / SUPABASE_KEY sont absents."
                )
            return "rest"
        # auto : la connexion SQL directe est préférée (schéma complet accessible)
        if self.has_postgres:
            return "postgres"
        if self.has_rest:
            return "rest"
        raise RuntimeError(
            "Aucun identifiant trouvé. Copiez .env.example vers .env puis renseignez "
            "DATABASE_URL (recommandé) ou SUPABASE_URL + SUPABASE_KEY."
        )

    def safe_summary(self) -> dict[str, Any]:
        """Résumé sans secret, pour les logs."""

        def _host(url: str | None) -> str | None:
            if not url:
                return None
            try:
                from urllib.parse import urlparse

                parsed = urlparse(url)
                return parsed.hostname
            except Exception:  # pragma: no cover - défensif
                return "<illisible>"

        # Le nom de la variable est publié, jamais sa valeur ; l'hôte est
        # réduit à sa forme masquée pour ne pas identifier l'instance.
        def _mask_host(url: str | None) -> str | None:
            # L'identifiant de projet Supabase fait partie du nom d'hôte. Même
            # s'il ne s'agit pas d'un secret d'authentification, il n'a aucune
            # utilité opérationnelle dans les journaux : on masque donc l'hôte
            # entier au lieu d'en conserver le suffixe.
            return "***" if _host(url) else None

        return {
            "postgres_source": self.database_url_source or "—",
            "postgres_host": _mask_host(self.database_url),
            "supabase_host": _mask_host(self.supabase_url),
            "cle_utilisee": self.supabase_key_source or "—",
            "schema": self.schema,
            "backend": self.backend,
        }


# Noms acceptés pour la chaîne de connexion PostgreSQL. La recherche est
# ensuite élargie à toute variable dont le nom évoque une connexion, afin de
# tolérer les variantes de nommage sans jamais exposer la valeur.
CONNECTION_STRING_ENV_NAMES: tuple[str, ...] = (
    "DATABASE_URL",
    "SUPABASE_CONNECTION_STRING",
    "SUPABASE_DB_URL",
    "POSTGRES_URL",
    "PG_CONNECTION_STRING",
)


def _find_connection_string() -> tuple[str | None, str | None]:
    """Cherche une chaîne de connexion, d'abord par nom exact puis par motif."""
    value, name = _first_env(CONNECTION_STRING_ENV_NAMES)
    if value:
        return value, name
    for key, raw in os.environ.items():
        upper = key.upper()
        if ("CONNECTION_STRING" in upper or "DATABASE_URL" in upper or "DB_URL" in upper) and raw:
            if raw.strip().startswith(("postgres://", "postgresql://")):
                return raw.strip(), key
    return None, None


def sanitize_database_url(url: str) -> str:
    """Nettoie une chaîne de connexion sans jamais en révéler le contenu.

    Deux corrections courantes :

    * les **crochets du gabarit Supabase** autour du mot de passe
      (``postgresql://user:[MOT_DE_PASSE]@hôte``) sont retirés — copiés tels
      quels, ils font échouer l'authentification ;
    * les caractères spéciaux du mot de passe sont ré-encodés pour l'URL.
    """
    from urllib.parse import quote

    raw = url.strip()
    # On n'utilise pas `urlsplit` pour découper les identifiants : il échoue sur
    # les crochets du gabarit (lus comme une adresse IPv6) et se trompe si le
    # mot de passe contient `@` ou `#`. Le découpage se fait donc sur le
    # DERNIER `@`, seul séparateur non ambigu entre identifiants et hôte.
    match = re.match(
        r"^(?P<scheme>postgres(?:ql)?)://"
        r"(?P<user>[^:/@]+)"
        r"(?::(?P<password>.*))?"
        r"@(?P<host>[^@/]+)"
        r"(?P<rest>[/?].*)?$",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return raw

    user = match.group("user")
    password = match.group("password")
    if password is None:
        return raw
    # Crochets du gabarit Supabase : `postgresql://user:[MOT_DE_PASSE]@hôte`.
    if password.startswith("[") and password.endswith("]"):
        password = password[1:-1]

    return (
        f"{match.group('scheme')}://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{match.group('host')}{match.group('rest') or ''}"
    )


def resolve_reachable_url(url: str) -> tuple[str, str]:
    """Bascule vers le pooler Supabase si l'hôte direct n'est pas joignable.

    Supabase réserve ``db.<ref>.supabase.co`` à l'IPv6 : sur un poste sans pile
    IPv6, ce nom ne résout pas. La voie IPv4 est le **pooler**, dont le nom
    dépend de la région (variable ``SUPABASE_POOLER_HOST``) et dont
    l'utilisateur devient ``postgres.<ref>``.

    Renvoie ``(url, mode)`` où ``mode`` vaut ``"direct"`` ou ``"pooler"``.
    Le nom d'hôte du pooler n'est pas un secret ; le mot de passe est repris
    tel quel depuis la chaîne d'origine et n'est jamais journalisé.
    """
    import socket
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        socket.getaddrinfo(host, parts.port or 5432, socket.AF_INET, socket.SOCK_STREAM)
        return url, "direct"
    except socket.gaierror:
        pass

    pooler_host = (os.getenv("SUPABASE_POOLER_HOST") or "").strip()
    match = re.match(r"^db\.([a-z0-9]+)\.supabase\.(co|com)$", host)
    if not pooler_host or not match:
        raise RuntimeError(
            "L'hôte de la chaîne de connexion n'est pas résolvable et aucun repli "
            "n'est configuré. Renseignez SUPABASE_POOLER_HOST (Supabase > Project "
            "Settings > Database > Connection pooling), par exemple "
            "aws-0-eu-central-1.pooler.supabase.com (nom générique d'illustration, "
            "à remplacer par celui affiché dans votre propre projet Supabase)."
        )
    project_ref = match.group(1)
    port = int(os.getenv("SUPABASE_POOLER_PORT", "5432"))
    user = f"postgres.{project_ref}"
    password = parts.password or ""
    netloc = f"{user}:{password}@{pooler_host}:{port}"
    query = parts.query or "sslmode=require"
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment)), "pooler"


def _build_database_url_from_parts() -> str | None:
    """Reconstruit une URL PostgreSQL à partir des variables PG* si besoin."""
    host = os.getenv("PGHOST")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    if not (host and user and password):
        return None
    from urllib.parse import quote_plus

    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "postgres")
    sslmode = os.getenv("PGSSLMODE", "require")
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}?sslmode={sslmode}"
    )


# Noms de variables acceptés pour la clé Supabase, par rôle.
# Par défaut on privilégie la clé anon/publishable (moindre privilège).
# `SUPABASE_KEY_ROLE=service` bascule sur la clé à privilèges élevés — nécessaire
# lorsque les politiques RLS empêchent toute lecture anonyme.
ANON_KEY_ENV_NAMES: tuple[str, ...] = (
    "SUPABASE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_ANON_PUBLIC_KEY",
    "SUPABASE_PUBLISHABLE_KEY",
)
SERVICE_KEY_ENV_NAMES: tuple[str, ...] = (
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_ROLE",
    "SUPABASE_SECRET_KEY",
)


def _first_env(names: Sequence[str]) -> tuple[str | None, str | None]:
    """Première variable non vide parmi ``names`` : renvoie (valeur, nom)."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip(), name
    return None, None


def get_credentials(key_role: str | None = None) -> DbCredentials:
    """Identifiants issus de l'environnement.

    ``key_role`` (ou la variable ``SUPABASE_KEY_ROLE``) vaut ``anon`` ou
    ``service`` et détermine quelle clé Supabase est utilisée en priorité.
    """
    _load_dotenv_once()
    raw_url, url_source = _find_connection_string()
    database_url = sanitize_database_url(raw_url) if raw_url else _build_database_url_from_parts()
    role = (key_role or os.getenv("SUPABASE_KEY_ROLE", "anon")).lower()
    order = (
        SERVICE_KEY_ENV_NAMES + ANON_KEY_ENV_NAMES
        if role == "service"
        else ANON_KEY_ENV_NAMES + SERVICE_KEY_ENV_NAMES
    )
    supabase_key, key_source = _first_env(order)
    return DbCredentials(
        database_url=database_url,
        database_url_source=url_source,
        supabase_url=(os.getenv("SUPABASE_URL") or "").strip() or None,
        supabase_key=supabase_key,
        supabase_key_source=key_source,
        schema=os.getenv("DB_SCHEMA", "public"),
        backend=os.getenv("DB_BACKEND", "auto").lower(),
    )


@dataclass
class Config:
    """Accès pratique à la configuration YAML."""

    raw: dict[str, Any] = field(default_factory=dict)
    path: Path = DEFAULT_CONFIG_PATH

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Lecture par chemin pointé, ex. ``cfg.get("target.frequency")``."""
        node: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return copy.deepcopy(node)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def resolve_path(self, dotted_key: str) -> Path:
        """Chemin du projet déclaré sous la section ``paths``."""
        value = self.get(dotted_key)
        if value is None:
            raise KeyError(f"Chemin non défini dans la configuration : {dotted_key}")
        path = PROJECT_ROOT / value
        return path


@lru_cache(maxsize=4)
def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return Config(raw=raw, path=config_path)
