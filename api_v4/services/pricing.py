"""Service de simulation pricing de l'API produit V4.

Simulation uniquement : aucune ecriture, aucune application automatique du
prix simule. Le volume provient de la baseline mediane par produit
(`baseline_mediane_produit`), seule reference issue de l'entrainement.

Deux principes explicites dans ce module :

1. **Aucune erreur n'est convertie en zero.** Si le modele n'est pas charge
   ou si sa prediction n'est pas exploitable, le service leve une erreur et
   l'API repond explicitement ; il ne renvoie jamais `0` a la place. Un `0`
   renvoye par ce service est donc toujours une valeur reellement predite.

2. **Le chiffre d'affaires et la marge sont DERIVES**, et non issus de
   modeles independants. Ils se calculent a partir du volume predit et du
   prix simule :

       chiffre_affaires = volume x prix_simule
       marge            = volume x (prix_simule - cout_unitaire)

   Les modeles `revenue_window_xof_7j` et `margin_window_xof_7j` restent
   entraines et documentes, mais ils predisent des medianes historiques qui
   ne reagissent pas a la remise proposee : les utiliser ici produirait un
   chiffre d'affaires insensible au prix simule, donc trompeur dans une
   simulation. Ce choix est documente dans la reponse elle-meme.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from api_v4 import logging as journal
from api_v4.registry import REGISTRY
from src.pricing_v4.models import predict as predict_pricing

VOLUME_TARGET = "units_sold_window_7j"


class UnknownProductError(Exception):
    """Le produit demande n'appartient pas au catalogue pricing connu."""


class PriceBelowCostError(Exception):
    """La remise proposee ferait tomber le prix simule sous le cout produit."""

    def __init__(self, prix_simule: float, cout: float) -> None:
        self.prix_simule = prix_simule
        self.cout = cout
        super().__init__(f"prix simule {prix_simule:.2f} XOF < cout {cout:.2f} XOF")


class VolumeUnavailableError(Exception):
    """Le modele de volume ne peut produire aucune estimation exploitable.

    Distincte d'une prediction nulle : ici, il n'y a PAS de valeur, alors
    qu'une prediction de zero est une valeur legitime.
    """

    def __init__(self, produit_key: str, raison: str) -> None:
        self.produit_key = produit_key
        self.raison = raison
        super().__init__(f"volume indisponible pour {produit_key} : {raison}")


@dataclass
class PricingOutcome:
    produit_key: str
    categorie: str
    classe_abc: str
    prix_catalogue_xof: float
    cout_xof: float
    remise_proposee_pct: float
    prix_simule_xof: float
    volume_estime_unites_7j: float
    chiffre_affaires_estime_xof: float
    marge_estimee_xof: float
    marge_unitaire_xof: float
    volume_nul: bool
    modele: str
    modele_statut: str
    version: str
    garde_fous: dict
    message: Optional[str]


def _predire_volume(produit_key: str) -> float:
    """Volume predit par la baseline. Leve une erreur plutot que de renvoyer 0."""
    modele = REGISTRY.pricing_models.get(VOLUME_TARGET)
    if modele is None:
        journal.erreur("volume_modele_absent", produit_key=produit_key, cible=VOLUME_TARGET)
        raise VolumeUnavailableError(produit_key, "modele de volume non charge")

    try:
        brut = predict_pricing(modele, pd.DataFrame([{"produit_key": produit_key}]))
    except Exception as exc:  # noqa: BLE001 - remonte en erreur explicite, jamais en zero
        journal.erreur("volume_echec_prediction", produit_key=produit_key, detail=str(exc))
        raise VolumeUnavailableError(produit_key, f"echec de prediction : {exc}") from exc

    if len(brut) != 1:
        raise VolumeUnavailableError(produit_key, "le modele n'a pas renvoye exactement une valeur")

    valeur = float(brut[0])
    if math.isnan(valeur) or math.isinf(valeur):
        journal.erreur("volume_valeur_non_finie", produit_key=produit_key, valeur=str(brut[0]))
        raise VolumeUnavailableError(produit_key, "valeur predite non finie")
    if valeur < 0:
        journal.erreur("volume_negatif", produit_key=produit_key, valeur=valeur)
        raise VolumeUnavailableError(produit_key, "valeur predite negative")
    return valeur


def simulate(produit_key: str, discount_proposed_pct: float) -> PricingOutcome:
    entry = REGISTRY.pricing_catalog.get(produit_key)
    if entry is None:
        journal.avertissement("pricing_produit_inconnu", produit_key=produit_key)
        raise UnknownProductError(produit_key)

    prix_catalogue = float(entry["prix_base_xof"])
    cout = float(entry["cout_xof"])
    prix_simule = round(prix_catalogue * (1.0 - discount_proposed_pct / 100.0), 2)

    if prix_simule < cout:
        journal.avertissement("pricing_prix_sous_cout", produit_key=produit_key,
                              prix_simule=prix_simule, cout=cout,
                              remise_pct=discount_proposed_pct)
        raise PriceBelowCostError(prix_simule, cout)

    volume = _predire_volume(produit_key)

    marge_unitaire = prix_simule - cout
    chiffre_affaires = volume * prix_simule
    marge = volume * marge_unitaire

    modele_entry = REGISTRY.model_entry("pricing", VOLUME_TARGET) or {}
    modele = modele_entry.get("model_name", "baseline_mediane_produit")
    statut = modele_entry.get("status", "unknown")

    volume_nul = volume == 0.0
    message = None
    if volume_nul:
        message = (
            "La mediane historique de ventes hebdomadaires de ce produit est nulle : "
            "il s'agit d'un produit a rotation lente, dont la valeur mediane predite "
            "est reellement zero. Ce n'est pas une erreur de calcul, mais la baseline "
            "mediane n'apporte aucune information exploitable pour ce produit.")

    journal.info("pricing_simulation", produit_key=produit_key,
                 remise_pct=discount_proposed_pct, prix_simule=prix_simule,
                 volume=volume, volume_nul=volume_nul,
                 chiffre_affaires=chiffre_affaires, marge=marge)

    return PricingOutcome(
        produit_key=produit_key, categorie=entry["categorie"], classe_abc=entry["classe_abc"],
        prix_catalogue_xof=prix_catalogue, cout_xof=cout,
        remise_proposee_pct=discount_proposed_pct, prix_simule_xof=prix_simule,
        volume_estime_unites_7j=round(volume, 3),
        chiffre_affaires_estime_xof=round(chiffre_affaires, 2),
        marge_estimee_xof=round(marge, 2),
        marge_unitaire_xof=round(marge_unitaire, 2),
        volume_nul=volume_nul,
        modele=modele, modele_statut=statut,
        version=modele_entry.get("version", "unknown"),
        garde_fous={"prix_sous_cout": False, "marge_unitaire_negative": marge_unitaire < 0,
                    "marge_totale_negative": marge < 0},
        message=message,
    )


def catalogue_complet() -> list[dict]:
    """Liste plate des produits pricing, pour consommation analytique.

    Meme source que la simulation : catalogue produit et volume median predit
    par la baseline. Le volume est calcule en une seule passe pour les 300
    produits. Aucune remise n'est appliquee ici : la marge unitaire donnee est
    celle au prix catalogue, servant de point de reference.

    Une valeur nulle de volume est une prediction reelle (produit a rotation
    lente) et non un echec ; le champ `volume_nul` la signale explicitement.
    """
    catalogue = REGISTRY.pricing_catalog
    if not catalogue:
        return []

    cles = sorted(catalogue)
    modele = REGISTRY.pricing_models.get(VOLUME_TARGET)
    volumes: dict[str, float | None] = {k: None for k in cles}
    if modele is not None:
        try:
            frame = pd.DataFrame({"produit_key": cles})
            predits = predict_pricing(modele, frame)
            for cle, valeur in zip(cles, predits):
                brut = float(valeur)
                volumes[cle] = brut if math.isfinite(brut) and brut >= 0 else None
        except Exception as exc:  # noqa: BLE001 - liste servie sans volume plutot qu'erreur globale
            journal.erreur("pricing_catalogue_volume_indisponible", detail=str(exc))

    lignes = []
    for cle in cles:
        entree = catalogue[cle]
        prix = float(entree["prix_base_xof"])
        cout = float(entree["cout_xof"])
        volume = volumes[cle]
        lignes.append({
            "produit_key": cle,
            "categorie": entree["categorie"],
            "classe_abc": entree["classe_abc"],
            "prix_catalogue_xof": prix,
            "cout_xof": cout,
            "marge_unitaire_prix_catalogue_xof": round(prix - cout, 2),
            "taux_marge_prix_catalogue": round((prix - cout) / prix, 6) if prix else None,
            "volume_median_estime_7j": None if volume is None else round(volume, 3),
            "volume_nul": None if volume is None else volume == 0.0,
        })
    return lignes
