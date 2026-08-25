"""Accès warehouse Supabase + mode démonstration."""
from __future__ import annotations

import os
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from ml_meta import ACTIVITY, MODELS

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

TIMEOUT = 45
PAGE = 1000


def _kpi(name: str, value: Any, unit: str, status: str, hint: str) -> dict[str, Any]:
    return {"name": name, "value": value, "unit": unit, "status": status, "hint": hint}


def build_fiche(k: dict[str, Any]) -> list[dict[str, Any]]:
    m = MODELS
    return [
        {
            "title": "Marge, prix & ventes",
            "items": [
                _kpi("Taux de marge brute", k.get("margin_pct"), "%", "calculable", "Part du CA une fois le coût des produits déduit."),
                _kpi("Chiffre d’affaires net", k.get("ca"), "F", "calculable", "Ventes des commandes validées uniquement."),
                _kpi("Panier moyen", k.get("panier_moyen"), "F", "calculable", "Montant moyen dépensé par commande."),
                _kpi("Impact prix / promotion", m["pricing"]["wape_qty"], "%", "modele", "WAPE quantité V1 — effet promo encore observationnel."),
            ],
        },
        {
            "title": "Stock & demande",
            "items": [
                _kpi("Rotation des stocks", k.get("stock_rotation"), "x", "calculable", "Vitesse à laquelle le stock se vend sur la période."),
                _kpi("Couverture de stock", k.get("stock_cover_days"), "j", "calculable", "Jours de vente encore tenus avec le stock actuel."),
                _kpi("Taux de rupture", k.get("rupture_pct"), "%", "calculable", "Part des produits à stock zéro."),
                _kpi("Précision de la prévision", m["forecasting"]["wape_30"], "%", "modele", "WAPE 30 jours du forecast V1 (plus bas = mieux)."),
            ],
        },
        {
            "title": "Parcours d’achat en ligne",
            "items": [
                _kpi("Taux de conversion", k.get("conversion"), "%", "calculable", "Visites du site qui aboutissent à un achat."),
                _kpi("Taux d’abandon de panier", k.get("abandon_pct"), "%", "calculable", "Paniers remplis jamais payés."),
            ],
        },
        {
            "title": "Recommandation & ventes croisées",
            "items": [
                _kpi("Part des paniers multi-produits", k.get("multi_pct"), "%", "calculable", "Commandes contenant plusieurs produits."),
                _kpi("Qualité des recommandations", m["recsys"]["recall10"], "%", "modele", "Recall@10 du moteur V1 (popularité)."),
            ],
        },
        {
            "title": "Clients & fidélisation",
            "items": [
                _kpi("Valeur vie client", k.get("clv"), "F", "calculable", "CA moyen par acheteur (proxy CLV)."),
                _kpi("CA segment VIP", k.get("ca_vip_share"), "%", "calculable", "Part du CA apportée par les VIP."),
            ],
        },
        {
            "title": "Valeur du projet & responsabilité",
            "items": [
                _kpi("Retour sur investissement (ROI)", None, "%", "modele", "Gain estimé du projet / coût — fourni après les modèles."),
                _kpi("Équité / absence de biais", None, "", "modele", "Écarts de prix ou de reco entre profils — IA responsable."),
                _kpi("Qualité des données", k.get("data_quality"), "%", "calculable", "Complétude des clés, montants, dates et régions."),
            ],
        },
    ]


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def supabase_key() -> str:
    for n in ("SUPABASE_KEY", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        v = _env(n)
        if v:
            return v
    return ""


def supabase_configured() -> bool:
    url = _env("SUPABASE_URL")
    key = supabase_key()
    return bool(url and key and "xxxx" not in url and "xxxx" not in key)


def postgres_configured() -> bool:
    return bool(_env("DATABASE_URL") and "xxxx" not in _env("DATABASE_URL"))


def _pg_connect():
    import psycopg2

    conn = psycopg2.connect(_env("DATABASE_URL"), connect_timeout=25)
    conn.autocommit = True
    return conn


def _pg_all(conn, sql: str, params=None) -> list[dict]:
    from psycopg2.extras import RealDictCursor

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def _pg_web_metrics(conn, filters: dict[str, str]) -> tuple[dict, dict, dict]:
    where = ["coalesce(est_bot, false) = false"]
    params: list[Any] = []
    if filters.get("appareil"):
        where.append("appareil = %s")
        params.append(filters["appareil"])
    if filters.get("source_trafic"):
        where.append("source_trafic = %s")
        params.append(filters["source_trafic"])
    clause = " and ".join(where)
    funnel = {
        r["type_event"]: int(r["n"])
        for r in _pg_all(
            conn,
            f"""
            select type_event, count(*)::int as n
            from fact_evenements_web
            where {clause}
            group by type_event
            """,
            params,
        )
        if r.get("type_event")
    }
    devices = {
        r["appareil"]: int(r["n"])
        for r in _pg_all(
            conn,
            f"""
            select appareil, count(*)::int as n
            from fact_evenements_web
            where {clause}
            group by appareil
            """,
            params,
        )
        if r.get("appareil")
    }
    traffic = {
        r["source_trafic"]: int(r["n"])
        for r in _pg_all(
            conn,
            f"""
            select source_trafic, count(*)::int as n
            from fact_evenements_web
            where {clause}
            group by source_trafic
            """,
            params,
        )
        if r.get("source_trafic")
    }
    return funnel, devices, traffic


def _load_warehouse_postgres() -> dict[str, Any]:
    """Lecture directe Postgres (rôle postgres) — contourne RLS."""
    conn = _pg_connect()
    try:
        produits = _pg_all(conn, "select * from dim_produit")
        clients = _pg_all(conn, "select * from dim_client")
        dates = _pg_all(conn, "select * from dim_date")
        promos = _pg_all(conn, "select * from dim_promotion")
        ventes = _pg_all(
            conn,
            """
            select vente_id, produit_key, client_key, date_key, promo_key,
                   quantite, montant_net_xof, order_id, statut_commande
            from fact_ventes
            """,
        )
        funnel, devices, traffic = _pg_web_metrics(conn, {})
        stock_rows = _pg_all(
            conn,
            """
            select produit_key, date_key, niveau_stock
            from fact_stock
            where date_key = (select max(date_key) from fact_stock)
            """,
        )
        return {
            "source": "supabase",
            "backend": "postgres",
            "empty": not ventes,
            "produits": produits,
            "clients": clients,
            "dates": dates,
            "promos": promos,
            "ventes": ventes,
            "stock_rows": stock_rows,
            "funnel": funnel,
            "devices": devices,
            "traffic": traffic,
        }
    finally:
        conn.close()


def load_postgres() -> dict[str, Any]:
    wh = _load_warehouse_postgres()
    payload = _assemble_from_warehouse(wh, {})
    payload["empty"] = wh.get("empty", False)
    return payload


def _headers() -> dict[str, str]:
    key = supabase_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Prefer": "count=exact",
    }


def _base() -> str:
    return _env("SUPABASE_URL").rstrip("/") + "/rest/v1"


def _get(path: str, params: dict[str, str] | None = None, range_end: int | None = None) -> tuple[list, int | None]:
    headers = _headers()
    if range_end is not None:
        headers["Range"] = f"0-{range_end}"
        headers["Range-Unit"] = "items"
    r = requests.get(f"{_base()}/{path}", headers=headers, params=params or {}, timeout=TIMEOUT)
    r.raise_for_status()
    total = None
    cr = r.headers.get("Content-Range") or ""
    if "/" in cr:
        try:
            total = int(cr.split("/")[-1])
        except ValueError:
            total = None
    data = r.json() if r.text else []
    return data if isinstance(data, list) else [], total


def _count(table: str, extra: dict[str, str] | None = None) -> int:
    params = {"select": "count", **(extra or {})}
    # PostgREST: select=* with Prefer count and Range 0-0
    headers = _headers()
    headers["Range"] = "0-0"
    r = requests.get(
        f"{_base()}/{table}",
        headers=headers,
        params={"select": "*", **(extra or {})},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    cr = r.headers.get("Content-Range") or ""
    if "/" in cr and cr.split("/")[-1] != "*":
        return int(cr.split("/")[-1])
    return 0


def _all(table: str, select: str, extra: dict[str, str] | None = None, cap: int = 120_000) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while start < cap:
        headers = _headers()
        headers["Range"] = f"{start}-{start + PAGE - 1}"
        headers["Range-Unit"] = "items"
        r = requests.get(
            f"{_base()}/{table}",
            headers=headers,
            params={"select": select, **(extra or {})},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        chunk = r.json() if r.text else []
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        start += PAGE
    return rows


def _col(row: dict, *names: str, default: Any = None) -> Any:
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return default


def _load_warehouse_live() -> dict[str, Any]:
    produits = _all("dim_produit", "produit_key,product_id,product_name,categorie,marque,prix_base_xof,cout_xof,is_current")
    clients = _all("dim_client", "client_key,region,age_bracket,segment_fidelite,is_current", cap=8_000)
    dates = _all("dim_date", "date_key,date_complete,annee,mois,jour_semaine,est_weekend")
    promos = _all("dim_promotion", "*", cap=500)

    try:
        ventes = _all(
            "fact_ventes",
            "vente_id,produit_key,client_key,date_key,promo_key,quantite,montant_net_xof,order_id,statut_commande",
        )
    except requests.HTTPError:
        ventes = []

    funnel: dict[str, int] = {}
    devices: dict[str, int] = {}
    traffic: dict[str, int] = {}
    try:
        for ev in ("view", "add_to_cart", "purchase"):
            funnel[ev] = _count("fact_evenements_web", {"type_event": f"eq.{ev}"})
        for d in ("mobile", "desktop", "tablet"):
            try:
                devices[d] = _count("fact_evenements_web", {"appareil": f"eq.{d}"})
            except requests.HTTPError:
                devices[d] = _count("fact_evenements_web", {"device": f"eq.{d}"})
        for s in ("organic_search", "social_media", "direct", "email_campaign", "paid_ads", "affiliate"):
            try:
                traffic[s] = _count("fact_evenements_web", {"source_trafic": f"eq.{s}"})
            except requests.HTTPError:
                break
    except requests.HTTPError:
        funnel = {"view": 0, "add_to_cart": 0, "purchase": 0}

    stock_rows: list[dict] = []
    try:
        if dates:
            last_key = max(str(_col(d, "date_key")) for d in dates)
            stock_rows = _all("fact_stock", "produit_key,date_key,niveau_stock", extra={"date_key": f"eq.{last_key}"}, cap=2_000)
    except requests.HTTPError:
        stock_rows = []

    return {
        "source": "supabase",
        "backend": "rest",
        "empty": not produits and not ventes,
        "produits": produits,
        "clients": clients,
        "dates": dates,
        "promos": promos,
        "ventes": ventes,
        "stock_rows": stock_rows,
        "funnel": funnel,
        "devices": devices,
        "traffic": traffic,
    }


def load_live() -> dict[str, Any]:
    wh = _load_warehouse_live()
    if wh.get("empty"):
        demo = load_demo()
        demo["empty"] = True
        demo["error"] = (
            "Supabase joignable, mais 0 ligne (RLS). Exécute dashboard/ouvrir_lecture.sql "
            "dans le SQL Editor, ou mets la clé service_role dans SUPABASE_KEY."
        )
        return demo
    return _assemble_from_warehouse(wh, {})


def _uniq(values: list[Any]) -> list[str]:
    out = sorted({str(v) for v in values if v not in (None, "")})
    return out


def parse_filters(raw: dict[str, str] | None) -> dict[str, str]:
    if not raw:
        return {}
    keys = (
        "categorie", "marque", "produit", "region", "segment", "age", "client",
        "annee", "mois", "periode", "weekend", "promo", "statut",
        "appareil", "source_trafic", "stock_level", "q",
    )
    out: dict[str, str] = {}
    for k in keys:
        v = (raw.get(k) or "").strip()
        if v and v.lower() != "all":
            out[k] = v
    return out


def _parse_date_key(s: Any):
    if s is None or s == "" or s == "—":
        return None
    raw = str(s).strip()[:10]
    from datetime import datetime

    for fmt, val in (("%Y-%m-%d", raw), ("%Y-%m", raw[:7]), ("%Y%m%d", raw.replace("-", "")[:8])):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def _jours_inactif(derniere: Any, ref) -> int | None:
    """Jours écoulés depuis le dernier achat (réf. = dernière date du périmètre)."""
    d1 = _parse_date_key(derniere)
    if not d1 or ref is None:
        return None
    return max((ref - d1).days, 0)


def _classer_client(
    jours_inactif: int | None,
    n_cmd: int,
    freq_mois: float,
    jours_entre: float | None,
) -> str:
    """
    4 statuts exclusifs (comportement d'achat, pas le libellé Mozart) :
    - vip     : achète très souvent (≈ chaque semaine / ≥ 1,5 cmd/mois)
    - loyal   : achète de façon régulière mais moins fréquent
    - inactif : longtemps sans achat (6 mois → < 2 ans)
    - churn   : parti — ≥ 2 ans sans achat
    """
    ji = int(jours_inactif) if jours_inactif is not None else 0
    if ji >= 730:
        return "churn"
    if ji >= 180:
        return "inactif"
    # Actifs
    entre = float(jours_entre) if jours_entre is not None else None
    if n_cmd >= 2 and (
        float(freq_mois or 0) >= 1.5
        or (entre is not None and entre <= 14)
    ):
        return "vip"
    return "loyal"


def _frequence_achat(premiere: Any, derniere: Any, n_cmd: int) -> dict[str, Any]:
    """Fréquence d'achat : commandes / mois sur la période d'activité du client."""
    n = int(n_cmd or 0)
    d0 = _parse_date_key(premiere)
    d1 = _parse_date_key(derniere)
    if n <= 0:
        return {"freq_mois": 0.0, "jours_actif": 0, "libelle": "Aucune commande", "jours_entre": None}
    if not d0 or not d1:
        return {"freq_mois": float(n), "jours_actif": 0, "libelle": f"{n} cmd (période inconnue)", "jours_entre": None}
    days = max((d1 - d0).days, 1)
    freq = round(n / (days / 30.0), 2)
    entre = round(days / max(n - 1, 1), 1) if n > 1 else float(days)
    return {
        "freq_mois": freq,
        "jours_actif": days,
        "libelle": f"{freq} cmd/mois",
        "jours_entre": entre,
    }


def _client_label(c: dict) -> str:
    key = c.get("client_key")
    reg = c.get("region") or "?"
    seg = c.get("segment_fidelite") or "?"
    return f"Client {key} · {reg} · {seg}"


def build_filter_options(wh: dict[str, Any]) -> dict[str, Any]:
    produits = wh.get("produits") or []
    clients = wh.get("clients") or []
    dates = wh.get("dates") or []
    ventes = wh.get("ventes") or []
    statuts = _uniq([v.get("statut_commande") or "confirmee" for v in ventes])
    if not statuts:
        statuts = ["confirmee", "annulee"]
    mois_vals = sorted({int(d.get("mois")) for d in dates if d.get("mois") is not None})

    client_opts: list[str] = []
    client_labels: dict[str, str] = {}
    clients_by_age: dict[str, list[str]] = {}
    clients_by_segment: dict[str, list[str]] = {}
    clients_by_region: dict[str, list[str]] = {}
    for c in clients:
        if c.get("is_current") is False:
            continue
        ck = str(c.get("client_key"))
        client_opts.append(ck)
        client_labels[ck] = _client_label(c)
        age = str(c.get("age_bracket") or "")
        seg = str(c.get("segment_fidelite") or "")
        reg = str(c.get("region") or "")
        if age:
            clients_by_age.setdefault(age, []).append(ck)
        if seg:
            clients_by_segment.setdefault(seg, []).append(ck)
        if reg:
            clients_by_region.setdefault(reg, []).append(ck)

    produits_by_categorie: dict[str, list[str]] = {}
    produits_by_marque: dict[str, list[str]] = {}
    all_produits: list[str] = []
    for p in produits:
        pname = str(p.get("product_name") or p.get("product_id") or "")
        if not pname:
            continue
        all_produits.append(pname)
        cat = str(p.get("categorie") or "")
        marque = str(p.get("marque") or "")
        if cat:
            produits_by_categorie.setdefault(cat, []).append(pname)
        if marque:
            produits_by_marque.setdefault(marque, []).append(pname)

    # Dédupliquer listes dépendantes
    for d in (produits_by_categorie, produits_by_marque, clients_by_age, clients_by_segment, clients_by_region):
        for k, vals in d.items():
            d[k] = _uniq(vals)

    return {
        "categories": _uniq([p.get("categorie") for p in produits]),
        "marques": _uniq([p.get("marque") for p in produits]),
        "produits": _uniq(all_produits)[:400],
        "produits_by_categorie": produits_by_categorie,
        "produits_by_marque": produits_by_marque,
        "regions": _uniq([c.get("region") for c in clients]),
        "segments": _uniq([c.get("segment_fidelite") for c in clients]),
        "ages": _uniq([c.get("age_bracket") for c in clients]),
        "clients": client_opts[:800],
        "client_labels": client_labels,
        "clients_by_age": clients_by_age,
        "clients_by_segment": clients_by_segment,
        "clients_by_region": clients_by_region,
        "annees": sorted(_uniq([d.get("annee") for d in dates]), reverse=True),
        "mois": [str(m) for m in mois_vals],
        "statuts": statuts,
        "appareils": _uniq(list((wh.get("devices") or {}).keys())),
        "sources_trafic": _uniq(list((wh.get("traffic") or {}).keys())),
        "weekends": ["semaine", "weekend"],
        "promos": ["oui", "non"],
        "stock_levels": ["rupture", "faible", "ok"],
    }


def _date_bounds(dates: list[dict], periode: str) -> tuple[str | None, str | None]:
    keys = sorted(str(d.get("date_key") or "") for d in dates if d.get("date_key"))
    if not keys or periode in ("", "all"):
        return None, None
    max_key = keys[-1]
    try:
        if len(max_key) == 8:
            end = date(int(max_key[:4]), int(max_key[4:6]), int(max_key[6:8]))
        else:
            end = date.fromisoformat(str(max_key)[:10])
    except ValueError:
        return None, None
    days = {"30d": 30, "3m": 92, "6m": 183, "1y": 365}.get(periode, 0)
    if not days:
        return None, None
    start = end - timedelta(days=days - 1)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _in_period(date_key: str, dmap: dict, start_key: str | None, end_key: str | None) -> bool:
    if not start_key or not end_key:
        return True
    dk = str(date_key or "")
    if len(dk) >= 8:
        key = dk[:8]
    else:
        dd = dmap.get(dk, {})
        dc = dd.get("date_complete")
        if not dc:
            return False
        key = str(dc).replace("-", "")[:8]
    return start_key <= key <= end_key


def _ensure_vente_indexes(wh: dict[str, Any]) -> None:
    """Index ventes par année pour filtres instantanés."""
    if wh.get("_idx_ready"):
        return
    dates = wh.get("dates") or []
    dmap = {str(d.get("date_key")): d for d in dates}
    by_annee: dict[str, list] = {}
    for v in wh.get("ventes") or []:
        dd = dmap.get(str(v.get("date_key")), {}) or {}
        annee = str(dd.get("annee") or "")
        by_annee.setdefault(annee, []).append(v)
    wh["_by_annee"] = by_annee
    wh["_dmap"] = dmap
    wh["_idx_ready"] = True


def filter_ventes(wh: dict[str, Any], filters: dict[str, str]) -> list[dict]:
    _ensure_vente_indexes(wh)
    produits = wh.get("produits") or []
    clients = wh.get("clients") or []
    dates = wh.get("dates") or []
    pmap = {p.get("produit_key"): p for p in produits}
    cmap = {c.get("client_key"): c for c in clients}
    dmap = wh.get("_dmap") or {str(d.get("date_key")): d for d in dates}
    start_key, end_key = _date_bounds(dates, filters.get("periode", "all"))
    q = (filters.get("q") or "").lower()
    # Démarrer sur le sous-ensemble année si filtré (beaucoup plus rapide)
    if filters.get("annee") and filters["annee"] in (wh.get("_by_annee") or {}):
        source = wh["_by_annee"][filters["annee"]]
    else:
        source = wh.get("ventes") or []
    out: list[dict] = []
    for v in source:
        prod = pmap.get(v.get("produit_key"), {}) or {}
        cli = cmap.get(v.get("client_key"), {}) or {}
        dd = dmap.get(str(v.get("date_key")), {}) or {}
        if filters.get("categorie") and prod.get("categorie") != filters["categorie"]:
            continue
        if filters.get("marque") and prod.get("marque") != filters["marque"]:
            continue
        pname = prod.get("product_name") or prod.get("product_id")
        if filters.get("produit") and str(pname) != filters["produit"]:
            continue
        if filters.get("region") and cli.get("region") != filters["region"]:
            continue
        if filters.get("segment") and cli.get("segment_fidelite") != filters["segment"]:
            continue
        if filters.get("client") and str(cli.get("client_key")) != str(filters["client"]):
            continue
        if filters.get("age") and cli.get("age_bracket") != filters["age"]:
            continue
        if filters.get("annee") and str(dd.get("annee")) != str(filters["annee"]):
            continue
        if filters.get("mois") and str(dd.get("mois")) != str(filters["mois"]):
            continue
        if not _in_period(str(v.get("date_key")), dmap, start_key, end_key):
            continue
        if filters.get("weekend") == "weekend" and not dd.get("est_weekend"):
            continue
        if filters.get("weekend") == "semaine" and dd.get("est_weekend"):
            continue
        if filters.get("promo") == "oui" and not v.get("promo_key"):
            continue
        if filters.get("promo") == "non" and v.get("promo_key"):
            continue
        statut = v.get("statut_commande") or "confirmee"
        if filters.get("statut") and statut != filters["statut"]:
            continue
        if q:
            blob = " ".join(
                str(x or "")
                for x in (
                    v.get("vente_id"),
                    v.get("order_id"),
                    pname,
                    prod.get("categorie"),
                    cli.get("region"),
                    cli.get("client_key"),
                    cli.get("segment_fidelite"),
                )
            ).lower()
            if q not in blob:
                continue
        out.append(v)
    return out


def filter_stock(wh: dict[str, Any], filters: dict[str, str]) -> list[dict]:
    produits = wh.get("produits") or []
    pmap = {p.get("produit_key"): p for p in produits}
    out: list[dict] = []
    for row in wh.get("stock_rows") or []:
        prod = pmap.get(row.get("produit_key"), {}) or {}
        if filters.get("categorie") and prod.get("categorie") != filters["categorie"]:
            continue
        if filters.get("marque") and prod.get("marque") != filters["marque"]:
            continue
        pname = prod.get("product_name") or prod.get("product_id")
        if filters.get("produit") and str(pname) != filters["produit"]:
            continue
        lvl = int(row.get("niveau_stock") or 0)
        level = filters.get("stock_level")
        if level == "rupture" and lvl > 0:
            continue
        if level == "faible" and not (0 < lvl < 40):
            continue
        if level == "ok" and lvl < 40:
            continue
        out.append(row)
    return out


def _web_metrics(wh: dict[str, Any], filters: dict[str, str]) -> tuple[dict, dict, dict]:
    web_filters = {k: filters[k] for k in ("appareil", "source_trafic") if k in filters}
    if wh.get("backend") == "postgres" and web_filters:
        conn = _pg_connect()
        try:
            pg_filters = dict(web_filters)
            if pg_filters.get("source_trafic"):
                pg_filters["source_trafic"] = pg_filters["source_trafic"].replace(" ", "_")
            return _pg_web_metrics(conn, pg_filters)
        finally:
            conn.close()
    return wh.get("funnel") or {}, wh.get("devices") or {}, wh.get("traffic") or {}


def _filter_options_cached(wh: dict[str, Any]) -> dict[str, Any]:
    cached = wh.get("_filter_options")
    if cached is not None:
        return cached
    opts = build_filter_options(wh)
    wh["_filter_options"] = opts
    return opts


def _row_from_vente(
    v: dict[str, Any],
    pmap: dict[Any, dict],
    cmap: dict[Any, dict],
    dmap: dict[str, dict],
) -> dict[str, Any]:
    prod = pmap.get(v.get("produit_key"), {})
    cli = cmap.get(v.get("client_key"), {})
    dk = str(v.get("date_key") or "")
    dd = dmap.get(dk, {})
    if dd.get("date_complete"):
        date_str = str(dd["date_complete"])[:10]
    elif len(dk) == 8:
        date_str = f"{dk[:4]}-{dk[4:6]}-{dk[6:8]}"
    else:
        date_str = dk or "—"
    qty = int(v.get("quantite") or 0)
    montant = float(v.get("montant_net_xof") or 0)
    prix_u = round(montant / qty) if qty else montant
    return {
        "vente_id": v.get("vente_id"),
        "date": date_str,
        "jour": dd.get("jour_semaine") or "—",
        "id": v.get("order_id") or v.get("vente_id"),
        "client_key": cli.get("client_key"),
        "client": _client_label(cli) if cli else "—",
        "produit": prod.get("product_name") or prod.get("product_id") or "—",
        "marque": prod.get("marque") or "—",
        "categorie": prod.get("categorie") or "—",
        "region": cli.get("region") or "—",
        "segment": cli.get("segment_fidelite") or "—",
        "age": cli.get("age_bracket") or "—",
        "quantite": qty,
        "prix_unitaire": prix_u,
        "montant": montant,
        "promo": "oui" if v.get("promo_key") else "non",
        "statut": v.get("statut_commande") or "confirmee",
    }


def _assemble_from_warehouse(wh: dict[str, Any], filters: dict[str, str]) -> dict[str, Any]:
    ventes = filter_ventes(wh, filters)
    stock_rows = filter_stock(wh, filters)
    funnel, devices, traffic = _web_metrics(wh, filters)
    payload = _assemble(
        wh.get("produits") or [],
        wh.get("clients") or [],
        wh.get("dates") or [],
        wh.get("promos") or [],
        ventes,
        funnel,
        devices,
        traffic,
        stock_rows,
        source=wh.get("source") or "demo",
        all_ventes=wh.get("ventes") or [],
    )
    payload["filter_options"] = _filter_options_cached(wh)
    payload["active_filters"] = filters
    payload["filtered_rows"] = len(ventes)
    payload["model_kpis"] = {
        "wape_30": MODELS["forecasting"]["wape_30"],
        "wape_qty": MODELS["pricing"]["wape_qty"],
        "recall10": MODELS["recsys"]["recall10"],
        "roi": None,
    }
    payload["mlops"] = {
        "roadmap": [
            "Brancher les prévisions forecast en production",
            "Valider humainement le simulateur pricing",
            "Tester une reco segmentée vs popularité",
            "Ajouter drift monitoring et alertes modèle",
        ],
        "checks": [
            {"label": "Modèles V1 documentés", "ok": True},
            {"label": "Aucun déploiement automatique", "ok": True},
            {"label": "Tests anti-fuite temporelle", "ok": True},
            {"label": "ROI estimé disponible", "ok": False},
        ],
    }
    return payload


def _assemble(
    produits, clients, dates, promos, ventes, funnel, devices, traffic, stock_rows, source: str,
    all_ventes: list | None = None,
) -> dict[str, Any]:
    pmap = {p.get("produit_key"): p for p in produits}
    cmap = {c.get("client_key"): c for c in clients}
    dmap = {str(d.get("date_key")): d for d in dates}

    ca = 0.0
    qty = 0
    orders = set()
    buyers = set()
    promo_ca = 0.0
    promo_keys: set = set()
    by_month: dict[str, float] = {}
    by_qty: dict[str, float] = {}
    by_day: dict[str, float] = {}
    by_day_qty: dict[str, float] = {}
    by_cat: dict[str, float] = {}
    by_cat_month: dict[str, dict[str, float]] = {}
    by_month_orders: dict[str, set] = {}
    by_region: dict[str, float] = {}
    by_seg: dict[str, int] = {}
    by_seg_ca: dict[str, float] = {}
    order_skus: dict[Any, set] = {}
    n_ok_region = 0
    n_ok_prod = 0
    n_ok_amt = 0
    n_ok_date = 0
    by_prod: dict[str, dict] = {}
    by_cli: dict[Any, dict] = {}
    prod_year_keys: set[tuple[str, str]] = set()
    cli_year_keys: set[tuple[Any, str]] = set()

    profit = 0.0
    for v in ventes:
        m = float(v.get("montant_net_xof") or 0)
        q = int(v.get("quantite") or 0)
        ca += m
        qty += q
        oid = v.get("order_id") or v.get("vente_id")
        orders.add(oid)
        buyers.add(v.get("client_key"))
        if v.get("promo_key"):
            promo_ca += m
            promo_keys.add(v.get("promo_key"))
        dk = str(v.get("date_key") or "")
        dd = dmap.get(dk, {})
        month = None
        if dd.get("date_complete"):
            month = str(dd["date_complete"])[:7]
        elif len(dk) >= 6:
            month = f"{dk[:4]}-{dk[4:6]}"
        if month:
            by_month[month] = by_month.get(month, 0) + m
            by_qty[month] = by_qty.get(month, 0) + q
            by_month_orders.setdefault(month, set()).add(oid)
            by_cat_month.setdefault(month, {})
            cat_m = (pmap.get(v.get("produit_key"), {}) or {}).get("categorie") or "Autre"
            by_cat_month[month][cat_m] = by_cat_month[month].get(cat_m, 0) + m
        day = None
        if dd.get("date_complete"):
            day = str(dd["date_complete"])[:10]
        elif len(dk) == 8:
            day = f"{dk[:4]}-{dk[4:6]}-{dk[6:8]}"
        if day:
            by_day[day] = by_day.get(day, 0) + m
            by_day_qty[day] = by_day_qty.get(day, 0) + q
        prod = pmap.get(v.get("produit_key"), {})
        cat = prod.get("categorie") or "Autre"
        by_cat[cat] = by_cat.get(cat, 0) + m
        cli = cmap.get(v.get("client_key"), {})
        reg = cli.get("region") or "Non renseigné"
        by_region[reg] = by_region.get(reg, 0) + m
        order_skus.setdefault(oid, set()).add(v.get("produit_key"))
        seg = cli.get("segment_fidelite") or "inconnu"
        by_seg_ca[seg] = by_seg_ca.get(seg, 0) + m
        if cli.get("region"):
            n_ok_region += 1
        if prod:
            n_ok_prod += 1
        if v.get("montant_net_xof") is not None:
            n_ok_amt += 1
        if v.get("date_key"):
            n_ok_date += 1
        cout = float(prod.get("cout_xof") or 0)
        profit += m - cout * q
        pname = prod.get("product_name") or prod.get("product_id") or "—"
        if pname not in by_prod:
            by_prod[pname] = {
                "produit": pname,
                "categorie": cat,
                "marque": prod.get("marque") or "—",
                "quantite": 0,
                "ca": 0.0,
                "lignes": 0,
                "commandes": set(),
                "premiere": None,
                "derniere": None,
            }
        by_prod[pname]["quantite"] += q
        by_prod[pname]["ca"] += m
        by_prod[pname]["lignes"] += 1
        by_prod[pname]["commandes"].add(oid)
        date_v = day or month or dk or None
        if date_v:
            prev_p = by_prod[pname]["premiere"]
            prev_d = by_prod[pname]["derniere"]
            if prev_p is None or date_v < prev_p:
                by_prod[pname]["premiere"] = date_v
            if prev_d is None or date_v > prev_d:
                by_prod[pname]["derniere"] = date_v
        ck = cli.get("client_key") or v.get("client_key")
        if ck not in by_cli:
            by_cli[ck] = {
                "client_key": ck,
                "client": _client_label(cli) if cli else "—",
                "region": cli.get("region") or "—",
                "segment": cli.get("segment_fidelite") or "—",
                "age": cli.get("age_bracket") or "—",
                "quantite": 0,
                "ca": 0.0,
                "lignes": 0,
                "commandes": set(),
                "premiere": None,
                "derniere": None,
            }
        by_cli[ck]["quantite"] += q
        by_cli[ck]["ca"] += m
        by_cli[ck]["lignes"] += 1
        by_cli[ck]["commandes"].add(oid)
        if date_v:
            prev_p = by_cli[ck]["premiere"]
            prev_d = by_cli[ck]["derniere"]
            if prev_p is None or date_v < prev_p:
                by_cli[ck]["premiere"] = date_v
            if prev_d is None or date_v > prev_d:
                by_cli[ck]["derniere"] = date_v
        annee_v = str(dd.get("annee") or "")
        if annee_v:
            prod_year_keys.add((pname, annee_v))
            cli_year_keys.add((ck, annee_v))

    for row in by_cli.values():
        s = row.get("segment") or "inconnu"
        by_seg[s] = by_seg.get(s, 0) + 1

    top_recent = sorted(ventes, key=lambda x: str(x.get("date_key") or ""), reverse=True)[:200]
    recent_out = [_row_from_vente(v, pmap, cmap, dmap) for v in top_recent]

    produits_detail = sorted(
        [
            {
                "produit": v["produit"],
                "categorie": v["categorie"],
                "marque": v["marque"],
                "quantite": v["quantite"],
                "ca": round(v["ca"]),
                "lignes": v["lignes"],
                "commandes": len(v["commandes"]),
                "premiere": v.get("premiere") or "—",
                "derniere": v.get("derniere") or "—",
            }
            for v in by_prod.values()
        ],
        key=lambda x: -x["ca"],
    )

    clients_all = []
    from datetime import datetime as _dt

    def _date_from_vente(vrow: dict):
        dk = str(vrow.get("date_key") or "")
        dd = dmap.get(dk, {})
        if dd.get("date_complete"):
            return _parse_date_key(str(dd["date_complete"])[:10])
        if len(dk) == 8:
            return _parse_date_key(f"{dk[:4]}-{dk[4:6]}-{dk[6:8]}")
        return _parse_date_key(dk)

    # Dernier / 1er achat sur TOUT l’historique warehouse
    last_buy_global: dict[Any, Any] = {}
    first_buy_global: dict[Any, Any] = {}
    ca_global: dict[Any, float] = {}
    cmd_global: dict[Any, set] = {}
    for vrow in (all_ventes or ventes or []):
        ck = vrow.get("client_key")
        if ck is None:
            continue
        dt = _date_from_vente(vrow)
        if dt:
            prev = last_buy_global.get(ck)
            if prev is None or dt > prev:
                last_buy_global[ck] = dt
            prev0 = first_buy_global.get(ck)
            if prev0 is None or dt < prev0:
                first_buy_global[ck] = dt
        ca_global[ck] = ca_global.get(ck, 0.0) + float(vrow.get("montant_net_xof") or 0)
        cmd_global.setdefault(ck, set()).add(vrow.get("order_id") or vrow.get("vente_id"))

    ref_candidates = list(last_buy_global.values())
    ref_inactivite = max(ref_candidates) if ref_candidates else _dt.now()

    def _row_client(
        ck, client, region, segment, age, ca_cli, n_cmd, prem, dern, quantite=0, lignes=0, ca_historique=None
    ):
        last_dt = last_buy_global.get(ck) or _parse_date_key(dern)
        first_dt = first_buy_global.get(ck) or _parse_date_key(prem)
        # Fréquence sur l’historique global (plus fiable que le seul filtre)
        prem_g = first_dt.strftime("%Y-%m-%d") if first_dt else (prem or "—")
        dern_g = last_dt.strftime("%Y-%m-%d") if last_dt else (dern or "—")
        n_g = len(cmd_global.get(ck) or []) or n_cmd
        freq = _frequence_achat(prem_g, dern_g, n_g)
        jours_inactif = max((ref_inactivite - last_dt).days, 0) if last_dt else None
        statut = _classer_client(jours_inactif, n_g, freq["freq_mois"], freq["jours_entre"])
        row = {
            "client_key": ck,
            "client": client,
            "region": region,
            "segment": segment,
            "age": age,
            "quantite": quantite,
            "ca": ca_cli,
            "lignes": lignes,
            "commandes": n_g,
            "premiere": prem_g,
            "derniere": dern_g,
            "statut_client": statut,
            "vip": statut == "vip",
            "loyal": statut == "loyal",
            "inactif": statut == "inactif",
            "churn": statut == "churn",
            "jours_inactif": jours_inactif,
            "freq_mois": freq["freq_mois"],
            "freq_libelle": freq["libelle"],
            "jours_actif": freq["jours_actif"],
            "jours_entre_cmd": freq["jours_entre"],
            "panier_moyen": round((ca_historique if ca_historique is not None else ca_cli) / max(n_g, 1)),
        }
        if ca_historique is not None:
            row["ca_historique"] = ca_historique
        return row

    seen_ck: set = set()
    for v in by_cli.values():
        ck = v["client_key"]
        seen_ck.add(ck)
        clients_all.append(
            _row_client(
                ck,
                v["client"],
                v["region"],
                v["segment"],
                v["age"],
                round(v["ca"]),
                len(v["commandes"]),
                v.get("premiere") or "—",
                v.get("derniere") or "—",
                quantite=v["quantite"],
                lignes=v["lignes"],
            )
        )

    # Absents du filtre courant mais déjà churn (≥ 2 ans) ou inactifs
    for ck, last_dt in last_buy_global.items():
        if ck in seen_ck:
            continue
        jours_inactif = max((ref_inactivite - last_dt).days, 0)
        if jours_inactif < 180:
            continue
        cli = cmap.get(ck) or {}
        n_cmd = len(cmd_global.get(ck) or [])
        prem_dt = first_buy_global.get(ck)
        clients_all.append(
            _row_client(
                ck,
                _client_label(cli) if cli else f"Client {ck}",
                cli.get("region") or "—",
                cli.get("segment_fidelite") or "—",
                cli.get("age_bracket") or "—",
                0,
                n_cmd,
                prem_dt.strftime("%Y-%m-%d") if prem_dt else "—",
                last_dt.strftime("%Y-%m-%d"),
                ca_historique=round(ca_global.get(ck, 0)),
            )
        )

    order_statut = {"vip": 0, "loyal": 1, "inactif": 2, "churn": 3}
    clients_all.sort(
        key=lambda x: (
            order_statut.get(x["statut_client"], 9),
            -(x.get("jours_inactif") or 0) if x["statut_client"] in ("churn", "inactif") else 0,
            -x["ca"],
        )
    )
    vips = [c for c in clients_all if c["statut_client"] == "vip"]
    loyaux = [c for c in clients_all if c["statut_client"] == "loyal"]
    inactifs = [c for c in clients_all if c["statut_client"] == "inactif"]
    churns = [c for c in clients_all if c["statut_client"] == "churn"]
    # Détail UI : tous VIP/churn + échantillon loyaux/inactifs
    clients_detail = (
        vips
        + churns
        + loyaux[: max(0, 400 - min(len(vips), 200))]
        + inactifs[:200]
    )
    n_clients_vip = len(vips)
    n_clients_loyal = len(loyaux)
    n_clients_inactif = len(inactifs)
    n_clients_churn = len(churns)
    n_clients_uniques = n_clients_vip + n_clients_loyal + n_clients_inactif + n_clients_churn
    freq_vip_moy = round(sum(c["freq_mois"] for c in vips) / max(len(vips), 1), 2) if vips else 0.0
    ca_vip_total = sum(c["ca"] for c in vips)

    months = sorted(by_month)
    days = sorted(by_day)
    views = funnel.get("view") or 0
    carts = funnel.get("add_to_cart") or 0
    purch = funnel.get("purchase") or 0
    conv = (purch / views * 100) if views else 0
    cac_proxy = 0
    n_produits_filtres = len(prod_year_keys) if prod_year_keys else len(by_prod)
    n_clients_filtres = len(cli_year_keys) if cli_year_keys else len(by_cli)
    n_promos_utilisees = len(promo_keys)
    arpu = ca / max(len(buyers), 1)

    stock_alert = []
    stock_detail = []
    for s in stock_rows:
        lvl = int(s.get("niveau_stock") or 0)
        prod = pmap.get(s.get("produit_key"), {})
        niveau = "rupture" if lvl <= 0 else ("faible" if lvl < 40 else "ok")
        item = {
            "produit": prod.get("product_name") or prod.get("product_id") or "—",
            "categorie": prod.get("categorie") or "—",
            "marque": prod.get("marque") or "—",
            "stock": lvl,
            "niveau": niveau,
            "prix_catalogue": float(prod.get("prix_base_xof") or 0),
        }
        stock_detail.append(item)
        if lvl < 40:
            stock_alert.append({"produit": item["produit"], "stock": lvl, "categorie": item["categorie"]})
    stock_alert = sorted(stock_alert, key=lambda x: x["stock"])[:8]
    stock_detail = sorted(stock_detail, key=lambda x: x["stock"])

    stock_levels = [int(s.get("niveau_stock") or 0) for s in stock_rows]
    total_stock = sum(stock_levels)
    n_days = max(len(days), 1)
    daily_qty = qty / n_days if n_days else 0
    stock_cover_days = round(total_stock / daily_qty, 1) if daily_qty else 0
    stock_rotation = round(qty / total_stock, 2) if total_stock else 0
    rupture_pct = round(sum(1 for x in stock_levels if x <= 0) / max(len(stock_levels), 1) * 100, 1) if stock_levels else 0

    n_ventes = max(len(ventes), 1)
    data_quality = round(
        (n_ok_region + n_ok_prod + n_ok_amt + n_ok_date) / (4 * n_ventes) * 100,
        1,
    )
    n_ord = max(len(orders), 1)
    panier_moyen = round(ca / n_ord)
    multi_pct = round(
        sum(1 for sk in order_skus.values() if len({x for x in sk if x is not None}) > 1) / n_ord * 100,
        1,
    )
    abandon_pct = round((1 - purch / carts) * 100, 1) if carts else 0
    clv = round(ca / max(len(buyers), 1))
    ca_vip_share = round(ca_vip_total / ca * 100, 1) if ca else 0

    margin_pct = round(profit / ca * 100, 1) if ca else 0
    last_m = months[-1] if months else None
    prev_m = months[-2] if len(months) > 1 else None

    def _delta(now: float, prev: float) -> float:
        if not prev:
            return 0.0
        return round((now - prev) / abs(prev) * 100, 1)

    cats = []
    last_cat = by_cat_month.get(last_m, {})
    prev_cat = by_cat_month.get(prev_m, {})
    for name, value in by_cat.items():
        cats.append(
            {
                "name": name,
                "value": round(value),
                "delta": _delta(last_cat.get(name, 0), prev_cat.get(name, 0)),
            }
        )
    cats = sorted(cats, key=lambda x: -x["value"])

    return {
        "source": source,
        "kpis": {
            "ca": round(ca),
            "profit": round(profit),
            "margin_pct": margin_pct,
            "commandes": len(orders),
            "clients": n_clients_filtres,
            "clients_uniques": n_clients_uniques,
            "acheteurs": len(buyers),
            "qty": qty,
            "visitors": views,
            "arpu": round(arpu),
            "conversion": round(conv, 2),
            "promo_share": round(promo_ca / ca * 100, 1) if ca else 0,
            "produits": n_produits_filtres,
            "promos": n_promos_utilisees,
            "ca_delta": _delta(by_month.get(last_m, 0), by_month.get(prev_m, 0)),
            "orders_delta": _delta(len(by_month_orders.get(last_m, ())), len(by_month_orders.get(prev_m, ()))),
            "qty_delta": _delta(by_qty.get(last_m, 0), by_qty.get(prev_m, 0)),
            "visitors_delta": 0,
            "margin_delta": 0,
            "panier_moyen": panier_moyen,
            "abandon_pct": abandon_pct,
            "multi_pct": multi_pct,
            "clv": clv,
            "ca_vip_share": ca_vip_share,
            "clients_vip": n_clients_vip,
            "clients_loyal": n_clients_loyal,
            "clients_inactif": n_clients_inactif,
            "clients_churn": n_clients_churn,
            "freq_vip_moy": freq_vip_moy,
            "ca_vip_total": ca_vip_total,
            "stock_rotation": stock_rotation,
            "stock_cover_days": stock_cover_days,
            "rupture_pct": rupture_pct,
            "data_quality": data_quality,
        },
        "timeseries": {
            "labels": months,
            "values": [round(by_month[m]) for m in months],
            "qty": [round(by_qty.get(m, 0)) for m in months],
            "daily": {
                "labels": days,
                "values": [round(by_day[d]) for d in days],
                "qty": [round(by_day_qty.get(d, 0)) for d in days],
            },
        },
        "categories": cats,
        "regions": sorted(
            [{"name": k, "value": round(v)} for k, v in by_region.items()],
            key=lambda x: -x["value"],
        )[:8],
        "segments": [
            {"name": k, "value": round(by_seg_ca.get(k, 0)), "clients": v}
            for k, v in by_seg.items()
        ],
        "funnel": {"view": views, "add_to_cart": carts, "purchase": purch},
        "devices": [{"name": k, "value": v} for k, v in devices.items() if v],
        "traffic": [{"name": k.replace("_", " "), "value": v} for k, v in traffic.items() if v],
        "recent": recent_out,
        "produits_detail": produits_detail,
        "clients_detail": clients_detail,
        "stock_detail": stock_detail,
        "stock_alert": stock_alert,
        "models": MODELS,
        "activity": ACTIVITY,
        "fiche": build_fiche(
            {
                "margin_pct": margin_pct,
                "ca": round(ca),
                "panier_moyen": panier_moyen,
                "conversion": round(conv, 2),
                "abandon_pct": abandon_pct,
                "multi_pct": multi_pct,
                "clv": clv,
                "ca_vip_share": ca_vip_share,
                "stock_rotation": stock_rotation,
                "stock_cover_days": stock_cover_days,
                "rupture_pct": rupture_pct,
                "data_quality": data_quality,
            }
        ),
    }


def _load_warehouse_demo() -> dict[str, Any]:
    rng = random.Random(42)
    cats = ["Électronique", "Mode", "Maison", "Beauté", "Alimentaire", "Sport", "Enfant", "High-tech"]
    marques = ["Wave", "Teranga", "Sahel", "Dakar+", "Neo", "Pulse"]
    regions = ["Dakar", "Thiès", "Saint-Louis", "Ziguinchor", "Kaolack", "Non renseigné"]
    segments = ["nouveau", "occasionnel", "regulier", "vip"]
    ages = ["18-24", "25-34", "35-44", "45+"]
    names = ["Écouteurs Wave", "Boubou prestige", "Mixeur Sahel", "Crème karité", "Ballon Dakar", "Chargeur 65W"]

    produits = [
        {
            "produit_key": i + 1,
            "product_id": f"P{i + 1}",
            "product_name": names[i % len(names)],
            "categorie": cats[i % len(cats)],
            "marque": marques[i % len(marques)],
            "prix_base_xof": rng.randint(8_000, 220_000),
            "cout_xof": rng.randint(4_000, 160_000),
        }
        for i in range(80)
    ]
    clients = [
        {
            "client_key": i + 1,
            "region": regions[i % len(regions)],
            "age_bracket": ages[i % len(ages)],
            "segment_fidelite": segments[i % len(segments)],
            "is_current": True,
        }
        for i in range(500)
    ]
    dates = []
    d0 = date(2023, 1, 1)
    for i in range(1100):
        dd = d0 + timedelta(days=i)
        dates.append(
            {
                "date_key": dd.strftime("%Y%m%d"),
                "date_complete": dd.isoformat(),
                "annee": dd.year,
                "mois": dd.month,
                "jour_semaine": dd.strftime("%A"),
                "est_weekend": dd.weekday() >= 5,
            }
        )
    ventes = []
    # Churn : uniquement des achats il y a ≥ 2 ans
    churn_demo_keys = {c["client_key"] for i, c in enumerate(clients) if i % 8 == 0}
    # VIP comportement : achats très fréquents
    vip_demo_keys = {c["client_key"] for i, c in enumerate(clients) if i % 8 == 1}
    old_hi = max(0, len(dates) - 800)  # zone « ≥ 2 ans » avant la fin
    for i in range(6000):
        prod = produits[rng.randint(0, len(produits) - 1)]
        cli = clients[rng.randint(0, len(clients) - 1)]
        ck = cli["client_key"]
        if ck in churn_demo_keys:
            dd = dates[rng.randint(0, max(0, old_hi))]
        elif ck in vip_demo_keys:
            dd = dates[rng.randint(max(0, len(dates) - 120), len(dates) - 1)]
        elif rng.random() < 0.15:
            dd = dates[rng.randint(0, max(0, len(dates) // 2))]
        else:
            dd = dates[rng.randint(max(0, len(dates) - 300), len(dates) - 1)]
        ventes.append(
            {
                "vente_id": i + 1,
                "produit_key": prod["produit_key"],
                "client_key": ck,
                "date_key": dd["date_key"],
                "promo_key": rng.randint(1, 40) if rng.random() < 0.18 else None,
                "quantite": rng.randint(1, 3),
                "montant_net_xof": rng.randint(8_000, 250_000),
                "order_id": f"ORD-{12000 + i // 2}",
                "statut_commande": "confirmee" if rng.random() > 0.06 else "annulee",
            }
        )
    # Densifier les VIP : beaucoup de petites commandes récentes
    for j, ck in enumerate(vip_demo_keys):
        for k in range(18):
            dd = dates[max(0, len(dates) - 1 - k * 5)]
            ventes.append(
                {
                    "vente_id": 50_000 + j * 20 + k,
                    "produit_key": produits[(j + k) % len(produits)]["produit_key"],
                    "client_key": ck,
                    "date_key": dd["date_key"],
                    "promo_key": None,
                    "quantite": 1,
                    "montant_net_xof": rng.randint(5_000, 40_000),
                    "order_id": f"ORD-VIP-{j}-{k}",
                    "statut_commande": "confirmee",
                }
            )
    last_key = dates[-1]["date_key"]
    stock_rows = [
        {"produit_key": p["produit_key"], "date_key": last_key, "niveau_stock": rng.randint(0, 120)}
        for p in produits
    ]
    return {
        "source": "demo",
        "backend": "demo",
        "empty": False,
        "produits": produits,
        "clients": clients,
        "dates": dates,
        "promos": [{"promo_key": i} for i in range(1, 41)],
        "ventes": ventes,
        "stock_rows": stock_rows,
        "funnel": {"view": 412_000, "add_to_cart": 86_400, "purchase": 19_870},
        "devices": {"mobile": 248_000, "desktop": 96_000, "tablet": 30_000},
        "traffic": {
            "organic_search": 120_000,
            "social_media": 88_000,
            "direct": 76_000,
            "paid_ads": 54_000,
            "email_campaign": 28_000,
            "affiliate": 18_000,
        },
    }


def load_demo() -> dict[str, Any]:
    return _assemble_from_warehouse(_load_warehouse_demo(), {})


_warehouse: dict[str, Any] | None = None
_load_errors: list[str] = []
_payload_cache: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
_PAYLOAD_CACHE_MAX = 48
EXPORT_LIGNES_MAX = 20_000


def ensure_warehouse(force: bool = False) -> dict[str, Any]:
    global _warehouse, _load_errors, _payload_cache
    if _warehouse and not force:
        return _warehouse
    _load_errors = []
    _payload_cache = {}
    if postgres_configured():
        try:
            wh = _load_warehouse_postgres()
            if wh.get("ventes"):
                _ensure_vente_indexes(wh)
                _filter_options_cached(wh)
                _warehouse = wh
                return _warehouse
            _load_errors.append("Postgres joignable mais 0 vente")
        except Exception as exc:  # noqa: BLE001
            _load_errors.append(f"Postgres: {exc}")
    if supabase_configured():
        try:
            wh = _load_warehouse_live()
            if not wh.get("empty"):
                _ensure_vente_indexes(wh)
                _filter_options_cached(wh)
                _warehouse = wh
                return _warehouse
            _load_errors.append("API REST: 0 ligne (RLS)")
        except Exception as exc:  # noqa: BLE001
            _load_errors.append(str(exc))
    _warehouse = _load_warehouse_demo()
    _ensure_vente_indexes(_warehouse)
    _filter_options_cached(_warehouse)
    return _warehouse


def build_export_lignes(
    filters: dict[str, str] | None = None,
    limit: int = EXPORT_LIGNES_MAX,
) -> tuple[list[dict[str, Any]], int]:
    wh = ensure_warehouse()
    parsed = parse_filters(filters)
    ventes = filter_ventes(wh, parsed)
    total = len(ventes)
    produits = wh.get("produits") or []
    clients = wh.get("clients") or []
    dates = wh.get("dates") or []
    pmap = {p.get("produit_key"): p for p in produits}
    cmap = {c.get("client_key"): c for c in clients}
    dmap = {str(d.get("date_key")): d for d in dates}
    cap = min(max(1, limit), total) if limit else total
    rows = [_row_from_vente(v, pmap, cmap, dmap) for v in ventes[:cap]]
    return rows, total


def get_payload(filters: dict[str, str] | None = None, force: bool = False) -> dict[str, Any]:
    wh = ensure_warehouse(force=force)
    parsed = parse_filters(filters)
    cache_key = tuple(sorted(parsed.items()))
    if not force and cache_key in _payload_cache:
        cached = dict(_payload_cache[cache_key])
        cached["empty"] = wh.get("empty", False)
        if wh.get("source") == "demo" and _load_errors:
            cached["error"] = " | ".join(_load_errors)
        return cached
    payload = _assemble_from_warehouse(wh, parsed)
    payload["empty"] = wh.get("empty", False)
    if wh.get("source") == "demo" and _load_errors:
        payload["error"] = " | ".join(_load_errors)
    if len(_payload_cache) >= _PAYLOAD_CACHE_MAX:
        _payload_cache.pop(next(iter(_payload_cache)))
    _payload_cache[cache_key] = payload
    return payload
