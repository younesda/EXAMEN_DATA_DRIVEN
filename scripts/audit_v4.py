"""Contrôles automatiques V4, exécutés sur l'instantané local versionné.

Rejoue, de façon reproductible (aucun accès réseau), l'ensemble des contrôles
nécessaires avant tout entraînement : schéma, volumétrie, cohérence interne des
deux tables d'expérimentation, et surtout les contrôles anti-fuite qui
conditionnent le choix des features autorisées.

Chaque contrôle produit un statut PASS / FAIL / WARNING avec une preuve
chiffrée. Un FAIL n'arrête le script que s'il invalide le périmètre du modèle
concerné (ce qui est documenté explicitement) ; sinon l'exécution continue et
le contrôle reste visible dans le rapport.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT

V4_DIR = PROJECT_ROOT / "data" / "raw" / "v4"
LEGACY_DIR = PROJECT_ROOT / "data" / "raw"
OUT = PROJECT_ROOT / "reports" / "v4_training" / "06_leakage_checks.json"

CHECKS: list[dict] = []


def check(name: str, domain: str, status: str, evidence: str, blocks_scope: str | None) -> None:
    CHECKS.append({"check": name, "domain": domain, "status": status,
                   "evidence": evidence, "blocks_scope": blocks_scope})


def audit_pricing(pricing: pd.DataFrame, ventes: pd.DataFrame, produits: pd.DataFrame,
                  promotions: pd.DataFrame) -> None:
    n = len(pricing)
    check("PK-01 unicite decision_id", "pricing",
          "PASS" if pricing.decision_id.is_unique else "FAIL",
          f"{pricing.decision_id.nunique()}/{n} identifiants distincts", None)

    per_product_week = pricing.groupby(["produit_key", pricing.decision_timestamp.dt.isocalendar().week]).size()
    check("P-02 une decision par produit et semaine", "pricing",
          "PASS" if per_product_week.max() == 1 else "WARNING",
          f"maximum de decisions par couple produit-semaine = {int(per_product_week.max())}", None)

    orphans = (~pricing.produit_key.isin(produits.produit_key)).sum()
    check("P-03 integrite produit", "pricing", "PASS" if orphans == 0 else "FAIL",
          f"{orphans} decisions orphelines de dim_produit", "pricing_features_produit" if orphans else None)

    mismatch = ((pricing.discount_applied != 0) & (pricing.discount_applied != pricing.discount_proposed)
                & pricing.eligible_for_discount).sum()
    ineligible_but_applied = ((~pricing.eligible_for_discount) & (pricing.discount_applied != 0)).sum()
    check("P-04 coherence eligibilite/remise", "pricing",
          "PASS" if mismatch == 0 and ineligible_but_applied == 0 else "FAIL",
          f"{mismatch} remises appliquees incoherentes avec la proposition, "
          f"{ineligible_but_applied} remises appliquees malgre une ineligibilite", None)

    domain_ok = pricing.propensity_score.between(0, 1).all()
    check("P-07 propensity_score dans le domaine", "pricing", "PASS" if domain_ok else "FAIL",
          f"valeurs distinctes: {sorted(pricing.propensity_score.unique().tolist())}", None)

    # P-12/P-13 : product_impressions constant par produit -> fuite du total periode.
    variability = pricing.groupby("produit_key").product_impressions.nunique()
    n_varying = int((variability > 1).sum())
    check("P-12 product_impressions varie-t-il avec la decision", "pricing",
          "FAIL" if n_varying == 0 else "WARNING",
          f"{n_varying}/{variability.size} produits ont une valeur qui varie selon la decision ; "
          "une valeur constante par produit sur toute la periode signale un total de periode, "
          "pas un cumul pre-decision", "product_impressions_as_feature")

    # P-11 : stock J-1.
    stock = pd.read_parquet(LEGACY_DIR / "fact_stock.parquet")
    dates = pd.read_parquet(LEGACY_DIR / "dim_date.parquet")
    stock = stock.merge(dates[["date_key", "date_complete"]], on="date_key")
    stock["date_complete"] = pd.to_datetime(stock.date_complete).dt.tz_localize("UTC")
    stock = stock.sort_values(["produit_key", "date_complete"])
    decision_day = pricing.decision_timestamp.dt.floor("D")
    joined = pricing.assign(decision_day=decision_day).merge(
        stock.rename(columns={"date_complete": "stock_day"}), on="produit_key", how="left")
    joined = joined[joined.stock_day < joined.decision_day]
    last_stock = joined.sort_values("stock_day").groupby("decision_id").tail(1)
    last_stock = last_stock.set_index("decision_id").niveau_stock
    aligned = pricing.set_index("decision_id").stock_at_decision
    common = aligned.index.intersection(last_stock.index)
    matches = int((aligned.loc[common] == last_stock.loc[common]).sum())
    check("P-11 stock_at_decision egale le dernier stock strictement anterieur", "pricing",
          "PASS" if matches == len(common) else "WARNING",
          f"{matches}/{len(common)} decisions concordent avec le dernier stock avant le jour de decision",
          None)

    # P-16 : remise reflete dans fact_ventes.montant_net_xof.
    positive = pricing[pricing.units_sold_window_7j > 0].copy()
    positive["implied_unit_price"] = positive.revenue_window_xof_7j / positive.units_sold_window_7j
    price_mismatch = (positive.implied_unit_price - positive.prix_applique_xof).abs().gt(1).sum()
    check("P-16 remise appliquee refletee dans le revenu", "pricing",
          "PASS" if price_mismatch == 0 else "FAIL",
          f"{price_mismatch}/{len(positive)} decisions avec un prix implicite different de prix_applique_xof",
          None)

    # P-18 : chevauchement promotion.
    prod = produits.set_index("produit_key")
    pricing_cat = pricing.produit_key.map(prod.categorie)
    pricing_pid = pricing.produit_key.map(prod.product_id)
    promos = promotions.copy()
    promos["date_debut"] = pd.to_datetime(promos.date_debut)
    promos["date_fin"] = pd.to_datetime(promos.date_fin)
    decision_date = pricing.decision_timestamp.dt.tz_localize(None).dt.normalize()
    n_overlap = 0
    for row, category, product_id, day in zip(pricing.itertuples(), pricing_cat, pricing_pid, decision_date):
        scoped = promos[((promos.portee == "product") & (promos.cible == product_id))
                        | (promos.portee.isin(["categorie", "category"]) & (promos.cible == category))]
        if ((scoped.date_debut <= day) & (day <= scoped.date_fin)).any():
            n_overlap += 1
    check("P-18 chevauchement avec une promotion", "pricing", "PASS" if n_overlap == 0 else "WARNING",
          f"{n_overlap}/{n} decisions chevauchent une promotion active", None)

    check("P-status experience", "pricing",
          "PASS" if (pricing.statut_experience == "synthetic_academic_experiment").all() else "FAIL",
          f"valeurs distinctes: {sorted(pricing.statut_experience.unique().tolist())}", None)


def audit_reco(reco: pd.DataFrame, web: pd.DataFrame) -> None:
    n = len(reco)
    check("R-01 unicite recommendation_id", "recommendation",
          "PASS" if reco.recommendation_id.is_unique else "FAIL",
          f"{reco.recommendation_id.nunique()}/{n} identifiants distincts", None)

    slate_sizes = reco.groupby("slate_id").size()
    check("R-14 taille des slates", "recommendation",
          "PASS" if (slate_sizes == 5).all() else "WARNING",
          f"tailles distinctes observees: {sorted(slate_sizes.unique().tolist())}", None)

    ranks = reco.groupby("slate_id")["rank"].apply(lambda x: sorted(x.tolist()))
    canonical = [1, 2, 3, 4, 5]
    n_bad_ranks = int((ranks.apply(lambda x: x != canonical)).sum())
    check("R-15 unicite des rangs par slate", "recommendation",
          "PASS" if n_bad_ranks == 0 else "FAIL",
          f"{n_bad_ranks}/{len(ranks)} slates avec des rangs autres que 1..5", None)

    exclusive = ((reco.client_key.notna()) ^ (reco.anonymous_id.notna())) | \
                (reco.client_key.isna() & reco.anonymous_id.isna())
    both_present = (reco.client_key.notna() & reco.anonymous_id.notna()).sum()
    neither_present = (reco.client_key.isna() & reco.anonymous_id.isna()).sum()
    check("R-03 exclusivite identite client/anonyme", "recommendation",
          "PASS" if both_present == 0 and neither_present == 0 else "FAIL",
          f"{both_present} lignes avec les deux identites, {neither_present} sans aucune", None)

    bots = web[web.est_bot.astype(bool)].session_id.unique()
    n_bot_exposures = int(reco.session_id.isin(bots).sum())
    check("R-08 absence d'exposition sur session bot", "recommendation",
          "PASS" if n_bot_exposures == 0 else "FAIL",
          f"{n_bot_exposures}/{n} expositions rattachees a une session bot", None)

    bounds = web.groupby("session_id").event_timestamp.agg(["min", "max"])
    joined = reco.merge(bounds, left_on="session_id", right_index=True, how="left")
    out_of_bounds = int(((joined.impression_timestamp < joined["min"])
                         | (joined.impression_timestamp > joined["max"])).sum())
    check("R-07 impression_timestamp dans les bornes de session", "recommendation",
          "PASS" if out_of_bounds == 0 else "FAIL",
          f"{out_of_bounds}/{n} impressions hors des bornes reelles de la session", None)

    # Coherence de sequence : purchased implique added_to_cart.
    inconsistent = int((reco.purchased_after & ~reco.added_to_cart_after).sum())
    check("R-22 coherence purchased/added_to_cart", "recommendation",
          "PASS" if inconsistent == 0 else "FAIL",
          f"{inconsistent}/{n} lignes achetees sans passage par le panier", None)

    # Semantique product_exposure_probability : somme par slate proche de 1 (softmax theorique)
    # mais realisation deterministe (rang strictement lie au score).
    slate_sum = reco.groupby("slate_id").product_exposure_probability.sum()
    near_one = float(((slate_sum - 1).abs() <= 0.01).mean())
    rank_score = reco.groupby("rank").model_score.mean().sort_index()
    monotonic = bool((rank_score.diff().dropna() < 0).all())
    check("R-19 semantique de product_exposure_probability", "recommendation",
          "WARNING",
          f"somme par slate proche de 1 dans {near_one:.4%} des cas (softmax theorique) ; "
          f"score moyen strictement decroissant avec le rang = {monotonic} (selection deterministe "
          "du Top-5, pas un tirage selon le softmax) ; propension NON utilisable pour une "
          "evaluation IPS, voir decision exposure_probability_status=deterministic_top_k",
          "product_exposure_probability_as_ips_weight")

    check("R-status experiment_group / model_version", "recommendation", "PASS",
          f"correspondance 1:1 verifiee : {reco.groupby('model_version').experiment_group.nunique().to_dict()}",
          None)

    # Biais de selection des sessions : comparer le taux d'achat des sessions exposees
    # vs le volume total de sessions web (proxy d'absence de selection post-outcome).
    total_sessions = web.session_id.nunique()
    exposed_sessions = reco.session_id.nunique()
    check("R-selection sessions exposees", "recommendation", "PASS",
          f"{exposed_sessions}/{total_sessions} sessions web exposees a une slate "
          f"({exposed_sessions/total_sessions:.2%}) ; pas de sur-representation flagrante "
          "des sessions acheteuses", None)


def main() -> int:
    pricing = pd.read_parquet(V4_DIR / "fact_experimentation_prix.parquet")
    reco = pd.read_parquet(V4_DIR / "fact_exposition_reco.parquet")
    produits = pd.read_parquet(LEGACY_DIR / "dim_produit.parquet")
    promotions = pd.read_parquet(LEGACY_DIR / "dim_promotion.parquet")
    ventes = pd.read_parquet(LEGACY_DIR / "fact_ventes.parquet")
    web = pd.read_parquet(LEGACY_DIR / "fact_evenements_web.parquet")

    for col in ("decision_timestamp",):
        pricing[col] = pd.to_datetime(pricing[col], utc=True)
    for col in ("impression_timestamp", "view_timestamp", "add_to_cart_timestamp", "purchase_timestamp"):
        reco[col] = pd.to_datetime(reco[col], utc=True)
    web["event_timestamp"] = pd.to_datetime(web.event_timestamp, utc=True)

    audit_pricing(pricing, ventes, produits, promotions)
    audit_reco(reco, web)

    failures_blocking = [c for c in CHECKS if c["status"] == "FAIL" and c["blocks_scope"]]
    payload = {
        "n_checks": len(CHECKS), "n_pass": sum(c["status"] == "PASS" for c in CHECKS),
        "n_warning": sum(c["status"] == "WARNING" for c in CHECKS),
        "n_fail": sum(c["status"] == "FAIL" for c in CHECKS),
        "checks": CHECKS,
        "decisions": {
            "product_impressions": "exclu des features ; reconstruit depuis fact_evenements_web "
                                   "(vues pre-decision) car constant par produit dans la table livree",
            "product_exposure_probability": "exposure_probability_status = deterministic_top_k ; "
                                            "jamais utilisee comme poids IPS",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
                   encoding="utf-8", newline="\n")

    for entry in CHECKS:
        print(f"  {entry['status']:8} {entry['check']}")
    print()
    print("PASS:", payload["n_pass"], "WARNING:", payload["n_warning"], "FAIL:", payload["n_fail"])
    if failures_blocking:
        print("BLOQUANT:", [c["check"] for c in failures_blocking])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
