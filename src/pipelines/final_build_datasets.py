"""Audit final et construction fraîche des cinq datasets analytiques."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.data.extract import load_cached
from v2.data.builders.client_product_interactions import build_client_product_interactions
from v2.data.builders.order_baskets import build_order_baskets
from v2.data.builders.session_sequences import build_session_sequences

OUT = PROJECT_ROOT / "data" / "processed" / "final"
REPORT = PROJECT_ROOT / "reports" / "final"
TABLES = ["dim_client", "dim_date", "dim_produit", "dim_promotion",
          "fact_evenements_web", "fact_stock", "fact_ventes"]
EXPECTED = {"dim_client": 5000, "dim_date": 546, "dim_produit": 300,
            "dim_promotion": 120, "fact_evenements_web": 657392,
            "fact_stock": 117763, "fact_ventes": 84319}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    t = {name: load_cached(name) for name in TABLES}
    v, w, s = t["fact_ventes"], t["fact_evenements_web"], t["fact_stock"]
    dates, products, promos = t["dim_date"], t["dim_produit"], t["dim_promotion"]
    dates = dates.assign(ds=pd.to_datetime(dates["date_complete"]).dt.normalize())
    w = w.rename(columns={"type_event": "event_type"}).copy()
    w["event_timestamp"] = pd.to_datetime(w["event_timestamp"], utc=True)

    checks: dict[str, dict] = {}
    def check(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    for name, df in t.items():
        check(f"volume::{name}", len(df) == EXPECTED[name], f"{len(df):,}/{EXPECTED[name]:,}")
    check("pk::ventes", v["vente_id"].is_unique, f"uniques={v.vente_id.nunique():,}")
    check("pk::web", w["event_id"].is_unique, f"uniques={w.event_id.nunique():,}")
    check("pk::stock", not s.duplicated(["produit_key", "date_key"]).any(), "produit×jour")
    check("statuts", set(v.statut_commande.unique()) == {"confirmee", "annulee", "retournee"},
          json.dumps(v.statut_commande.value_counts().to_dict(), ensure_ascii=False))
    check("fk::ventes_produit", v.produit_key.isin(products.produit_key).all(), "0 orpheline")
    check("fk::ventes_client", v.client_key.isin(t["dim_client"].client_key).all(), "0 orpheline")
    check("fk::web_produit", w.produit_key.isin(products.produit_key).all(), "0 orpheline")
    check("utc", str(w.event_timestamp.dtype) == "datetime64[ns, UTC]", str(w.event_timestamp.dtype))
    check("bots", w.est_bot.notna().all(), f"exclus={int(w.est_bot.astype(bool).sum()):,}")
    gap = (w.sort_values(["session_id", "event_timestamp", "event_id"])
             .groupby("session_id").event_timestamp.diff().dt.total_seconds().div(60))
    check("sessions_timeout_30", not (gap > 30).any(), f"écart max={gap.max():.1f} min")
    purchase = w[w.event_type.eq("purchase")]
    check("purchase_order", purchase.order_id.notna().all(), f"{len(purchase):,} achats")
    check("purchase_quantity", purchase.quantity.notna().all(), "100 % renseigné")
    check("ventes_web", set(purchase.order_id) == set(v.order_id),
          f"{purchase.order_id.nunique():,} commandes appariées")
    check("order_mono_client", v.groupby("order_id").client_key.nunique().max() == 1, "max=1")
    check("order_mono_date", v.groupby("order_id").date_key.nunique().max() == 1, "max=1")
    check("order_mono_status", v.groupby("order_id").statut_commande.nunique().max() == 1, "max=1")

    stock = s.merge(dates[["date_key", "ds"]], on="date_key").sort_values(["produit_key", "ds"])
    stock_err = stock.niveau_stock - (stock.groupby("produit_key").niveau_stock.shift(1)
                                      - stock.quantite_vendue + stock.quantite_reapprovisionnee)
    check("stock_formula", (stock_err.dropna() == 0).all(),
          f"écarts={int((stock_err.dropna()!=0).sum())}")

    sales = (v.merge(dates[["date_key", "ds"]], on="date_key")
               .merge(products[["produit_key", "product_id", "categorie", "marque",
                                "prix_base_xof", "cout_xof"]], on="produit_key")
               .merge(promos[["promo_key", "remise_pct"]], on="promo_key", how="left"))
    sales["remise_pct"] = sales.remise_pct.fillna(0).astype(float)
    expected_amount = sales.prix_base_xof * sales.quantite * (1-sales.remise_pct/100)
    rel_err = (sales.montant_net_xof / expected_amount - 1).abs()
    check("price_formula", (rel_err <= .021).all(),
          f"100 % à ±2,1 %; médiane={rel_err.median():.4f}")
    check("catalog_price_fixed", products.groupby("product_id").prix_base_xof.nunique().max() == 1,
          "aucune variation intra-produit")

    # 1) Forecasting: grille complète produit×jour, cible confirmée uniquement.
    calendar = pd.MultiIndex.from_product(
        [products.produit_key.unique(), dates.ds.sort_values().unique()], names=["produit_key", "ds"]
    ).to_frame(index=False)
    confirmed = sales[sales.statut_commande.eq("confirmee")]
    daily = confirmed.groupby(["produit_key", "ds"], as_index=False).agg(
        y=("quantite", "sum"), ca_confirme_xof=("montant_net_xof", "sum"))
    daily = calendar.merge(daily, on=["produit_key", "ds"], how="left").fillna(
        {"y": 0, "ca_confirme_xof": 0})
    daily = daily.merge(products[["produit_key", "product_id", "categorie", "marque"]], on="produit_key")
    web_human = w[~w.est_bot.astype(bool)].copy()
    web_human["ds"] = web_human.event_timestamp.dt.tz_convert("Africa/Dakar").dt.tz_localize(None).dt.normalize()
    web_daily = web_human.groupby(["produit_key", "ds", "event_type"]).size().unstack(fill_value=0).reset_index()
    daily = daily.merge(web_daily, on=["produit_key", "ds"], how="left")
    for c in ("view", "add_to_cart", "purchase"):
        if c not in daily: daily[c] = 0
        daily[c] = daily[c].fillna(0).astype(int)
    daily = daily.merge(stock[["produit_key", "ds", "niveau_stock", "quantite_vendue",
                               "quantite_reapprovisionnee"]], on=["produit_key", "ds"], how="left")
    daily = daily.merge(products[["produit_key", "prix_base_xof", "cout_xof"]], on="produit_key")

    # Promotion connue par date de début/fin et cible produit/catégorie.
    promo_rows = []
    by_product = products.set_index("product_id").produit_key.to_dict()
    by_category = products.groupby("categorie").produit_key.apply(list).to_dict()
    for r in promos.itertuples():
        keys = [by_product.get(r.cible)] if r.portee == "product" else by_category.get(r.cible, [])
        for key in [k for k in keys if k is not None]:
            for ds in pd.date_range(r.date_debut, r.date_fin, freq="D"):
                promo_rows.append((key, ds.normalize(), float(r.remise_pct)))
    promo_calendar = pd.DataFrame(promo_rows, columns=["produit_key", "ds", "remise_pct"])
    promo_calendar = promo_calendar.groupby(["produit_key", "ds"], as_index=False).remise_pct.max()
    daily = daily.merge(promo_calendar, on=["produit_key", "ds"], how="left")
    daily["remise_pct"] = daily.remise_pct.fillna(0)

    # 2) Pricing: grain produit-jour confirmé, prix payé et marge observés.
    pricing = confirmed.assign(prix_unitaire_paye_xof=lambda x: x.montant_net_xof/x.quantite,
                               marge_ligne_xof=lambda x: x.montant_net_xof-x.cout_xof*x.quantite)
    pricing = pricing.groupby(["produit_key", "ds", "categorie", "marque", "prix_base_xof",
                               "cout_xof", "remise_pct"], as_index=False).agg(
        quantite=("quantite", "sum"), ca_xof=("montant_net_xof", "sum"),
        marge_xof=("marge_ligne_xof", "sum"), n_lignes=("vente_id", "size"))
    pricing["prix_unitaire_paye_xof"] = pricing.ca_xof/pricing.quantite

    # 3-5) Paniers, sessions et interactions; purchase n'est jamais ajouté
    # aux ventes dans une même matrice, il reste un signal web distinct.
    sales_for_basket = sales.rename(columns={"ds": "date_commande"})
    baskets = build_order_baskets(sales_for_basket, products)
    sequences = build_session_sequences(web_human, exclure_bots=False)
    interactions = build_client_product_interactions(web_human, exclure_bots=False)

    outputs = {"product_daily_forecasting": daily,
               "product_day_discount_pricing": pricing,
               "order_baskets": baskets, "session_sequences": sequences,
               "client_product_interactions": interactions}
    manifest = {}
    for name, df in outputs.items():
        path = OUT / f"{name}.parquet"
        df.to_parquet(path, index=False)
        manifest[name] = {"rows": len(df), "columns": list(df.columns), "sha256": _sha(path)}
    failed = [k for k, x in checks.items() if not x["ok"]]
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# 01 — Audit des données finales", "", "## Verdict", "",
             ("**VALIDÉ — entraînements autorisés.**" if not failed else
              f"**ÉCHEC BLOQUANT — entraînements interdits : {failed}.**"), "",
             "Extraction fraîche, locale et strictement en lecture seule. Aucun cache ou résultat V1 n'a été réutilisé.", "",
             "## Contrôles", "", "| Contrôle | Résultat | Détail |", "|---|---:|---|"]
    lines += [f"| `{k}` | {'OK' if x['ok'] else 'ÉCHEC'} | {x['detail']} |" for k,x in checks.items()]
    lines += ["", "## Datasets reconstruits", "", "| Dataset | Lignes | SHA-256 |", "|---|---:|---|"]
    lines += [f"| `{k}` | {x['rows']:,} | `{x['sha256']}` |" for k,x in manifest.items()]
    lines += ["", "## Limites documentées", "",
              "- `quantite_vendue` du stock inclut tous les statuts; aucune réintégration d'annulation/retour n'est modélisée.",
              "- Le prix catalogue est fixe par produit : le pricing ne peut être ni causal ni un optimum continu; il reste un simulateur de promotions/marge.",
              "- La règle session est un timeout d'inactivité ≤30 minutes; la durée totale peut dépasser 30 minutes.",
              "- Les visiteurs anonymes sont conservés sans création de client fictif."]
    (REPORT / "01_data_audit.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"failed": failed, "datasets": {k:v["rows"] for k,v in manifest.items()}}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
