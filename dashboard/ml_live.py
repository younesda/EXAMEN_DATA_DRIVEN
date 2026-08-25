"""API modèles V4 (Render) — lecture seule pour la page métier Modèles."""
from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

BASE = "https://examen-data-driven-v4.onrender.com"
TIMEOUT = 60
CACHE_TTL = 300

_cache: dict[str, Any] | None = None
_cache_at = 0.0


def _get(path: str) -> dict[str, Any]:
    r = requests.get(f"{BASE}{path}", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _pct(x: Any) -> float | None:
    if x is None:
        return None
    v = float(x)
    return round(v * 100, 2) if abs(v) <= 1.5 else round(v, 2)


def _fetch_all() -> tuple[dict[str, Any], list[str]]:
    """Charge les endpoints en parallèle (beaucoup plus rapide au cold start Render)."""
    paths = [
        "/forecast",
        "/metrics",
        "/forecast/produits",
        "/pricing/produits",
        "/recommendations/produits",
        "/metadata",
    ]
    out: dict[str, Any] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_get, p): p for p in paths}
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                out[path] = fut.result()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {exc}")
                out[path] = {}
    return out, errors


def fetch_models_live(force: bool = False) -> dict[str, Any]:
    global _cache, _cache_at
    now = time.time()
    if (
        not force
        and _cache
        and (now - _cache_at) < CACHE_TTL
        and (_cache.get("tables") or {}).get("forecast")
    ):
        return _cache

    raw, errors = _fetch_all()
    forecast_meta = raw.get("/forecast") or {}
    metrics = raw.get("/metrics") or {}
    forecast_pack = raw.get("/forecast/produits") or {}
    pricing_pack = raw.get("/pricing/produits") or {}
    reco_pack = raw.get("/recommendations/produits") or {}
    meta = raw.get("/metadata") or {}

    fc = metrics.get("forecasting") or {}
    horizons = fc.get("horizons") or {}
    windows = ((fc.get("windows") or {}).get("detail") or [])[:6]

    wape_quotidien = _pct((horizons.get("quotidien") or {}).get("wape"))
    wape_7 = _pct((horizons.get("cumule_7j") or {}).get("wape"))
    wape_30 = _pct(
        (horizons.get("cumule_30j") or {}).get("wape")
        or fc.get("wape30_micro")
        or (forecast_meta.get("metriques") or {}).get("wape_cumulee_30j")
    )
    bias = _pct(fc.get("forecast_bias_macro") or (forecast_meta.get("metriques") or {}).get("forecast_bias_macro"))

    pricing_rows = pricing_pack.get("produits") or []
    abc = Counter(str(r.get("classe_abc") or "?") for r in pricing_rows)
    marges = [float(r.get("taux_marge_prix_catalogue") or 0) * 100 for r in pricing_rows]
    marge_moy = round(sum(marges) / len(marges), 1) if marges else None
    volume_nul = sum(1 for r in pricing_rows if r.get("volume_nul"))

    reco_rows = reco_pack.get("produits") or []
    reco_sorted = sorted(reco_rows, key=lambda x: float(x.get("popularite_globale") or 0), reverse=True)

    fc_rows = forecast_pack.get("produits") or []
    fc_by_gap = sorted(fc_rows, key=lambda x: float(x.get("ecart_absolu_30j") or 0), reverse=True)
    fc_top = fc_by_gap[:12]

    by_cat_reel: dict[str, float] = {}
    by_cat_prev: dict[str, float] = {}
    for r in fc_rows:
        cat = r.get("categorie") or "Autre"
        by_cat_reel[cat] = by_cat_reel.get(cat, 0) + float(r.get("total_reel_30j") or 0)
        by_cat_prev[cat] = by_cat_prev.get(cat, 0) + float(r.get("total_prevu_30j") or 0)
    cats = sorted(by_cat_reel.keys(), key=lambda c: -by_cat_reel[c])

    win_labels = [f"F{w.get('fenetre')}" for w in windows]
    win_wape30 = [_pct(w.get("wape_cumulee_30j")) or 0 for w in windows]
    win_wape7 = [_pct(w.get("wape_cumulee_7j")) or 0 for w in windows]

    pricing_block = metrics.get("pricing") or {}
    pricing_targets = pricing_block.get("targets") or {}
    pricing_rows_score = []
    target_labels = {
        "units_sold_window_7j": "Unités (7 j)",
        "revenue_window_xof_7j": "CA (7 j)",
        "margin_window_xof_7j": "Marge (7 j)",
    }
    for tid, label in target_labels.items():
        t = pricing_targets.get(tid) or {}
        if not t:
            continue
        pricing_rows_score.append({
            "cible": label,
            "target_id": tid,
            "wape_macro": _pct(t.get("wape_macro")),
            "wape_micro": _pct(t.get("wape_micro_pooled")),
            "biais": _pct(t.get("bias_macro")),
            "statut": t.get("status") or "—",
        })
    pricing_wape = pricing_rows_score[0]["wape_micro"] if pricing_rows_score else None

    ROLE_FR = {
        "purchased_after": "Achat",
        "added_to_cart_after": "Ajout au panier",
        "viewed_after_impression": "Consultation",
    }
    reco_roles = []
    reco_recall = None
    reco_coverage = None
    default_gain = None
    for m in meta.get("models") or []:
        if m.get("domain") != "recommendation":
            continue
        met = m.get("metrics") or {}
        target = m.get("target") or ""
        if "recall@10" in met and reco_recall is None and m.get("status") != "exploratory":
            reco_recall = _pct(met.get("recall@10"))
            reco_coverage = _pct(met.get("coverage_catalogue"))
        if target in ROLE_FR:
            gain = _pct(met.get("relative_ndcg_gain"))
            statut = m.get("status") or "—"
            is_default = statut == "validated_academic"
            if is_default and default_gain is None:
                default_gain = gain
            reco_roles.append({
                "role": ROLE_FR[target],
                "cible": target,
                "modele": m.get("model_name"),
                "gain_ndcg10": gain,
                "p_holm": met.get("p_value_holm_independante"),
                "statut": "Validé pour le site" if is_default else ("En test" if statut == "exploratory" else statut),
                "par_defaut": "oui" if is_default else "non",
                "repli": "Best-sellers",
            })

    win_detail = []
    for w in windows:
        win_detail.append({
            "fenetre": w.get("fenetre"),
            "debut": w.get("debut"),
            "wape_day": _pct(w.get("wape_quotidienne")),
            "wape_7": _pct(w.get("wape_cumulee_7j")),
            "wape_30": _pct(w.get("wape_cumulee_30j")),
            "biais": _pct(w.get("biais")),
        })

    wape30_micro = _pct(fc.get("wape30_micro") or (forecast_meta.get("metriques") or {}).get("wape30_micro"))
    daily_ops = fc.get("daily_model_metrics") or {}
    win_meta = fc.get("windows") or {}

    cards = [
        {
            "id": "forecast",
            "name": "Prévision des ventes",
            "subtitle": "Combien commander sur 7 et 30 jours",
            "status": "Prêt pour la planification",
            "status_tone": "ok",
            "metric_label": "Erreur moyenne à 30 jours",
            "metric_value": wape_30,
            "metric_unit": "%",
            "usage": "Estimer les volumes pour le stock et les commandes fournisseurs.",
            "interdit": "Ce n’est pas un score de réussite. L’écart jour par jour reste souvent élevé.",
            "note": "Plus l’erreur est basse, plus la prévision est utile pour commander.",
        },
        {
            "id": "pricing",
            "name": "Simulation des prix",
            "subtitle": "Scénarios prix / marge avant une promo",
            "status": "Simulation — aucun prix modifié en magasin",
            "status_tone": "warn",
            "metric_label": "Écart volume à 7 jours",
            "metric_value": pricing_wape,
            "metric_unit": "%",
            "usage": "Comparer volume, CA et marge pour préparer une décision prix.",
            "interdit": "Rien n’est appliqué automatiquement. Une baisse de prix ne garantit pas plus de ventes.",
            "note": "CA et marge affichés sont calculés à partir du volume et du prix simulés.",
        },
        {
            "id": "reco",
            "name": "Mise en avant produits",
            "subtitle": "Mieux ordonner les produits à pousser",
            "status": "Listes validées · sinon best-sellers",
            "status_tone": "info",
            "metric_label": "Gain d’ordre (achat)",
            "metric_value": default_gain,
            "metric_unit": "%",
            "usage": "Réordonner une vitrine ou une liste courte pour mieux coller aux achats.",
            "interdit": "Une piste encore en test n’est jamais proposée seule sur le site.",
            "note": "Le gain dit si l’ordre de la liste est meilleur, pas un taux de « bonnes » réponses.",
        },
    ]

    payload = {
        "live": True,
        "source": BASE,
        "errors": errors,
        "ok": bool(fc_rows or pricing_rows or reco_rows or reco_roles or pricing_rows_score),
        "service": {
            "name": meta.get("service") or "api_v4",
            "commit": meta.get("deployed_commit"),
            "statut_donnees": metrics.get("statut_donnees") or meta.get("status") or "synthetic_academic_experiment",
            "docs": f"{BASE}/docs",
            "metrics_url": f"{BASE}/metrics",
            "metadata_url": f"{BASE}/metadata",
        },
        "cards": cards,
        "validation": {
            "forecast": {
                "wape30_micro": wape30_micro,
                "wape_day": wape_quotidien,
                "wape_7": wape_7,
                "wape_30": wape_30,
                "biais": bias,
                "planning_model": fc.get("planning_model") or forecast_meta.get("modele_planification_30j"),
                "daily_model": fc.get("daily_model") or forecast_meta.get("modele_quotidien"),
                "daily_ops": {
                    "wape_day": _pct(daily_ops.get("wape_quotidienne")),
                    "wape_30": _pct(daily_ops.get("wape_cumulee_30j")),
                    "biais": _pct(daily_ops.get("biais")),
                },
                "fenetres": {
                    "evaluees": win_meta.get("evaluated"),
                    "victoires_planif": win_meta.get("won_planning_30d"),
                    "victoires_quotidien": win_meta.get("won_daily"),
                    "horizons": fc.get("horizons_evaluated") or 30,
                },
                "windows": win_detail,
                "note": fc.get("note"),
            },
            "pricing": {
                "modele": "Médiane par produit",
                "statut": "Simulation",
                "causal": bool(pricing_block.get("causal_effect_estimated")),
                "auto_price": bool(pricing_block.get("automatic_optimal_price")),
                "targets": pricing_rows_score,
                "note": "Simulation uniquement — validation humaine obligatoire.",
            },
            "recommendation": {
                "roles": reco_roles,
                "repli": "Best-sellers",
                "note": "Le gain mesure un meilleur ordre de liste. Sinon on affiche les best-sellers.",
            },
        },
        "kpis": {
            "wape_30": wape_30,
            "wape_7": wape_7,
            "wape_day": wape_quotidien,
            "wape30_micro": wape30_micro,
            "bias": bias,
            "pricing_wape": pricing_wape,
            "marge_moyenne": marge_moy,
            "n_forecast": forecast_pack.get("n_produits") or len(fc_rows),
            "n_pricing": pricing_pack.get("n_produits") or len(pricing_rows),
            "n_reco": reco_pack.get("n_produits") or len(reco_rows),
            "recall10": reco_recall,
            "coverage": reco_coverage,
            "ndcg_gain_achat": default_gain,
        },
        "charts": {
            "precision_horizons": {
                "labels": ["Au jour", "Sur 7 jours", "Sur 30 jours"],
                "values": [wape_quotidien or 0, wape_7 or 0, wape_30 or 0],
                "hint": "WAPE = erreur relative pondérée (plus bas = mieux). Pas une exactitude.",
            },
            "fenetres": {
                "labels": win_labels,
                "wape_30": win_wape30,
                "wape_7": win_wape7,
            },
            "reel_vs_prevu_cat": {
                "labels": cats,
                "reel": [round(by_cat_reel[c], 1) for c in cats],
                "prevu": [round(by_cat_prev[c], 1) for c in cats],
            },
            "abc": {
                "labels": [f"Classe {k}" for k, _ in sorted(abc.items())],
                "values": [v for _, v in sorted(abc.items())],
            },
            "populaires": {
                "labels": [(r.get("produit_key") or "")[-6:] or "?" for r in reco_sorted[:10]],
                "names": [r.get("produit_key") for r in reco_sorted[:10]],
                "values": [float(r.get("popularite_globale") or 0) for r in reco_sorted[:10]],
                "recent": [float(r.get("popularite_recente_28j") or 0) for r in reco_sorted[:10]],
            },
            "ecarts_produits": {
                "labels": [(r.get("nom") or r.get("produit_key") or "")[:22] for r in fc_top[:8]],
                "reel": [float(r.get("total_reel_30j") or 0) for r in fc_top[:8]],
                "prevu": [float(r.get("total_prevu_30j") or 0) for r in fc_top[:8]],
            },
            "pricing_targets": {
                "labels": [r["cible"] for r in pricing_rows_score],
                "wape_micro": [r["wape_micro"] or 0 for r in pricing_rows_score],
                "wape_macro": [r["wape_macro"] or 0 for r in pricing_rows_score],
            },
            "reco_gains": {
                "labels": [r["role"] for r in reco_roles],
                "values": [r["gain_ndcg10"] or 0 for r in reco_roles],
                "default": [r["par_defaut"] == "oui" for r in reco_roles],
            },
        },
        "tables": {
            "forecast": [
                {
                    "produit": r.get("nom") or r.get("produit_key"),
                    "categorie": r.get("categorie"),
                    "reel": r.get("total_reel_30j"),
                    "prevu": r.get("total_prevu_30j"),
                    "ecart": r.get("ecart_absolu_30j"),
                }
                for r in fc_by_gap[:30]
            ],
            "forecast_windows": win_detail,
            "pricing": [
                {
                    "produit": r.get("produit_key"),
                    "categorie": r.get("categorie"),
                    "classe": r.get("classe_abc"),
                    "prix": r.get("prix_catalogue_xof"),
                    "marge_pct": round(float(r.get("taux_marge_prix_catalogue") or 0) * 100, 1),
                    "volume_nul": bool(r.get("volume_nul")),
                }
                for r in sorted(
                    pricing_rows, key=lambda x: float(x.get("prix_catalogue_xof") or 0), reverse=True
                )[:30]
            ],
            "pricing_scores": pricing_rows_score,
            "reco": [
                {
                    "rang": r.get("rang_popularite_globale"),
                    "produit": r.get("produit_key"),
                    "categorie": r.get("categorie"),
                    "pop": r.get("popularite_globale"),
                    "pop_28j": r.get("popularite_recente_28j"),
                    "prix": r.get("prix_base_xof"),
                }
                for r in reco_sorted[:30]
            ],
            "reco_roles": reco_roles,
        },
        "stats": {
            "volume_nul_pricing": volume_nul,
            "abc": dict(abc),
        },
    }

    # Ne jamais mettre en cache une réponse vide (évite l’écran « indisponible »)
    if payload["ok"]:
        _cache = payload
        _cache_at = now
    return payload
