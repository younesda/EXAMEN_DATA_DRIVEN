"""Dataset futur `client_product_interactions` — grain
``client/anonymous_id × produit × timestamp``.

**Non exécuté sur les données actuelles.** Ce module est du code prêt à tourner.

Les poids d'interaction sont **configurables et provisoires**. Aucun poids
définitif ne sera fixé avant une validation temporelle : les valeurs par défaut
ci-dessous sont un point de départ ordonné par intensité d'engagement, pas un
réglage validé. Les figer maintenant reviendrait à choisir des
hyperparamètres avant d'avoir la moindre mesure — exactement ce que le
protocole V2 interdit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from v2.data.builders.common import (
    exclure_bots_et_tests,
    exiger_colonnes,
    normaliser_timestamps,
)

COLONNES_REQUISES = ("event_timestamp", "event_type", "produit_key")


@dataclass(frozen=True)
class PoidsInteraction:
    """Poids par type d'événement, plus la pondération quantité et récence.

    ATTENTION : valeurs **provisoires**. Elles doivent être choisies par
    validation temporelle — estimées sur des fenêtres strictement antérieures à
    la fenêtre évaluée — et jamais ajustées après observation des résultats.
    """

    par_type: dict[str, float] = field(default_factory=lambda: {
        "view": 1.0, "click": 2.0, "add_to_cart": 3.0, "purchase": 5.0,
    })
    poids_quantite: float = 0.0        # 0 = quantité ignorée
    demi_vie_jours: float | None = None  # None = aucune décroissance temporelle
    valide_par_validation_temporelle: bool = False

    def poids_type(self, event_type: pd.Series) -> pd.Series:
        # Un type inconnu reçoit 0, pas une valeur par défaut arbitraire : il
        # ne doit pas peser sans avoir été explicitement pondéré.
        return event_type.map(self.par_type).fillna(0.0)


POIDS_PAR_DEFAUT = PoidsInteraction()

SCHEMA_SORTIE = {
    "identite": "text — client_key si connu, sinon anonymous_id",
    "type_identite": "text — 'client' ou 'anonyme'",
    "produit_key": "text — produit concerné",
    "event_timestamp": "timestamptz — horodatage de l'interaction, en UTC",
    "event_type": "text — type d'interaction",
    "quantity": "integer — quantité si applicable, sinon nulle",
    "poids_base": "numeric — poids du type d'événement",
    "poids_quantite": "numeric — contribution de la quantité",
    "poids_recence": "numeric — facteur de décroissance temporelle, 1.0 si désactivée",
    "poids_total": "numeric — poids final de l'interaction",
}


def build_client_product_interactions(
    web: pd.DataFrame,
    poids: PoidsInteraction = POIDS_PAR_DEFAUT,
    reference_recence: pd.Timestamp | None = None,
    exclure_bots: bool = True,
) -> pd.DataFrame:
    """Construit la table d'interactions pondérées.

    Args:
        web: `fact_evenements_web` enrichie.
        poids: configuration des poids. Provisoire tant que
            `valide_par_validation_temporelle` est faux.
        reference_recence: instant de référence de la décroissance. Doit être
            le **cutoff de la fenêtre évaluée**, jamais la date du jour : sinon
            une interaction postérieure au cutoff influencerait sa propre
            pondération.
        exclure_bots: exclusion du trafic robotique et interne.
    """
    exiger_colonnes(web, COLONNES_REQUISES, contexte="client_product_interactions")

    d = exclure_bots_et_tests(web) if exclure_bots else web.copy()
    if d.empty:
        return pd.DataFrame(columns=list(SCHEMA_SORTIE))

    d["event_timestamp"] = normaliser_timestamps(d["event_timestamp"], "event_timestamp")
    d = d.dropna(subset=["produit_key", "event_timestamp"])

    client = d["client_key"] if "client_key" in d.columns else pd.Series(np.nan, index=d.index)
    anonyme = d["anonymous_id"] if "anonymous_id" in d.columns else pd.Series(np.nan, index=d.index)
    d["identite"] = client.fillna(anonyme)
    d["type_identite"] = np.where(client.notna(), "client", "anonyme")
    # Une interaction rattachable à personne n'est pas exploitable et n'est pas
    # inventée : elle est écartée, et le fait est mesurable par différence.
    d = d[d["identite"].notna()]

    d["poids_base"] = poids.poids_type(d["event_type"])

    if poids.poids_quantite and "quantity" in d.columns:
        d["poids_quantite"] = poids.poids_quantite * d["quantity"].fillna(0).astype(float)
    else:
        d["poids_quantite"] = 0.0

    d["poids_recence"] = _facteur_recence(d["event_timestamp"], poids, reference_recence)
    d["poids_total"] = (d["poids_base"] + d["poids_quantite"]) * d["poids_recence"]

    colonnes = [c for c in SCHEMA_SORTIE if c in d.columns]
    return d[colonnes].sort_values(["identite", "produit_key", "event_timestamp"]).reset_index(drop=True)


def _facteur_recence(
    ts: pd.Series, poids: PoidsInteraction, reference: pd.Timestamp | None
) -> pd.Series:
    if poids.demi_vie_jours is None:
        return pd.Series(1.0, index=ts.index)
    if reference is None:
        raise ValueError(
            "Une décroissance de récence est demandée sans instant de référence. "
            "La référence doit être le cutoff de la fenêtre évaluée : utiliser la date du "
            "jour ferait dépendre la pondération d'informations postérieures au cutoff."
        )
    age_jours = (pd.Timestamp(reference) - ts).dt.total_seconds() / 86400.0
    # Les interactions postérieures au cutoff auraient un âge négatif et donc un
    # poids amplifié : elles sont neutralisées plutôt que d'être silencieusement
    # sur-pondérées. Leur présence est un défaut de filtrage en amont.
    age_jours = age_jours.clip(lower=0.0)
    return np.power(0.5, age_jours / poids.demi_vie_jours)


def agreger_par_couple(interactions: pd.DataFrame) -> pd.DataFrame:
    """Matrice identité × produit, poids cumulés — entrée d'un collaboratif."""
    exiger_colonnes(interactions, ("identite", "produit_key", "poids_total"),
                    contexte="agreger_par_couple")
    return (interactions.groupby(["identite", "produit_key"], as_index=False)
            .agg(poids_cumule=("poids_total", "sum"),
                 n_interactions=("poids_total", "size"),
                 derniere_interaction=("event_timestamp", "max"))
            .sort_values(["identite", "poids_cumule"], ascending=[True, False])
            .reset_index(drop=True))
