"""Service de consultation de la prevision 30 jours.

Lecture seule stricte. Ce module ne charge aucun modele de forecasting, n'en
reentraine aucun et ne modifie aucun artefact : il sert un instantane deja
calcule (`api_v4/data/forecast_snapshot.json`), derive du backtest hors
echantillon du modele V2 valide.

Ce que le service expose est donc un RESULTAT DE BACKTEST (realise contre
prevu sur une fenetre passee), et non une prevision du futur. Cette
distinction est portee explicitement dans chaque reponse.
"""
from __future__ import annotations

from api_v4.registry import REGISTRY


class ForecastUnavailableError(Exception):
    """L'instantane de prevision n'est pas charge."""


class UnknownForecastProductError(Exception):
    """Le produit demande n'appartient pas a l'instantane de prevision."""


def _snapshot() -> dict:
    snapshot = REGISTRY.forecast_snapshot
    if not snapshot or not snapshot.get("produits"):
        raise ForecastUnavailableError("instantane de prevision indisponible")
    return snapshot


def summary() -> dict:
    """Synthese : modeles retenus, metriques globales, fenetre evaluee."""
    snapshot = _snapshot()
    return {
        "statut": snapshot["statut"],
        "modele_planification_30j": snapshot["modele_planification_30j"],
        "modele_quotidien": snapshot["modele_quotidien"],
        "metriques": snapshot["metriques"],
        "fenetre": {k: v for k, v in snapshot["fenetre"].items() if k != "dates"},
        "n_produits": snapshot["n_produits"],
        "avertissement": snapshot["avertissement"],
    }


def product_list(limite: int = 300) -> list[dict]:
    """Liste des produits couverts, avec leur ecart cumule sur 30 jours."""
    snapshot = _snapshot()
    lignes = [
        {
            "produit_key": key,
            "nom": valeur["nom"],
            "categorie": valeur["categorie"],
            "total_reel_30j": valeur["total_reel_30j"],
            "total_prevu_30j": valeur["total_prevu_30j"],
            "ecart_absolu_30j": valeur["ecart_absolu_30j"],
        }
        for key, valeur in snapshot["produits"].items()
    ]
    lignes.sort(key=lambda ligne: ligne["produit_key"])
    return lignes[:limite]


def product_forecast(produit_key: str) -> dict:
    """Courbe realise contre prevu, horizon par horizon, pour un produit."""
    snapshot = _snapshot()
    entree = snapshot["produits"].get(produit_key)
    if entree is None:
        raise UnknownForecastProductError(produit_key)
    return {
        "produit_key": produit_key,
        "nom": entree["nom"],
        "categorie": entree["categorie"],
        "modele": snapshot["modele_planification_30j"],
        "fenetre_debut": snapshot["fenetre"]["debut"],
        "horizons": snapshot["fenetre"]["horizons"],
        "dates": snapshot["fenetre"]["dates"],
        "reel": entree["reel"],
        "prevu": entree["prevu"],
        "total_reel_30j": entree["total_reel_30j"],
        "total_prevu_30j": entree["total_prevu_30j"],
        "ecart_absolu_30j": entree["ecart_absolu_30j"],
        "avertissement": snapshot["avertissement"],
    }
