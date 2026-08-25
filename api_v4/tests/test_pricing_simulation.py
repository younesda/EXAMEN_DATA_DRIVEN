"""Tests de la simulation pricing.

Couvrent le defaut constate en console (volume, chiffre d'affaires et marge
affiches a zero) et sa cause reelle : la moitie des produits ont une mediane
hebdomadaire de ventes nulle. Ces tests verifient qu'un zero est toujours une
prediction reelle et jamais une erreur masquee.
"""
from __future__ import annotations

import joblib
import pytest
from fastapi.testclient import TestClient

from api_v4.config import MODELS_DIR
from api_v4.main import app
from api_v4.registry import REGISTRY
from api_v4.services import pricing as pricing_service

client = TestClient(app)


def _produit_volume_non_nul() -> str:
    table = joblib.load(MODELS_DIR / "pricing" / "units_sold_window_7j" / "model.joblib"
                        )["fitted_model"].state["table"]
    for key in sorted(table.index):
        if table[key] > 0 and key in REGISTRY.pricing_catalog:
            return key
    pytest.skip("aucun produit a mediane non nulle")


def _produit_volume_nul() -> str:
    table = joblib.load(MODELS_DIR / "pricing" / "units_sold_window_7j" / "model.joblib"
                        )["fitted_model"].state["table"]
    for key in sorted(table.index):
        if table[key] == 0 and key in REGISTRY.pricing_catalog:
            return key
    pytest.skip("aucun produit a mediane nulle")


# ------------------------------------------------------ prediction non nulle


def test_produit_avec_prediction_non_nulle():
    produit = _produit_volume_non_nul()
    corps = client.post("/pricing/simulation",
                        json={"produit_key": produit, "discount_proposed": 10}).json()
    assert corps["volume_estime_unites_7j"] > 0
    assert corps["chiffre_affaires_estime_xof"] > 0
    assert corps["marge_estimee_xof"] != 0
    assert corps["volume_nul"] is False
    assert corps["message"] is None


def test_formule_du_chiffre_affaires_et_de_la_marge():
    """chiffre_affaires = volume x prix_simule ;
    marge = volume x (prix_simule - cout)."""
    produit = _produit_volume_non_nul()
    for remise in (0, 5, 15, 30):
        corps = client.post("/pricing/simulation",
                            json={"produit_key": produit, "discount_proposed": remise}).json()
        volume = corps["volume_estime_unites_7j"]
        prix = corps["prix_simule_xof"]
        cout = corps["cout_xof"]
        assert corps["chiffre_affaires_estime_xof"] == pytest.approx(volume * prix, abs=0.01)
        assert corps["marge_estimee_xof"] == pytest.approx(volume * (prix - cout), abs=0.01)
        assert corps["marge_unitaire_xof"] == pytest.approx(prix - cout, abs=0.01)


def test_le_prix_simule_suit_la_remise():
    produit = _produit_volume_non_nul()
    catalogue = REGISTRY.pricing_catalog[produit]
    for remise in (0, 10, 25):
        corps = client.post("/pricing/simulation",
                            json={"produit_key": produit, "discount_proposed": remise}).json()
        attendu = catalogue["prix_base_xof"] * (1 - remise / 100)
        assert corps["prix_simule_xof"] == pytest.approx(attendu, abs=0.01)


def test_le_chiffre_affaires_reagit_a_la_remise():
    """Consequence du calcul derive : contrairement aux medianes independantes
    utilisees auparavant, le chiffre d'affaires varie avec la remise."""
    produit = _produit_volume_non_nul()
    sans = client.post("/pricing/simulation",
                       json={"produit_key": produit, "discount_proposed": 0}).json()
    avec = client.post("/pricing/simulation",
                       json={"produit_key": produit, "discount_proposed": 20}).json()
    assert avec["chiffre_affaires_estime_xof"] < sans["chiffre_affaires_estime_xof"]
    assert avec["marge_estimee_xof"] < sans["marge_estimee_xof"]


# --------------------------------------------------------- prediction nulle


def test_prediction_reellement_nulle_est_signalee_et_non_masquee():
    produit = _produit_volume_nul()
    reponse = client.post("/pricing/simulation",
                          json={"produit_key": produit, "discount_proposed": 10})
    assert reponse.status_code == 200, "un zero reel n'est pas une erreur"
    corps = reponse.json()
    assert corps["volume_estime_unites_7j"] == 0
    assert corps["volume_nul"] is True
    assert corps["message"], "un volume nul doit etre explique"
    assert "rotation lente" in corps["message"]


def test_un_volume_nul_reste_coherent_avec_les_formules():
    produit = _produit_volume_nul()
    corps = client.post("/pricing/simulation",
                        json={"produit_key": produit, "discount_proposed": 10}).json()
    assert corps["chiffre_affaires_estime_xof"] == 0
    assert corps["marge_estimee_xof"] == 0
    # la marge unitaire, elle, reste informative meme si le volume est nul
    assert corps["marge_unitaire_xof"] == pytest.approx(
        corps["prix_simule_xof"] - corps["cout_xof"], abs=0.01)


# ------------------------------------------------------------------ erreurs


def test_produit_absent_renvoie_404():
    reponse = client.post("/pricing/simulation", json={"produit_key": "PRD_INEXISTANT"})
    assert reponse.status_code == 404


def test_remise_sous_le_cout_renvoie_422():
    produit = _produit_volume_non_nul()
    reponse = client.post("/pricing/simulation",
                          json={"produit_key": produit, "discount_proposed": 99})
    assert reponse.status_code == 422
    assert "inferieur au cout" in reponse.json()["detail"]


def test_modele_indisponible_renvoie_une_erreur_explicite_pas_un_zero():
    """Regression : un modele absent doit produire une erreur HTTP, jamais un
    volume de zero qui serait indistinguable d'une prediction reelle."""
    produit = _produit_volume_non_nul()
    original = dict(REGISTRY.pricing_models)
    REGISTRY.pricing_models.pop("units_sold_window_7j", None)
    try:
        reponse = client.post("/pricing/simulation",
                              json={"produit_key": produit, "discount_proposed": 10})
        assert reponse.status_code == 503
        assert "volume non disponible" in reponse.json()["detail"]
    finally:
        REGISTRY.pricing_models.clear()
        REGISTRY.pricing_models.update(original)


def test_echec_de_prediction_ne_devient_jamais_zero(monkeypatch):
    produit = _produit_volume_non_nul()

    def _echec(modele, frame):
        raise RuntimeError("echec simule du modele")

    monkeypatch.setattr(pricing_service, "predict_pricing", _echec)
    reponse = client.post("/pricing/simulation",
                          json={"produit_key": produit, "discount_proposed": 10})
    assert reponse.status_code == 503
    assert "echec de prediction" in reponse.json()["detail"]


def test_volume_non_fini_est_rejete(monkeypatch):
    import numpy as np
    produit = _produit_volume_non_nul()
    monkeypatch.setattr(pricing_service, "predict_pricing",
                        lambda modele, frame: np.array([float("nan")]))
    reponse = client.post("/pricing/simulation",
                          json={"produit_key": produit, "discount_proposed": 10})
    assert reponse.status_code == 503
    assert "non finie" in reponse.json()["detail"]


# --------------------------------------------------------- statut et modele


def test_la_reponse_expose_le_modele_et_son_statut():
    produit = _produit_volume_non_nul()
    corps = client.post("/pricing/simulation",
                        json={"produit_key": produit, "discount_proposed": 10}).json()
    assert corps["modele"] == "baseline_mediane_produit"
    assert corps["modele_statut"] == "validated_academic"


def test_aucune_revendication_causale_dans_la_reponse():
    produit = _produit_volume_non_nul()
    corps = client.post("/pricing/simulation",
                        json={"produit_key": produit, "discount_proposed": 10}).json()
    avertissement = corps["avertissement"].lower()
    assert "aucune revendication causale" in avertissement
    assert "aucune application automatique" in avertissement


def test_la_console_expose_un_exemple_de_produit_a_volume_non_nul():
    """La page doit s'ouvrir sur un produit exploitable, pas sur un produit a
    mediane nulle affichant partout des zeros."""
    from api_v4.config import STATIC_DIR
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "EXEMPLE_PRICING" in script
    exemple = script.split('EXEMPLE_PRICING = "')[1].split('"')[0]
    corps = client.post("/pricing/simulation",
                        json={"produit_key": exemple, "discount_proposed": 10}).json()
    assert corps["volume_estime_unites_7j"] > 0, (
        f"l'exemple {exemple} propose par la console a un volume nul")


def test_la_console_affiche_toujours_la_valeur_reelle_meme_nulle():
    """Une prediction de zero est une valeur reelle : la console doit l'afficher,
    et non la remplacer par une mention du type "non exploitable"."""
    from api_v4.config import STATIC_DIR
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # Les commentaires citent volontairement la formulation ecartee pour
    # expliquer le choix : le controle porte sur le code executable.
    code = "\n".join(ligne for ligne in script.splitlines()
                     if not ligne.strip().startswith("//"))
    assert "non exploitable" not in code, (
        "la console masque une valeur reellement predite au lieu de l'afficher")
    assert "nombre(donnees.volume_estime_unites_7j, 2)" in code
    assert "xof(donnees.chiffre_affaires_estime_xof)" in code
    assert "xof(donnees.marge_estimee_xof)" in code


def test_un_volume_nul_reste_signale_sans_effacer_les_chiffres():
    """Le signalement passe par le message et un marqueur visuel, jamais par
    la suppression de la valeur."""
    from api_v4.config import STATIC_DIR
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "valeur-nulle" in script, "marqueur visuel absent"
    assert "donnees.message" in script, "message explicatif absent"
