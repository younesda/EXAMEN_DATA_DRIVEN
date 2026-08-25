"""Service de scoring recommandation de l'API produit V4.

Construit le vecteur de features exactement dans l'ordre attendu par les
modeles entraines (`src.recsys_v4.dataset.ALL_FEATURES`), a partir :
- du contexte fourni par l'appelant (client, appareil, source, canal) ;
- de l'instantane produit fige a la fin de la fenetre d'entrainement
  (`api_v4/data/recommendation_catalog.json`).

Aucune lecture de base client en direct, aucun acces Supabase. Le repli sur
`popularite_globale_v1` est declenche automatiquement si le modele demande
echoue, n'est pas charge, ou si aucun produit candidat n'est reconnu.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from api_v4.config import FALLBACK_MODEL_NAME
from api_v4.registry import REGISTRY
from src.recsys_v4.dataset import ALL_FEATURES
from src.recsys_v4.models import predict as predict_recommendation

COLD_START_DEFAULTS = {
    "client_purchase_count_before": 0.0,
    "client_recency_days": 9999.0,
    "client_frequency_90d": 0.0,
    "client_category_affinity": 0.0,
}


class NoValidCandidatesError(Exception):
    """Aucun des produits candidats n'appartient au catalogue connu."""


@dataclass
class RecommendationOutcome:
    """Resultat d'un scoring.

    Distingue explicitement trois choses qui peuvent differer lors d'un repli :
    - `target` / `target_status` : la cible demandee et le statut du modele
      prevu pour elle ;
    - `model_requested` : le modele qui aurait ete utilise sans incident ;
    - `model_used` / `served_model_status` : le modele reellement servi et son
      propre statut.

    `status` est conserve pour compatibilite avec les consommateurs existants
    et vaut toujours `target_status`.
    """

    target: str
    model_used: str
    fallback_used: bool
    fallback_reason: str | None
    status: str
    version: str
    target_status: str
    model_requested: str
    served_model_status: str
    results: list[dict] = field(default_factory=list)
    dropped_products: list[str] = field(default_factory=list)


def _encode_context_value(mapping: dict, raw_value: str | None) -> int:
    value = raw_value if raw_value else "inconnu"
    if value not in mapping:
        value = "inconnu" if "inconnu" in mapping else next(iter(mapping), value)
    return int(mapping.get(value, 0))


def _build_feature_frame(candidate_products: list[str], context: dict) -> tuple[pd.DataFrame, list[str]]:
    catalog = REGISTRY.recommendation_catalog
    mappings = REGISTRY.categorical_mappings

    device_code = _encode_context_value(mappings.get("device", {}), context.get("device"))
    source_code = _encode_context_value(mappings.get("source", {}), context.get("source"))
    channel_code = _encode_context_value(mappings.get("channel", {}), context.get("channel"))
    is_anonymous = 0 if context.get("client_id") else 1
    is_cold_start = 1 if float(context.get("client_purchase_count_before", 0.0)) == 0.0 else 0

    rows, dropped = [], []
    for product_id in candidate_products:
        entry = catalog.get(product_id)
        if entry is None:
            dropped.append(product_id)
            continue
        rows.append({
            "produit_key": product_id,
            "category_code": entry["category_code"],
            "brand_code": entry["brand_code"],
            "device_code": device_code,
            "source_code": source_code,
            "channel_code": channel_code,
            "prix_base_xof": entry["prix_base_xof"],
            "client_purchase_count_before": float(context.get("client_purchase_count_before", 0.0)),
            "client_recency_days": float(context.get("client_recency_days", 9999.0)),
            "client_frequency_90d": float(context.get("client_frequency_90d", 0.0)),
            "client_category_affinity": float(context.get("client_category_affinity", 0.0)),
            "product_popularity_before": entry["product_popularity_before"],
            "product_recent_popularity_28d": entry["product_recent_popularity_28d"],
            "is_anonymous": is_anonymous,
            "is_cold_start_client": is_cold_start,
        })
    frame = pd.DataFrame(rows, columns=["produit_key", *ALL_FEATURES]) if rows else pd.DataFrame()
    return frame, dropped


def _rank(products: list[str], scores: np.ndarray) -> list[dict]:
    order = np.argsort(-np.asarray(scores, dtype=float))
    return [{"product_id": products[position], "score": round(float(scores[position]), 6), "rank": rank}
           for rank, position in enumerate(order, start=1)]


def _fallback_popularity(products: list[str]) -> list[dict]:
    catalog = REGISTRY.recommendation_catalog
    scores = np.array([catalog.get(product, {}).get("product_popularity_before", 0.0) for product in products])
    return _rank(products, scores)


def _fallback_outcome(target: str, reason: str, target_status: str, model_requested: str,
                      version: str, products: list[str], dropped: list[str]) -> RecommendationOutcome:
    return RecommendationOutcome(
        target=target, model_used=FALLBACK_MODEL_NAME, fallback_used=True,
        fallback_reason=reason, status=target_status, version=version,
        target_status=target_status, model_requested=model_requested,
        served_model_status=REGISTRY.status_of_model_name("recommendation", FALLBACK_MODEL_NAME),
        results=_fallback_popularity(products), dropped_products=dropped)


def score_target(target: str, candidate_products: list[str], context: dict) -> RecommendationOutcome:
    target_status = REGISTRY.model_status("recommendation", target)
    version = REGISTRY.model_version("recommendation", target)
    model_requested = REGISTRY.model_name_for_target("recommendation", target)

    frame, dropped = _build_feature_frame(candidate_products, context)
    if frame.empty:
        raise NoValidCandidatesError(
            "aucun des produits candidats n'appartient au catalogue connu : " + ", ".join(dropped))

    model = REGISTRY.recommendation_models.get(target)
    if model is None:
        return _fallback_outcome(target, "modele_indisponible", target_status, model_requested,
                                 version, frame.produit_key.tolist(), dropped)

    try:
        scores = predict_recommendation(model, frame)
        scores = np.asarray(scores, dtype=float)
        if scores.shape[0] != len(frame) or not np.all(np.isfinite(scores)):
            raise ValueError("scores non valides retournes par le modele")
    except Exception:  # noqa: BLE001 - tout echec de scoring declenche le repli, sans propager l'erreur
        return _fallback_outcome(target, "echec_scoring", target_status, model_requested,
                                 version, frame.produit_key.tolist(), dropped)

    results = _rank(frame.produit_key.tolist(), scores)
    return RecommendationOutcome(
        target=target, model_used=model.name, fallback_used=False, fallback_reason=None,
        status=target_status, version=version, target_status=target_status,
        model_requested=model_requested, served_model_status=target_status,
        results=results, dropped_products=dropped)


def catalogue_complet() -> list[dict]:
    """Liste plate des produits couverts par la recommandation.

    ATTENTION AU SENS : ce n'est PAS une liste de recommandations. Une
    recommandation est contextuelle — elle reclasse des candidats pour un
    client donne — et ne se resume pas a un classement fixe de produits.

    Ce que cette liste expose, ce sont les scores de POPULARITE qui
    alimentent `popularite_globale_v1`, le modele de repli : popularite
    cumulee et popularite recente sur 28 jours, figees a la fin de la fenetre
    d'entrainement. Utile pour un tableau de bord, jamais a presenter comme
    une recommandation personnalisee.
    """
    catalogue = REGISTRY.recommendation_catalog
    if not catalogue:
        return []

    lignes = []
    for cle in sorted(catalogue):
        entree = catalogue[cle]
        lignes.append({
            "produit_key": cle,
            "categorie": entree.get("categorie"),
            "prix_base_xof": entree.get("prix_base_xof"),
            "popularite_globale": entree.get("product_popularity_before"),
            "popularite_recente_28j": entree.get("product_recent_popularity_28d"),
        })
    # Rang de popularite, pour faciliter les tris cote tableau de bord.
    ordonnes = sorted(lignes, key=lambda l: (l["popularite_globale"] or 0), reverse=True)
    for rang, ligne in enumerate(ordonnes, start=1):
        ligne["rang_popularite_globale"] = rang
    return lignes
