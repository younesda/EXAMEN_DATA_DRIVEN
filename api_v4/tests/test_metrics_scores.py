"""Tests de la route `/metrics` et de la coherence des scores affiches.

Exigence centrale : aucune valeur de score ne doit etre inventee ni ecrite en
dur. Chaque nombre servi doit provenir des metadonnees finales, et une
metrique absente doit valoir `null` plutot que zero.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api_v4.config import MODELS_DIR, STATIC_DIR
from api_v4.main import app
from src.config.settings import PROJECT_ROOT

client = TestClient(app)

CIBLES_PRICING = ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j")


@pytest.fixture(scope="module")
def scores() -> dict:
    return client.get("/metrics").json()


@pytest.fixture(scope="module")
def final_status() -> dict:
    return json.loads((MODELS_DIR / "FINAL_STATUS.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- structure


def test_metrics_expose_les_trois_domaines(scores):
    for domaine in ("forecasting", "pricing", "recommendation"):
        assert domaine in scores, f"domaine manquant dans /metrics : {domaine}"


def test_metrics_conserve_les_compteurs_operationnels(scores):
    """Les compteurs restent disponibles, deplaces sous la clef `service`."""
    assert "service" in scores
    assert "requests_total" in scores["service"]


# ------------------------------------------------------------ forecasting


def test_forecasting_reprend_exactement_la_decision_v2(scores):
    statut = json.loads(
        (PROJECT_ROOT / "models" / "FINAL_STATUS.json").read_text(encoding="utf-8"))["status"]
    f = scores["forecasting"]
    assert f["planning_model"] == statut["forecasting_30d_model"] == "LightGBM_direct_per_horizon"
    assert f["daily_model"] == statut["forecasting_daily_model"] == "CrostonOptimized"
    assert f["wape30_macro"] == statut["forecasting_wape30_macro"] == 0.25831
    assert f["forecast_bias_macro"] == statut["forecasting_bias"] == -0.02589


def test_forecasting_ne_revendique_pas_une_exactitude_de_90_pour_cent(scores):
    assert "90" in scores["forecasting"]["note"]


# ---------------------------------------------------------------- pricing


def test_pricing_present_dans_metrics(scores):
    p = scores["pricing"]
    assert p["model"] == "baseline_mediane_produit"
    assert p["status"] == "simulation_only"
    assert set(p["targets"]) == set(CIBLES_PRICING)


def test_pricing_present_dans_metadata(final_status):
    cibles = {e["target"] for e in final_status["models"] if e["domain"] == "pricing"}
    assert cibles == set(CIBLES_PRICING)


def test_pricing_ne_revendique_ni_causalite_ni_prix_optimal(scores):
    p = scores["pricing"]
    assert p["causal_effect_estimated"] is False
    assert p["automatic_optimal_price"] is False


def test_scores_pricing_identiques_aux_metadonnees(scores, final_status):
    """Coherence stricte : chaque WAPE et biais servi doit egaler la valeur
    enregistree dans les metadonnees, sans arrondi ni recalcul."""
    par_cible = {e["target"]: e["metrics"] for e in final_status["models"]
                 if e["domain"] == "pricing"}
    for cible in CIBLES_PRICING:
        servi = scores["pricing"]["targets"][cible]
        attendu = par_cible[cible]
        assert servi["wape_macro"] == attendu["wape_macro"]
        assert servi["bias_macro"] == attendu["bias"]


def test_aucune_valeur_pricing_inventee(scores):
    """Chaque metrique servie existe reellement dans les metadonnees, ou vaut
    `null`. Aucune ne doit valoir zero par defaut."""
    for cible in CIBLES_PRICING:
        c = scores["pricing"]["targets"][cible]
        assert c["disponible"] is True
        for clef in ("wape_macro", "bias_macro"):
            assert c[clef] is not None, f"{cible}.{clef} absent"
        # une WAPE nulle serait suspecte : elle signalerait une valeur par defaut
        assert c["wape_macro"] > 0, f"{cible} : WAPE nulle, valeur de remplacement probable"


# --------------------------------------------------------- recommandation


def test_recommandation_expose_les_trois_roles(scores):
    assert set(scores["recommendation"]) == {"purchase", "add_to_cart", "view"}


def test_recommandation_modeles_et_gains_conformes_aux_metadonnees(scores, final_status):
    par_cible = {e["target"]: e for e in final_status["models"]
                 if e["domain"] == "recommendation" and e.get("sha256")}
    attendu = {
        "purchase": ("purchased_after", "CatBoostRanker", "validated_academic"),
        "add_to_cart": ("added_to_cart_after", "pointwise_conversion", "validated_academic"),
        "view": ("viewed_after_impression", "CatBoostRanker", "exploratory"),
    }
    for role, (cible, modele, statut) in attendu.items():
        servi = scores["recommendation"][role]
        assert servi["model"] == modele
        assert servi["status"] == statut
        assert servi["ndcg10_gain_relative"] == par_cible[cible]["metrics"]["relative_ndcg_gain"]
        assert servi["holm_pvalue_independent"] == \
            par_cible[cible]["metrics"]["p_value_holm_independante"]


def test_gains_recommandation_correspondent_aux_valeurs_publiees(scores):
    """Verifie les ordres de grandeur publies dans les rapports V4."""
    assert scores["recommendation"]["purchase"]["ndcg10_gain_relative"] == pytest.approx(0.0857, abs=1e-4)
    assert scores["recommendation"]["purchase"]["holm_pvalue_independent"] == pytest.approx(0.00075, abs=1e-5)
    assert scores["recommendation"]["add_to_cart"]["ndcg10_gain_relative"] == pytest.approx(0.0770, abs=1e-4)
    assert scores["recommendation"]["add_to_cart"]["holm_pvalue_independent"] == pytest.approx(0.0015, abs=1e-5)
    assert scores["recommendation"]["view"]["ndcg10_gain_relative"] == pytest.approx(0.0557, abs=1e-4)


def test_le_modele_de_consultation_reste_exploratoire_et_non_par_defaut(scores):
    vue = scores["recommendation"]["view"]
    assert vue["status"] == "exploratory"
    assert vue["used_by_default"] is False
    assert vue["fallback"] == "popularite_globale_v1"


# ------------------------------------------------------------- interface


def test_la_console_ne_code_aucun_score_en_dur():
    """Les scores affiches doivent venir de l'API, pas du script."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for valeur in ("0.25831", "0,25831", "0.02589", "0,02589",
                   "0.0857", "0,0857", "0.00075", "0,00075",
                   "0.1342", "0,1342", "0.077", "0,077"):
        assert valeur not in script, (
            f"score {valeur} ecrit en dur dans la console ; il doit etre lu depuis l'API")


def test_la_console_affiche_les_trois_domaines():
    """Les trois domaines sont presents, desormais en sections numerotees avec
    le forecasting en tete."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for titre in ("1. Forecasting V2", "2. Recommandation V4", "3. Pricing V4"):
        assert titre in script, f"domaine absent de la console : {titre}"


def test_la_console_propose_des_liens_vers_docs_et_metrics():
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'href="/metrics"' in page
    assert 'href="/docs"' in page


def test_la_console_ne_reference_aucun_endpoint_v2():
    """Aucun appel a l'ancienne API V2 ne doit subsister."""
    for fichier in ("app.js", "index.html"):
        contenu = (STATIC_DIR / fichier).read_text(encoding="utf-8")
        assert "/api/v1" not in contenu, f"reference a l'API V2 dans {fichier}"
        assert "/ready" not in contenu, f"sonde V2 referencee dans {fichier}"
        assert "examen-data-driven.onrender.com" not in contenu


def test_la_console_utilise_des_badges_de_statut():
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for statut in ("validated_academic", "exploratory", "simulation_only", "validated"):
        assert statut in script, f"badge manquant pour le statut {statut}"


# ------------------------------------------- forecasting detaille (section 1)


def test_metrics_expose_les_metriques_forecasting_detaillees(scores):
    f = scores["forecasting"]
    assert f["daily_model"] == "CrostonOptimized"
    assert f["planning_model"] == "LightGBM_direct_per_horizon"
    assert f["wape30_macro"] == 0.25831
    assert f["wape30_micro"] == 0.25743
    assert f["forecast_bias_macro"] == -0.02589
    assert f["status"] == "validated"


def test_metrics_expose_les_horizons_forecasting(scores):
    h = scores["forecasting"]["horizons"]
    for cle in ("quotidien", "cumule_7j", "cumule_14j", "cumule_30j"):
        assert cle in h, f"horizon manquant : {cle}"
        assert "definition" in h[cle], f"definition manquante pour {cle}"


def test_horizon_14_jours_declare_indisponible_sans_valeur_inventee(scores):
    """Le backtest n'a pas calcule la WAPE a 14 jours : elle doit etre
    declaree absente, jamais remplacee par un nombre."""
    quatorze = scores["forecasting"]["horizons"]["cumule_14j"]
    assert quatorze["disponible"] is False
    assert quatorze["wape"] is None
    assert quatorze["raison_indisponibilite"]


def test_metrics_expose_les_fenetres_et_victoires_forecasting(scores):
    w = scores["forecasting"]["windows"]
    assert w["evaluated"] == 6
    assert w["won_planning_30d"] is not None
    assert w["won_daily"] is not None
    assert len(w["detail"]) == 6
    for fenetre in w["detail"]:
        for cle in ("fenetre", "debut", "wape_quotidienne",
                    "wape_cumulee_7j", "wape_cumulee_30j", "biais"):
            assert cle in fenetre, f"champ manquant dans une fenetre : {cle}"


def test_metriques_forecasting_coherentes_avec_l_instantane():
    """Les valeurs servies doivent egaler celles de l'instantane de backtest,
    lui-meme derive des metadonnees de prevision."""
    from api_v4.config import FORECAST_SNAPSHOT_PATH
    instantane = json.loads(FORECAST_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    servi = client.get("/metrics").json()["forecasting"]
    metriques = instantane["metriques"]
    assert servi["horizons"]["quotidien"]["wape"] == metriques["wape_quotidienne"]
    assert servi["horizons"]["cumule_7j"]["wape"] == metriques["wape_cumulee_7j"]
    assert servi["horizons"]["cumule_30j"]["wape"] == metriques["wape_cumulee_30j"]
    assert servi["daily_model_metrics"] == instantane["modele_quotidien_metriques"]


def test_forecasting_ne_revendique_aucune_exactitude(scores):
    note = scores["forecasting"]["note"].lower()
    assert "backtest" in note
    assert "sans reentrainement" in note
    assert "aucune exactitude" in note


# ----------------------------------------------------- console : 3 sections


def test_la_console_organise_les_scores_en_trois_sections():
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for fonction in ("sectionForecasting", "sectionRecommandation", "sectionPricing"):
        assert fonction in script, f"section manquante : {fonction}"
    assert '"1. Forecasting V2' in script
    assert '"2. Recommandation V4' in script
    assert '"3. Pricing V4' in script


def test_la_console_propose_les_liens_forecast():
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'href="/forecast"' in script
    assert 'href="/forecast/produits"' in script


def test_la_console_ne_code_aucune_metrique_forecasting_en_dur():
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for valeur in ("0.25743", "0,25743", "1.0869", "1,0869", "0.4545", "0,4545",
                   "1.0945", "1,0945", "0.3699", "0,3699"):
        assert valeur not in script, (
            f"metrique forecasting {valeur} ecrite en dur dans la console")


def test_la_console_conserve_les_metriques_de_recommandation():
    """Regression : la mise en avant du forecasting ne doit pas evincer les
    scores de recommandation."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "ndcg10_gain_relative" in script
    assert "holm_pvalue_independent" in script
    assert "Gain NDCG@10" in script


def test_la_console_ne_parle_jamais_d_exactitude():
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "accuracy" not in script.lower()
    assert "exactitude" in script, "la mise en garde sur l'exactitude doit rester"


def test_la_console_masque_les_metriques_non_calculees():
    """Une metrique non calculee ne doit pas produire de carte vide dans la
    page Scores. L'information reste disponible dans /metrics : c'est
    l'affichage qui est allege, pas la donnee qui est supprimee."""
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    code = "\n".join(ligne for ligne in script.splitlines()
                     if not ligne.strip().startswith("//"))
    assert "non calcule" not in code, (
        "la console affiche encore une mention pour une metrique absente")
    assert "if (valeur === null || valeur === undefined) return null;" in code, (
        "carteMetrique doit renoncer a construire la carte si la valeur manque")
    assert "!entree.disponible) return;" in code, (
        "un horizon non evalue doit etre ignore, pas rendu")


def test_metrics_continue_d_exposer_les_metriques_non_calculees(scores):
    """Contrepartie du test precedent : masquer dans l'interface ne doit pas
    revenir a supprimer l'information de l'API."""
    quatorze = scores["forecasting"]["horizons"]["cumule_14j"]
    assert quatorze["disponible"] is False
    assert quatorze["wape"] is None
    assert quatorze["raison_indisponibilite"]


# ------------------------------------------------- listes plates analytiques


def test_pricing_produits_est_une_liste_plate_exploitable():
    corps = client.get("/pricing/produits").json()
    assert corps["n_produits"] == 300
    assert corps["statut"] == "simulation_only"
    ligne = corps["produits"][0]
    for champ in ("produit_key", "categorie", "classe_abc", "prix_catalogue_xof",
                  "cout_xof", "marge_unitaire_prix_catalogue_xof",
                  "volume_median_estime_7j", "volume_nul"):
        assert champ in ligne, f"champ manquant : {champ}"


def test_le_volume_de_la_liste_egale_celui_de_la_simulation():
    """Coherence stricte : la liste et la simulation doivent servir la meme
    valeur, sinon un tableau de bord et l'API se contrediraient."""
    liste = {l["produit_key"]: l for l in client.get("/pricing/produits").json()["produits"]}
    for produit in ("PRD000002", "PRD000003", "PRD000004"):
        sim = client.post("/pricing/simulation",
                          json={"produit_key": produit, "discount_proposed": 0}).json()
        assert liste[produit]["volume_median_estime_7j"] == sim["volume_estime_unites_7j"]
        assert liste[produit]["prix_catalogue_xof"] == sim["prix_catalogue_xof"]
        assert liste[produit]["cout_xof"] == sim["cout_xof"]


def test_la_marge_unitaire_de_la_liste_est_coherente():
    for ligne in client.get("/pricing/produits").json()["produits"][:20]:
        attendu = ligne["prix_catalogue_xof"] - ligne["cout_xof"]
        assert ligne["marge_unitaire_prix_catalogue_xof"] == pytest.approx(attendu, abs=0.01)


def test_recommendations_produits_est_une_liste_plate_exploitable():
    corps = client.get("/recommendations/produits").json()
    assert corps["n_produits"] == 208, "le catalogue de recommandation couvre 208 produits"
    ligne = corps["produits"][0]
    for champ in ("produit_key", "categorie", "prix_base_xof",
                  "popularite_globale", "popularite_recente_28j",
                  "rang_popularite_globale"):
        assert champ in ligne, f"champ manquant : {champ}"


def test_la_liste_de_recommandation_ne_se_presente_pas_comme_une_recommandation():
    """Garde-fou de sens : ces scores de popularite ne doivent jamais etre
    presentes comme une recommandation personnalisee."""
    corps = client.get("/recommendations/produits").json()
    assert corps["nature"] == "scores_de_popularite"
    assert corps["modele"] == "popularite_globale_v1"
    avertissement = corps["avertissement"].lower()
    assert "ne constituent pas une recommandation" in avertissement


def test_les_rangs_de_popularite_sont_coherents():
    lignes = client.get("/recommendations/produits").json()["produits"]
    rangs = sorted(l["rang_popularite_globale"] for l in lignes)
    assert rangs == list(range(1, len(lignes) + 1)), "les rangs doivent etre uniques et contigus"
    par_rang = sorted(lignes, key=lambda l: l["rang_popularite_globale"])
    popularites = [l["popularite_globale"] for l in par_rang]
    assert popularites == sorted(popularites, reverse=True), "rang 1 = plus populaire"


def test_les_deux_catalogues_ont_des_tailles_differentes_et_documentees():
    """Piege connu pour une jointure : 300 produits cote pricing, 208 cote
    recommandation."""
    pricing = client.get("/pricing/produits").json()["n_produits"]
    reco = client.get("/recommendations/produits").json()["n_produits"]
    assert pricing == 300 and reco == 208
    assert "moins que le catalogue pricing" in \
        client.get("/recommendations/produits").json()["avertissement"]
