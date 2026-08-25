"""Coeur de scoring du complement panier — source de verite unique.

Fuite corrigee le 2026-08-18
----------------------------
`complement_end_to_end.py` et `complement_candidate_pilot.py` derivaient la
categorie de scoring de la CIBLE MASQUEE :

    cat = g.loc[g.produit_key.eq(target), 'categorie'].iloc[0]

Les modeles `popularite_categorie`, `reference` et `rrf` recevaient donc la
categorie de l'article a deviner. Effet apparie mesure : NDCG@10 +0,1598,
IC95 [0,1556 ; 0,1639], soit un facteur 7.

Deux invariants sont desormais imposes par construction :

1. **Contexte seul.** `candidate_scores` recoit `context` et
   `context_categories`. L'article masque ne fournit ni categorie, ni marque,
   ni prix, ni aucun autre attribut. La signature ne comporte aucun parametre
   permettant de transmettre la cible.
2. **Departage neutre.** La cible du protocole est `sorted(items)[0]`,
   l'article alphabetiquement premier du panier. Un depart alphabetique des
   ex aequo l'avantage donc mecaniquement. `rank` departage par score, puis
   popularite, puis une permutation deterministe des references.

Tous les chemins d'evaluation du complement panier doivent importer ce module.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd

SEED = 42
RRF_K = 60
KS_DEFAULT = (5, 10, 20)
#: Generateurs honnetes fusionnes par le RRF.
RRF_SOURCES = ("cooccurrence_item_item", "bm25_panier", "association_lift",
               "popularite_categorie_contexte", "popularite_globale")


def tiebreak_order(products) -> dict[str, int]:
    """Permutation deterministe, independante de l'ordre lexical."""
    items = sorted(dict.fromkeys(products))
    rng = np.random.default_rng(SEED)
    return {item: int(position) for item, position in zip(items, rng.permutation(len(items)))}


def train_statistics(frame: pd.DataFrame):
    """Statistiques apprises sur les commandes strictement anterieures au test."""
    cooccurrence: dict[str, Counter] = defaultdict(Counter)
    popularity: Counter = Counter()
    category_popularity: dict[str, Counter] = defaultdict(Counter)
    for _, group in frame.groupby("order_id"):
        items = list(dict.fromkeys(group.produit_key))
        popularity.update(items)
        for item in items:
            cooccurrence[item].update(other for other in items if other != item)
        for category, sub in group.groupby("categorie"):
            category_popularity[category].update(sub.produit_key)
    return cooccurrence, popularity, category_popularity


def candidate_scores(context: set[str], context_categories, cooccurrence,
                     popularity, category_popularity) -> dict[str, Counter]:
    """Scores de tous les generateurs honnetes.

    La signature ne recoit **que** le contexte observe : il est structurellement
    impossible d'y passer la cible ou l'un de ses attributs.
    """
    coo: Counter = Counter()
    for item in context:
        for other, value in cooccurrence.get(item, {}).items():
            coo[other] += float(value)
    bm25 = Counter({x: v / (1.0 + np.log1p(popularity[x])) for x, v in coo.items()})
    association = Counter({x: v / max(popularity[x], 1) for x, v in coo.items()})
    category: Counter = Counter()
    for name in context_categories:
        for x, v in category_popularity.get(name, {}).items():
            category[x] += float(v)
    global_popularity = Counter({x: float(v) for x, v in popularity.items()})
    return {"popularite_globale": global_popularity,
            "cooccurrence_item_item": coo,
            "bm25_panier": bm25,
            "association_lift": association,
            "popularite_categorie_contexte": category}


def reciprocal_rank_fusion(scores: dict[str, Counter], context: set[str],
                           popularity: Counter, tiebreak: dict[str, int],
                           sources=RRF_SOURCES, k: int = RRF_K) -> Counter:
    """RRF standard : somme des 1/(k + rang) sur les generateurs honnetes."""
    fused: Counter = Counter()
    for name in sources:
        ordered = rank(scores[name], context, popularity, tiebreak, k=len(popularity))
        for position, item in enumerate(ordered, 1):
            fused[item] += 1.0 / (k + position)
    return fused


def rank(scores: Counter, context: set[str], popularity: Counter,
         tiebreak: dict[str, int], k: int) -> list[str]:
    """Classement unique, applique identiquement a tous les modeles.

    Seuls les scores strictement positifs sont retenus ; les places restantes
    sont completees par la popularite globale. Les ex aequo sont departages par
    popularite puis par `tiebreak`, jamais par ordre lexical.
    """
    missing = [item for item in scores if item not in tiebreak]
    if missing:
        raise KeyError("References absentes de la table de departage : " + str(sorted(missing)[:5]))

    def key(item: str) -> tuple:
        return (-float(scores.get(item, 0.0)), -float(popularity.get(item, 0)), tiebreak[item])

    ordered = [item for item in sorted((y for y, v in scores.items() if v > 0 and y not in context),
                                       key=key)]
    if len(ordered) < k:
        chosen = set(ordered)
        fallback = sorted((y for y in popularity if y not in context and y not in chosen),
                          key=lambda y: (-float(popularity[y]), tiebreak[y]))
        ordered = ordered + fallback[:k - len(ordered)]
    return ordered[:k]


def evaluate_unit(top: list[str], target: str, ks=KS_DEFAULT) -> dict:
    """Une cible masquee par commande : Recall@k = HitRate@k."""
    position = top.index(target) if target in top else None
    row: dict[str, float] = {}
    for k in ks:
        hit = int(position is not None and position < k)
        row["recall@" + str(k)] = hit
        row["ndcg@" + str(k)] = (1.0 / np.log2(position + 2)) if hit else 0.0
    row["mrr"] = (1.0 / (position + 1)) if position is not None else 0.0
    return row


def masked_target(items) -> str:
    """Regle de masquage du protocole, inchangee pour rester comparable."""
    return sorted(dict.fromkeys(items))[0]


def score_all(context: set[str], context_categories, cooccurrence, popularity,
              category_popularity, tiebreak: dict[str, int]) -> dict[str, Counter]:
    """Tous les generateurs honnetes plus leur fusion RRF."""
    scores = candidate_scores(context, context_categories, cooccurrence,
                              popularity, category_popularity)
    scores["rrf_contexte"] = reciprocal_rank_fusion(scores, context, popularity, tiebreak)
    return scores
