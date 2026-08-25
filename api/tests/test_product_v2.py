"""Tests du produit V2 : nouveaux endpoints, garde-fous et honnêteté d'affichage."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Valeurs retirées par l'audit de fuite. Aucune ne doit apparaître comme
#: résultat courant, ni dans l'API, ni dans l'interface.
INVALIDEES = ("0.4164", "0.41637", "0.43743", "0.21264", "0.1006", "0.0485")


# ------------------------------------------------------------------ santé


def test_version_expose_le_commit_et_l_environnement(client):
    charge = client.get("/version").json()
    assert charge["api_version"]
    assert charge["bundle_version"] == charge["model_version"]
    assert "environment" in charge and "commit" in charge
    assert charge["ready"] is True


def test_ready_declare_chaque_controle(client):
    charge = client.get("/ready").json()
    assert charge["status"] == "ready"
    for controle in ("models_loaded", "metadata_present", "sha256_valid",
                     "versions_consistent", "forecast_available"):
        assert charge["checks"][controle] is True


# --------------------------------------------------------------- métriques


def test_metrics_publie_les_trois_domaines(client):
    charge = client.get("/metrics").json()
    domaines = {d["key"]: d for d in charge["domains"]}
    assert set(domaines) == {"forecasting", "pricing", "recommendation"}

    forecast = {m["key"]: m["value"] for m in domaines["forecasting"]["metrics"]}
    assert forecast["wape30_macro"] == 0.25831
    assert forecast["wape30_micro"] == 0.25743
    assert forecast["forecast_bias_macro"] == -0.02589

    pricing = {m["key"]: m["value"] for m in domaines["pricing"]["metrics"]}
    assert pricing["wape"] == 0.5526
    assert pricing["forecast_bias"] == 0.0013
    assert domaines["pricing"]["status"] == "exploratory_non_causal"


def test_chaque_metrique_explique_son_sens_et_ses_limites(client):
    charge = client.get("/metrics").json()
    for domaine in charge["domains"]:
        for metrique in domaine.get("metrics", []):
            assert metrique["explanation"], metrique["key"]
            assert metrique["caveat"], metrique["key"]
            assert metrique["better"], metrique["key"]
            assert metrique["direction"] in {"lower", "higher", "zero"}


def test_les_deux_perimetres_de_recommandation_restent_separes(client):
    """Le périmètre général et le complément panier ne doivent jamais fusionner."""
    charge = client.get("/metrics").json()
    reco = next(d for d in charge["domains"] if d["key"] == "recommendation")
    perimetres = {p["key"]: p for p in reco["perimeters"]}
    assert set(perimetres) == {"general", "basket"}

    general = {m["key"]: m["value"] for m in perimetres["general"]["metrics"]}
    panier = {m["key"]: m["value"] for m in perimetres["basket"]["metrics"]}
    # Prochain achat : 4 fenêtres de 30 jours.
    assert math.isclose(general["recall"], 0.06685765, abs_tol=1e-6)
    assert math.isclose(general["ndcg"], 0.03771184, abs_tol=1e-6)
    # Complément panier : leave-one-item-out F2-F4.
    assert math.isclose(panier["recall"], 0.05557637, abs_tol=1e-6)
    assert math.isclose(panier["ndcg"], 0.02399695, abs_tol=1e-6)
    assert general["ndcg"] != panier["ndcg"]
    assert perimetres["basket"]["status"] == "none_validated"
    assert charge["perimeter_warning"]


def test_aucune_metrique_invalidee_n_est_exposee(client):
    for chemin in ("/metrics", "/models", "/api/v1/models/status"):
        texte = client.get(chemin).text
        for valeur in INVALIDEES:
            if valeur in texte:
                assert "invalidated" in texte, chemin + " expose " + valeur


def test_l_interface_n_affiche_aucune_metrique_invalidee():
    statiques = ROOT / "api" / "static"
    for nom in ("index.html", "app.js", "styles.css"):
        texte = (statiques / nom).read_text(encoding="utf-8")
        for valeur in ("0,4164", "0,437", "0,213", "0,1006", "0,0485"):
            assert valeur not in texte, nom + " contient " + valeur


def test_models_declare_le_modele_pricing_interdit(client):
    charge = client.get("/models").json()
    interdits = {m["key"]: m for m in charge["not_exposed"]}
    assert "pricing_accuracy" in interdits
    assert "18,14" in interdits["pricing_accuracy"]["reason"]
    assert charge["no_model_promoted"] is True


# --------------------------------------------------------------- catalogue


def test_catalogue_est_trie_par_popularite(client):
    charge = client.get("/api/v1/catalog/products?limit=10").json()
    assert charge["total"] == 300
    assert charge["returned"] == 10
    rangs = [p["popularity_rank"] for p in charge["products"]]
    assert rangs == sorted(rangs)


def test_recherche_produit_filtre_et_borne(client):
    charge = client.get("/api/v1/catalog/search?q=PRD00001&limit=5").json()
    assert charge["returned"] <= 5
    assert all("PRD00001" in p["product_key"] for p in charge["products"])
    vide = client.get("/api/v1/catalog/search?q=INEXISTANT").json()
    assert vide["returned"] == 0 and vide["products"] == []


# -------------------------------------------------------------- forecasting


def test_forecast_renvoie_un_backtest_valide(client, registry):
    produit = next(iter(registry.forecast["series"]))
    charge = client.post("/api/v1/forecast",
                         json={"product_key": produit, "horizon_days": 14}).json()
    assert charge["horizon_days"] == 14
    assert len(charge["points"]) == 14
    assert charge["kind"] == "backtest_valide"
    assert charge["model_name"] == "LightGBM_direct_per_horizon"
    assert charge["fallback_used"] is False
    total = sum(point["predicted_quantity"] for point in charge["points"])
    assert math.isclose(charge["total_predicted_quantity"], total, abs_tol=1e-3)
    assert all(math.isfinite(point["predicted_quantity"]) for point in charge["points"])


def test_forecast_refuse_un_produit_inconnu(client):
    reponse = client.post("/api/v1/forecast",
                          json={"product_key": "PRD999999", "horizon_days": 7})
    assert reponse.status_code == 404
    charge = reponse.json()
    assert charge["success"] is False
    assert charge["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_forecast_borne_l_horizon(client, registry):
    produit = next(iter(registry.forecast["series"]))
    for horizon in (0, 31, 999):
        reponse = client.post("/api/v1/forecast",
                              json={"product_key": produit, "horizon_days": horizon})
        assert reponse.status_code == 422, horizon


# ------------------------------------------------------------------ pricing


def test_pricing_accepte_un_contexte_vide(client, registry):
    """Une interface ne peut pas demander `stock_at_cutoff` à un utilisateur."""
    produit, ligne = next(iter(registry.catalog["pricing_catalog"].items()))
    reponse = client.post("/api/v1/pricing/simulate", json={
        "product_key": produit, "decision_date": "2026-07-15",
        "candidate_discounts_pct": [ligne["supported_discounts_pct"][0]], "features": {}})
    assert reponse.status_code == 200
    assert reponse.json()["simulations"]


def test_pricing_rejette_les_valeurs_non_finies(client, registry):
    produit = next(iter(registry.catalog["pricing_catalog"]))
    corps = json.dumps({
        "product_key": produit, "decision_date": "2026-07-15",
        "candidate_discounts_pct": [0], "features": {"stock_at_cutoff": float("nan")}})
    reponse = client.post("/api/v1/pricing/simulate", content=corps,
                          headers={"Content-Type": "application/json"})
    assert reponse.status_code == 422
    assert reponse.json()["error"]["code"] == "NON_FINITE_VALUE"


def test_mode_partiel_bloque_par_remise_sans_annuler_la_simulation(client, registry):
    """Une remise fautive ne doit pas faire perdre les scénarios valides."""
    cible = None
    for produit, ligne in registry.catalog["pricing_catalog"].items():
        remises = [float(v) for v in ligne["supported_discounts_pct"]]
        marge = 1 - ligne["cost_xof"] / ligne["catalog_price_xof"]
        if len(remises) >= 2 and max(remises) / 100 > marge:
            cible = (produit, remises)
            break
    if cible is None:
        return
    produit, remises = cible
    charge = client.post("/api/v1/pricing/simulate", json={
        "product_key": produit, "decision_date": "2026-07-15",
        "candidate_discounts_pct": remises, "features": {},
        "partial_results": True}).json()
    statuts = {s["simulation_status"] for s in charge["simulations"]}
    assert "blocked" in statuts
    for simulation in charge["simulations"]:
        if simulation["simulation_status"] == "blocked":
            assert simulation["blocked_reason"], "un blocage doit être expliqué"
            assert simulation["blocked_reason_code"] in {"price_below_cost", "margin_below_floor"}
            assert simulation["predicted_quantity"] == 0.0


def test_les_garde_fous_pricing_restent_declares(client, registry):
    produit, ligne = next(iter(registry.catalog["pricing_catalog"].items()))
    charge = client.post("/api/v1/pricing/simulate", json={
        "product_key": produit, "decision_date": "2026-07-15",
        "candidate_discounts_pct": [ligne["supported_discounts_pct"][0]],
        "features": {}}).json()
    assert charge["model_status"] == "exploratory_non_causal"
    assert charge["automatic_application_allowed"] is False
    assert charge["human_validation_required"] is True
    assert charge["causal_effect_estimated"] is False


# ------------------------------------------------------------ format d'erreur


def test_toutes_les_erreurs_partagent_le_meme_format(client):
    cas = [
        ("/inexistant", "GET", None, 404),
        ("/api/v1/recommendations/general", "POST", {"k": 0}, 422),
        ("/api/v1/forecast", "POST", {"product_key": "PRD999999", "horizon_days": 7}, 404),
    ]
    for chemin, methode, corps, attendu in cas:
        reponse = (client.get(chemin) if methode == "GET"
                   else client.post(chemin, json=corps))
        assert reponse.status_code == attendu, chemin
        charge = reponse.json()
        assert charge["success"] is False, chemin
        erreur = charge["error"]
        assert set(erreur) == {"code", "message", "details", "request_id"}, chemin
        assert erreur["code"].isupper(), chemin
        assert erreur["message"], chemin
        # Aucune trace d'exécution ni chemin local ne doit fuiter.
        assert "Traceback" not in reponse.text
        assert "C:\\" not in reponse.text and "/home/" not in reponse.text


def test_l_interface_est_servie_et_en_francais(client):
    page = client.get("/").text
    assert 'lang="fr"' in page
    for terme in ("Prévision", "remise", "recommandation"):
        assert terme.lower() in page.lower()
    script = client.get("/static/app.js").text
    # Le vocabulaire causal est proscrit côté pricing.
    assert "prix optimal" not in script.lower()
    for attendu in ("Validation humaine requise", "exploratoire", "Données synthétiques"):
        assert attendu.lower() in (page + script).lower(), attendu
