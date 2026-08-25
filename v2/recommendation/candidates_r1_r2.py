"""Candidats R1 et R2 — Recommandation V2.

**R1 — popularité régularisée**

    score = α × popularité_globale + (1−α) × popularité_récente

Les valeurs de α sont fixées à l'avance (``ALPHA_GRID``). Pour une fenêtre
donnée, le choix de α n'utilise que les fenêtres strictement antérieures ; la
première fenêtre applique ``ALPHA_DEFAUT``, fixé a priori.

**R2 — reranking de diversité**

Repart du classement R1 et applique trois mécanismes, tous paramétrés a
priori :

1. **Plafond de concentration par catégorie** : au plus ``MAX_PAR_CATEGORIE``
   produits d'une même catégorie dans le Top-K.
2. **Pénalité d'omniprésence** : un produit déjà recommandé à une grande part
   des clients voit son score réduit — c'est ce qui attaque directement la
   couverture catalogue de 5,4 % de la V1.
3. **Diversité minimale** : au moins ``MIN_CATEGORIES_TOP10`` catégories
   distinctes dans le Top-10 lorsque les candidats le permettent.

Toutes les popularités sont calculées **sur le train de la fenêtre
uniquement**. Aucune information postérieure au cutoff n'intervient.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# --- Paramètres fixés A PRIORI ---
ALPHA_GRID: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
ALPHA_DEFAUT = 0.5
FENETRE_RECENTE_JOURS = 60

MAX_PAR_CATEGORIE = 3
MIN_CATEGORIES_TOP10 = 4
PENALITE_OMNIPRESENCE = 0.5   # force de la pénalité appliquée aux produits sur-recommandés
SEUIL_OMNIPRESENCE = 0.30     # produit recommandé à plus de 30 % des clients = omniprésent


@dataclass(frozen=True)
class R1Spec:
    mode: str = "expanding"          # "expanding" (α sur fenêtres antérieures) ou "fixe"
    alpha_fixe: float | None = None

    @property
    def name(self) -> str:
        return "R1_popularite_regularisee" if self.mode == "expanding" else f"R1_alpha_fixe_{self.alpha_fixe:.2f}"


@dataclass(frozen=True)
class R2Spec:
    max_par_categorie: int = MAX_PAR_CATEGORIE
    min_categories_top10: int = MIN_CATEGORIES_TOP10
    penalite: float = PENALITE_OMNIPRESENCE
    seuil_omnipresence: float = SEUIL_OMNIPRESENCE

    @property
    def name(self) -> str:
        return "R2_reranking_diversite"


# =============================================================================
# Scores de popularité (train uniquement)
# =============================================================================
def popularity_scores(train_ventes: pd.DataFrame, cutoff, window_days: int | None = None) -> dict[str, float]:
    """Popularité = nombre de clients distincts ayant acheté, normalisée à 1."""
    df = train_ventes
    if window_days is not None:
        df = df[df["date_complete"] > cutoff - pd.Timedelta(days=window_days)]
    s = df.groupby("produit_key")["client_key"].nunique()
    if s.empty or s.max() == 0:
        return {}
    return (s / s.max()).to_dict()


def blended_scores(pop_global: dict, pop_recent: dict, alpha: float, produits: list[str]) -> dict[str, float]:
    return {
        p: alpha * pop_global.get(p, 0.0) + (1 - alpha) * pop_recent.get(p, 0.0)
        for p in produits
    }


# =============================================================================
# R1 — choix de α sur les fenêtres antérieures uniquement
# =============================================================================
def _recall_at_k(recs: dict[str, list[str]], relevant: dict[str, set[str]], k: int = 10) -> float:
    vals = []
    for client, rel in relevant.items():
        if not rel:
            continue
        top = recs.get(client, [])[:k]
        vals.append(sum(1 for p in top if p in rel) / len(rel))
    return float(np.mean(vals)) if vals else float("nan")


def choose_alpha_from_previous_windows(history_evals: dict[int, dict[float, float]], current_window: int) -> tuple[float, dict]:
    """`history_evals` : {fenetre: {alpha: recall@10}} pour les fenêtres déjà évaluées."""
    prior = {w: d for w, d in history_evals.items() if w < current_window}
    if not prior:
        return ALPHA_DEFAUT, {"source": "defaut_aucune_fenetre_anterieure", "fenetres_utilisees": []}
    moyennes = {a: float(np.mean([d[a] for d in prior.values()])) for a in ALPHA_GRID}
    best = max(moyennes, key=moyennes.get)
    return best, {
        "source": "fenetres_anterieures",
        "fenetres_utilisees": sorted(prior.keys()),
        "recall_par_alpha": {f"{k:.2f}": round(v, 6) for k, v in moyennes.items()},
    }


# =============================================================================
# R2 — reranking de diversité
# =============================================================================
def rerank_diversity(
    ranked: list[tuple[str, float]],
    produit_categorie: dict[str, str],
    exposure: dict[str, float],
    spec: R2Spec,
    k: int = 10,
) -> list[tuple[str, float]]:
    """Reranking glouton sous contraintes de diversité.

    `exposure` : part de clients à qui le produit a déjà été recommandé dans
    cette fenêtre (calculée au fil de l'eau, jamais depuis le futur).
    """
    # 1. Pénalité d'omniprésence appliquée au score
    penalises = []
    for produit, score in ranked:
        expo = exposure.get(produit, 0.0)
        if expo > spec.seuil_omnipresence:
            score = score * (1 - spec.penalite * (expo - spec.seuil_omnipresence) / (1 - spec.seuil_omnipresence))
        penalises.append((produit, score))
    penalises.sort(key=lambda kv: kv[1], reverse=True)

    # 2. Sélection gloutonne sous plafond par catégorie
    selection: list[tuple[str, float]] = []
    par_categorie: dict[str, int] = {}
    reste: list[tuple[str, float]] = []
    for produit, score in penalises:
        if len(selection) >= k:
            break
        cat = produit_categorie.get(produit, "_inconnue")
        if par_categorie.get(cat, 0) >= spec.max_par_categorie:
            reste.append((produit, score))
            continue
        selection.append((produit, score))
        par_categorie[cat] = par_categorie.get(cat, 0) + 1

    # 3. Diversité minimale : si trop peu de catégories, on force l'entrée de
    #    produits de catégories absentes (en remplaçant les derniers rangs).
    cats_presentes = {produit_categorie.get(p, "_inconnue") for p, _ in selection}
    if len(cats_presentes) < spec.min_categories_top10:
        for produit, score in penalises:
            if len(cats_presentes) >= spec.min_categories_top10:
                break
            cat = produit_categorie.get(produit, "_inconnue")
            if cat in cats_presentes or any(p == produit for p, _ in selection):
                continue
            if selection:
                selection[-1] = (produit, score)
            else:
                selection.append((produit, score))
            cats_presentes.add(cat)

    # 4. Complément si le plafond a laissé des trous
    if len(selection) < k:
        deja = {p for p, _ in selection}
        for produit, score in reste + penalises:
            if len(selection) >= k:
                break
            if produit not in deja:
                selection.append((produit, score))
                deja.add(produit)

    return selection[:k]
