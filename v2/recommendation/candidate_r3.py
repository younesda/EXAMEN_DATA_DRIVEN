"""Candidat R3 — personnalisation légère par catégorie, avec repli V1.

Principe : pour les seuls clients disposant d'un historique suffisant, on
remplace une partie du Top-10 de popularité par des produits issus de leurs
catégories préférées. Tous les autres clients (et le cold-start) reçoivent
strictement la liste V1 — le repli est automatique, jamais un choix implicite.

**Seuils d'éligibilité, fixés AVANT toute évaluation :**

* au moins ``MIN_ACHATS`` achats historiques ;
* au moins ``MIN_CATEGORIES`` catégories distinctes observées ;
* au moins ``PART_MIN_DOMINANTES`` des achats concentrés dans les catégories
  dominantes (sinon le profil est jugé trop diffus pour être exploitable).

**Trois mixes comparés**, également fixés a priori :

* ``MIX_10_0`` : Top-10 entièrement personnalisé ;
* ``MIX_5_5``  : 5 produits V1 + 5 produits des catégories préférées ;
* ``MIX_7_3``  : 7 produits V1 + 3 produits personnalisés.

Le mix appliqué à la fenêtre *k* est choisi **uniquement sur les fenêtres
antérieures** — ce ne sont pas des hyperparamètres réglés sur la fenêtre
courante.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# --- Seuils d'éligibilité fixés a priori ---
MIN_ACHATS = 3
MIN_CATEGORIES = 2
PART_MIN_DOMINANTES = 0.60

# --- Mixes fixés a priori : (n_v1, n_personnalise) sur un Top-10 ---
MIXES: dict[str, tuple[int, int]] = {
    "MIX_10_0": (0, 10),
    "MIX_5_5": (5, 5),
    "MIX_7_3": (7, 3),
}
MIX_DEFAUT = "MIX_7_3"  # le plus conservateur : appliqué quand aucune fenêtre antérieure n'existe


@dataclass(frozen=True)
class ClientProfile:
    eligible: bool
    categories_preferees: tuple[str, ...]
    n_achats: int
    n_categories: int
    part_dominantes: float
    raison_non_eligible: str | None = None


def build_client_profiles(train_ventes: pd.DataFrame) -> dict[str, ClientProfile]:
    """Profils calculés STRICTEMENT sur le train de la fenêtre.

    Les catégories dominantes sont les plus fréquentes cumulant au moins
    ``PART_MIN_DOMINANTES`` des achats du client.
    """
    profiles: dict[str, ClientProfile] = {}
    for client, g in train_ventes.groupby("client_key"):
        n_achats = len(g)
        parts = g["categorie"].value_counts(normalize=True)
        n_categories = len(parts)

        if n_achats < MIN_ACHATS:
            profiles[client] = ClientProfile(False, (), n_achats, n_categories, 0.0, "moins_de_3_achats")
            continue
        if n_categories < MIN_CATEGORIES:
            profiles[client] = ClientProfile(False, (), n_achats, n_categories, 0.0, "moins_de_2_categories")
            continue

        # Catégories dominantes : on empile jusqu'à atteindre le seuil de concentration.
        cumul, dominantes = 0.0, []
        for cat, part in parts.items():
            dominantes.append(cat)
            cumul += part
            if cumul >= PART_MIN_DOMINANTES:
                break

        # Le profil n'est exploitable que si les dominantes sont réellement
        # concentrées : si elles couvrent toutes les catégories du client, le
        # profil est diffus et n'apporte pas d'information.
        if len(dominantes) >= n_categories and n_categories > 2:
            profiles[client] = ClientProfile(
                False, (), n_achats, n_categories, cumul, "profil_trop_diffus"
            )
            continue

        profiles[client] = ClientProfile(True, tuple(dominantes), n_achats, n_categories, cumul)
    return profiles


def recommend_r3(
    client: str,
    profiles: dict[str, ClientProfile],
    v1_ranking: list[str],
    scores: dict[str, float],
    produit_categorie: dict[str, str],
    candidates: list[str],
    mix: str,
    k: int = 10,
) -> tuple[list[str], str]:
    """Retourne (top_k, source) où `source` vaut 'personnalise' ou 'repli_v1'."""
    profile = profiles.get(client)
    if profile is None or not profile.eligible:
        return v1_ranking[:k], "repli_v1"

    n_v1, n_perso = MIXES[mix]
    cats = set(profile.categories_preferees)

    perso_pool = [p for p in candidates if produit_categorie.get(p) in cats]
    perso_pool.sort(key=lambda p: scores.get(p, 0.0), reverse=True)

    selection: list[str] = []
    for p in v1_ranking[:n_v1]:
        if p not in selection:
            selection.append(p)
    for p in perso_pool:
        if len(selection) >= k:
            break
        if p not in selection:
            selection.append(p)
    # Complément par la liste V1 si les catégories préférées manquent de produits.
    for p in v1_ranking:
        if len(selection) >= k:
            break
        if p not in selection:
            selection.append(p)

    return selection[:k], "personnalise"


def choose_mix_from_previous_windows(
    history: dict[int, dict[str, float]], current_window: int
) -> tuple[str, dict]:
    """Mix retenu = celui de meilleure NDCG@10 moyenne sur les fenêtres
    strictement antérieures. Aucune information de la fenêtre courante."""
    prior = {w: d for w, d in history.items() if w < current_window}
    if not prior:
        return MIX_DEFAUT, {"source": "defaut_aucune_fenetre_anterieure", "fenetres_utilisees": []}
    moyennes = {m: float(np.mean([d[m] for d in prior.values()])) for m in MIXES}
    best = max(moyennes, key=moyennes.get)
    return best, {
        "source": "fenetres_anterieures",
        "fenetres_utilisees": sorted(prior.keys()),
        "ndcg_par_mix": {k: round(v, 6) for k, v in moyennes.items()},
    }
