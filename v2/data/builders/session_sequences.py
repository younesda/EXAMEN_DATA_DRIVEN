"""Dataset futur `session_sequences` — grain ``session_id × événement ordonné``.

**Non exécuté sur les données actuelles.** `fact_evenements_web` n'a
aujourd'hui ni `session_id` ni `event_timestamp` : les événements ne sont datés
qu'au jour, donc ni ordonnables ni regroupables en parcours. Ce module est du
code prêt à tourner.

Aucun repli ne reconstruit des sessions en groupant par ``(client, jour)`` :
cela fabriquerait des sessions qui n'ont jamais existé, et la durée qu'on en
tirerait n'aurait aucun sens.

Usages prévus :

* parcours vue → clic → ajout au panier → achat ;
* durée de session et temps entre événements ;
* intention récente (derniers produits vus avant le cutoff) ;
* attribution anonyme → authentifiée ;
* exclusion stricte des bots et du trafic de test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from v2.data.builders.common import (
    exclure_bots_et_tests,
    exiger_colonnes,
    normaliser_timestamps,
)

COLONNES_REQUISES = ("session_id", "event_timestamp", "event_type", "event_id")

# Ordre canonique de l'entonnoir. Sert à qualifier la progression d'une session,
# jamais à supposer qu'un événement manquant a eu lieu.
ORDRE_ENTONNOIR = {"view": 1, "click": 2, "add_to_cart": 3, "purchase": 4}

SCHEMA_SORTIE = {
    "session_id": "text — identifiant de session",
    "rang_evenement": "integer — position 1..n dans la session, par ordre chronologique",
    "event_id": "text — identifiant de l'événement",
    "event_timestamp": "timestamptz — horodatage, converti en UTC",
    "event_type": "text — type d'événement",
    "order_id": "text — commande portée uniquement par purchase",
    "quantity": "integer — quantité portée uniquement par purchase",
    "produit_key": "text — produit concerné, nul si l'événement n'en vise aucun",
    "client_key": "text — client si authentifié à cet instant, sinon nul",
    "anonymous_id": "text — identifiant de navigateur",
    "identite_effective": "text — client_key si connu à un moment de la session, sinon anonymous_id",
    "session_authentifiee": "boolean — la session contient au moins un événement authentifié",
    "secondes_depuis_debut": "numeric — écart au premier événement de la session",
    "secondes_depuis_precedent": "numeric — écart à l'événement précédent",
    "duree_session_secondes": "numeric — durée totale de la session",
    "n_evenements_session": "integer — nombre d'événements de la session",
    "etape_entonnoir": "integer — rang canonique du type d'événement",
    "etape_max_session": "integer — étape la plus avancée atteinte dans la session",
    "session_convertie": "boolean — la session contient un achat",
}


def build_session_sequences(
    web: pd.DataFrame, exclure_bots: bool = True
) -> pd.DataFrame:
    """Construit les parcours ordonnés au grain ``session_id × événement``.

    L'ordre est celui de `event_timestamp`, avec `event_id` en départage
    déterministe des ex æquo — deux événements au même horodatage ne doivent
    pas produire un ordre différent d'une exécution à l'autre.

    Raises:
        ColonnesManquantes: si `session_id` ou `event_timestamp` manque.
        ValueError: si les horodatages n'ont pas de fuseau.
    """
    exiger_colonnes(web, COLONNES_REQUISES, contexte="session_sequences")

    d = exclure_bots_et_tests(web) if exclure_bots else web.copy()
    if d.empty:
        return pd.DataFrame(columns=list(SCHEMA_SORTIE))

    d["event_timestamp"] = normaliser_timestamps(d["event_timestamp"], "event_timestamp")
    d = d.dropna(subset=["session_id", "event_timestamp"])
    d = d.sort_values(["session_id", "event_timestamp", "event_id"]).reset_index(drop=True)

    g = d.groupby("session_id", sort=False)
    d["rang_evenement"] = g.cumcount() + 1
    d["n_evenements_session"] = g["event_id"].transform("size")

    debut = g["event_timestamp"].transform("min")
    fin = g["event_timestamp"].transform("max")
    d["secondes_depuis_debut"] = (d["event_timestamp"] - debut).dt.total_seconds()
    d["secondes_depuis_precedent"] = g["event_timestamp"].diff().dt.total_seconds()
    d["duree_session_secondes"] = (fin - debut).dt.total_seconds()

    d["etape_entonnoir"] = d["event_type"].map(ORDRE_ENTONNOIR)
    d["etape_max_session"] = g["etape_entonnoir"].transform("max")
    d["session_convertie"] = d["etape_max_session"] >= ORDRE_ENTONNOIR["purchase"]

    d = _attribuer_identite(d)
    colonnes = [c for c in SCHEMA_SORTIE if c in d.columns]
    return d[colonnes].reset_index(drop=True)


def _attribuer_identite(d: pd.DataFrame) -> pd.DataFrame:
    """Rattache les événements anonymes d'une session au client qui s'y authentifie.

    Une session commence souvent anonyme puis devient authentifiée. Le
    rattachement est fait **à l'intérieur d'une session seulement** : propager
    une identité d'une session à l'autre via `anonymous_id` reviendrait à
    supposer qu'un appareil n'a qu'un seul utilisateur, ce qui est une
    hypothèse, pas une donnée. La règle de réconciliation inter-sessions doit
    venir du Data Engineer.
    """
    if "client_key" not in d.columns:
        d["identite_effective"] = d.get("anonymous_id")
        d["session_authentifiee"] = False
        return d

    client_session = d.groupby("session_id")["client_key"].transform(
        lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan
    )
    d["session_authentifiee"] = client_session.notna()
    anonyme = d["anonymous_id"] if "anonymous_id" in d.columns else pd.Series(np.nan, index=d.index)
    d["identite_effective"] = client_session.fillna(anonyme)
    return d


def intention_recente(
    sequences: pd.DataFrame, cutoff: pd.Timestamp, fenetre_heures: int = 24, k: int = 10
) -> pd.DataFrame:
    """Derniers produits vus par identité, **strictement avant** le cutoff.

    Le filtre est strict (`<`) : un événement survenu à l'instant exact du
    cutoff n'est pas considéré comme connu. C'est la même règle anti-fuite que
    celle appliquée en V1 au stock (`stock_disponible_lag1`).
    """
    exiger_colonnes(sequences, ("identite_effective", "event_timestamp", "produit_key"),
                    contexte="intention_recente")

    debut = cutoff - pd.Timedelta(hours=fenetre_heures)
    d = sequences[(sequences["event_timestamp"] < cutoff)
                  & (sequences["event_timestamp"] >= debut)]
    d = d.dropna(subset=["produit_key"])
    d = d.sort_values("event_timestamp", ascending=False)
    return (d.groupby("identite_effective").head(k)
            .loc[:, ["identite_effective", "produit_key", "event_timestamp", "event_type"]]
            .reset_index(drop=True))
