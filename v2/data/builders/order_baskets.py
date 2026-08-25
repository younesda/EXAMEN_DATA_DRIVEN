"""Dataset futur `order_baskets` — grain ``order_id × produit``.

**Non exécuté sur les données actuelles.** `fact_ventes` ne contient aucun
`order_id` aujourd'hui : le panier réel n'existe pas encore. Ce module est du
code prêt à tourner, pas un dataset produit.

Le garde-fou ``exiger_colonnes`` fait échouer l'appel si `order_id` est absent.
Il n'existe volontairement **aucun repli** groupant par ``(client, jour)`` :
cette heuristique fusionnerait des commandes distinctes passées le même jour et
fabriquerait des paniers qui n'ont jamais existé. Une hypothèse ne remplace pas
une donnée.

Usages prévus :

* panier réel et taille du panier ;
* produits achetés ensemble (co-occurrences, règles d'association, item-item) ;
* quantité et montant par ligne et par commande ;
* diversité de catégories dans la commande ;
* exclusion des annulations et des retours.
"""

from __future__ import annotations

import pandas as pd

from v2.data.builders.common import (
    STATUTS_EXCLUS_PAR_DEFAUT,
    exiger_colonnes,
    masque_lignes_valides,
)

COLONNES_REQUISES = ("order_id", "produit_key", "client_key", "quantite", "montant_net_xof")

SCHEMA_SORTIE = {
    "order_id": "text — identifiant de commande",
    "client_key": "text — client de la commande",
    "produit_key": "text — produit de la ligne",
    "categorie": "text — catégorie du produit, jointe depuis dim_produit",
    "date_commande": "timestamptz — date de la commande",
    "quantite": "integer — quantité de la ligne",
    "montant_net_xof": "numeric — montant net de la ligne",
    "taille_panier_lignes": "integer — nombre de lignes distinctes de la commande",
    "taille_panier_unites": "integer — somme des quantités de la commande",
    "montant_commande_xof": "numeric — montant total de la commande",
    "n_categories_commande": "integer — nombre de catégories distinctes dans la commande",
    "est_multi_produit": "boolean — la commande porte plus d'une ligne",
}


def build_order_baskets(
    ventes: pd.DataFrame,
    produits: pd.DataFrame | None = None,
    statuts_exclus: tuple[str, ...] = STATUTS_EXCLUS_PAR_DEFAUT,
    exclure_retours: bool = True,
) -> pd.DataFrame:
    """Construit le panier réel au grain ``order_id × produit``.

    Args:
        ventes: `fact_ventes` enrichie, avec au minimum `COLONNES_REQUISES`.
        produits: `dim_produit`, pour la catégorie. Optionnelle : sans elle, la
            colonne `categorie` est absente plutôt que remplie d'une valeur
            inventée.
        statuts_exclus: statuts de commande retirés du panier.
        exclure_retours: retire les lignes marquées `is_retour`.

    Raises:
        ValueError: si une colonne requise manque. Aucun repli heuristique.
    """
    exiger_colonnes(ventes, COLONNES_REQUISES, contexte="order_baskets")

    d = ventes[masque_lignes_valides(ventes, statuts_exclus, exclure_retours)].copy()
    if d.empty:
        return pd.DataFrame(columns=list(SCHEMA_SORTIE))

    if ("categorie" not in d.columns and produits is not None
            and {"produit_key", "categorie"} <= set(produits.columns)):
        d = d.merge(produits[["produit_key", "categorie"]].drop_duplicates("produit_key"),
                    on="produit_key", how="left")

    # Agrégation au grain order_id x produit : une commande peut porter deux
    # lignes du même produit (ajouts successifs). Les fusionner est un choix
    # explicite, et il est documenté dans le schéma de sortie.
    cles = ["order_id", "produit_key"]
    agg = {"quantite": "sum", "montant_net_xof": "sum", "client_key": "first"}
    if "categorie" in d.columns:
        agg["categorie"] = "first"
    if "date_commande" in d.columns:
        agg["date_commande"] = "min"
    lignes = d.groupby(cles, as_index=False).agg(agg)

    par_commande = lignes.groupby("order_id").agg(
        taille_panier_lignes=("produit_key", "nunique"),
        taille_panier_unites=("quantite", "sum"),
        montant_commande_xof=("montant_net_xof", "sum"),
    )
    if "categorie" in lignes.columns:
        par_commande["n_categories_commande"] = lignes.groupby("order_id")["categorie"].nunique()

    out = lignes.merge(par_commande, on="order_id", how="left")
    out["est_multi_produit"] = out["taille_panier_lignes"] > 1
    return out.sort_values(["order_id", "produit_key"]).reset_index(drop=True)


def co_occurrences(baskets: pd.DataFrame, min_support: int = 1) -> pd.DataFrame:
    """Paires de produits achetés dans une même commande.

    Chaque paire est ordonnée (produit_a < produit_b) pour n'être comptée
    qu'une fois. `min_support` est un plancher de comptage, pas un seuil de
    modèle : aucun paramètre de recommandation n'est fixé ici.
    """
    exiger_colonnes(baskets, ("order_id", "produit_key"), contexte="co_occurrences")

    paires = baskets[["order_id", "produit_key"]].drop_duplicates().merge(
        baskets[["order_id", "produit_key"]].drop_duplicates(),
        on="order_id", suffixes=("_a", "_b"),
    )
    paires = paires[paires["produit_key_a"] < paires["produit_key_b"]]
    out = (paires.groupby(["produit_key_a", "produit_key_b"]).size()
           .rename("n_commandes").reset_index())
    return out[out["n_commandes"] >= min_support].sort_values(
        "n_commandes", ascending=False
    ).reset_index(drop=True)
