"""Candidat B — sélection AutoETS / WindowAverage28 par segment.

Trois variantes, de la plus contrainte à la plus fine :

* **B1 — règle simple préétablie** : règle fixée *a priori* (avant de regarder
  le moindre résultat), fondée sur ce que la V1 avait déjà établi
  (`reports/23_rapport_final_forecasting.md` §6-7) : AutoETS domine en
  précision, WindowAverage28 est plus stable et meilleur sur les séries très
  intermittentes. Règle : WindowAverage28 si le taux de jours sans vente
  dépasse ``SEUIL_TAUX_ZEROS``, AutoETS sinon.
* **B2 — meilleur modèle par segment, appris sur les fenêtres antérieures** :
  pour chaque segment (classe ABC × profil de demande), on retient le modèle
  qui minimise la WAPE 30 j sur les fenêtres 1..k-1 seulement.
* **B3 — sélection par produit, fortement régularisée** : un produit ne peut
  s'écarter d'AutoETS que s'il dispose d'au moins ``MIN_VALIDATIONS`` fenêtres
  passées ET que WindowAverage28 y gagne d'une marge nette
  (``MARGE_REGULARISATION``). Sinon : AutoETS. Cette régularisation est
  volontairement sévère — avec au plus 5 fenêtres d'historique, une sélection
  par produit non contrainte sur-apprendrait immanquablement.

Aucun réentraînement : comme le candidat A, on sélectionne parmi les
prédictions V1 déjà figées. Toutes les variables de segmentation sont
calculées **sur le train de chaque fenêtre uniquement**.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

MODEL_A = "AutoETS"
MODEL_B = "WindowAverage28"

# --- Paramètres fixés A PRIORI (avant tout résultat) ---
SEUIL_TAUX_ZEROS = 0.60      # B1 : au-delà, la série est jugée très intermittente
MIN_VALIDATIONS = 2          # B3 : minimum de fenêtres passées pour autoriser un écart
MARGE_REGULARISATION = 0.10  # B3 : WindowAverage28 doit gagner ≥10 % relatif pour être retenu
MIN_OBS_SEGMENT = 20         # B2 : effectif minimal d'un segment pour lui faire confiance


class VariantB(str, Enum):
    B1_REGLE_SIMPLE = "B1_regle_simple_preetablie"
    B2_SEGMENT_APPRIS = "B2_meilleur_par_segment_fenetres_anterieures"
    B3_PAR_PRODUIT_REGULARISE = "B3_par_produit_regularise"


@dataclass(frozen=True)
class SegmentSpec:
    variant: VariantB

    @property
    def name(self) -> str:
        return f"candidat_b_{self.variant.value}"


def build_selection_frame(op: pd.DataFrame) -> pd.DataFrame:
    """Aligne les deux modèles côte à côte (même structure que le candidat A)."""
    a = op[op["model_requested"] == MODEL_A].rename(columns={"y_pred_final": "pred_autoets"})
    b = op[op["model_requested"] == MODEL_B].rename(columns={"y_pred_final": "pred_wa28"})
    merged = a.drop(columns=["model_requested"]).merge(
        b.drop(columns=["model_requested", "y"]), on=["unique_id", "ds", "window"], how="inner",
    )
    if len(merged) != len(a):
        raise ValueError("Alignement incomplet entre les deux modèles")
    return merged


def _wape_cumule_30j(frame: pd.DataFrame, pred_col: str) -> float:
    agg = frame.groupby(["unique_id", "window"])[["y", pred_col]].sum()
    denom = agg["y"].sum()
    if denom <= 0:
        return float("nan")
    return float(np.abs(agg[pred_col] - agg["y"]).sum() / denom)


# =============================================================================
# B1 — règle simple préétablie (aucun apprentissage)
# =============================================================================
def choose_b1(segments_window: pd.DataFrame) -> pd.Series:
    """WindowAverage28 si taux de zéros > seuil, AutoETS sinon.

    Le taux de zéros vient de la segmentation calculée sur le train de la
    fenêtre — aucune information du test n'intervient.
    """
    use_wa = segments_window["taux_jours_sans_vente"] > SEUIL_TAUX_ZEROS
    return pd.Series(np.where(use_wa, MODEL_B, MODEL_A), index=segments_window.index)


# =============================================================================
# B2 — meilleur modèle par segment, appris sur les fenêtres antérieures
# =============================================================================
def learn_b2_rule(history: pd.DataFrame) -> dict[tuple, str]:
    """Pour chaque (classe_abc, profil_demande), le modèle gagnant sur `history`.

    `history` ne contient que des fenêtres strictement antérieures. Un segment
    à effectif insuffisant retombe sur AutoETS (choix conservateur explicite).
    """
    if history.empty:
        return {}
    rule = {}
    for key, g in history.groupby(["classe_abc", "profil_demande"]):
        if g[["unique_id", "window"]].drop_duplicates().shape[0] < MIN_OBS_SEGMENT:
            rule[key] = MODEL_A
            continue
        w_a = _wape_cumule_30j(g, "pred_autoets")
        w_b = _wape_cumule_30j(g, "pred_wa28")
        rule[key] = MODEL_B if (np.isfinite(w_b) and w_b < w_a) else MODEL_A
    return rule


def apply_b2_rule(segments_window: pd.DataFrame, rule: dict[tuple, str]) -> pd.Series:
    keys = list(zip(segments_window["classe_abc"], segments_window["profil_demande"]))
    return pd.Series([rule.get(k, MODEL_A) for k in keys], index=segments_window.index)


# =============================================================================
# B3 — sélection par produit, fortement régularisée vers AutoETS
# =============================================================================
def learn_b3_rule(history: pd.DataFrame) -> dict[str, str]:
    """Par produit : WindowAverage28 seulement si (a) au moins MIN_VALIDATIONS
    fenêtres passées disponibles ET (b) il bat AutoETS d'au moins
    MARGE_REGULARISATION en relatif. Sinon AutoETS.
    """
    if history.empty:
        return {}
    rule = {}
    for uid, g in history.groupby("unique_id"):
        n_windows = g["window"].nunique()
        if n_windows < MIN_VALIDATIONS:
            rule[uid] = MODEL_A
            continue
        w_a = _wape_cumule_30j(g, "pred_autoets")
        w_b = _wape_cumule_30j(g, "pred_wa28")
        if not (np.isfinite(w_a) and np.isfinite(w_b)) or w_a <= 0:
            rule[uid] = MODEL_A
            continue
        gain_relatif = (w_a - w_b) / w_a
        rule[uid] = MODEL_B if gain_relatif >= MARGE_REGULARISATION else MODEL_A
    return rule


def apply_b3_rule(segments_window: pd.DataFrame, rule: dict[str, str]) -> pd.Series:
    return segments_window["unique_id"].map(lambda u: rule.get(u, MODEL_A))


# =============================================================================
# Exécution d'une variante
# =============================================================================
def run_candidate_b(spec: SegmentSpec, frame: pd.DataFrame, segments: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (prédictions, journal des décisions par fenêtre)."""
    enriched = frame.merge(segments, on=["unique_id", "window"], how="left")

    parts, decisions = [], []
    for window in sorted(enriched["window"].unique()):
        history = enriched[enriched["window"] < window]
        current = enriched[enriched["window"] == window].copy()

        # Une décision par (produit, fenêtre) : on travaille sur la table
        # dédupliquée, puis on rediffuse le choix sur les 30 jours.
        per_product = current.drop_duplicates("unique_id")[
            ["unique_id", "classe_abc", "profil_demande", "taux_jours_sans_vente"]
        ].set_index("unique_id")

        if spec.variant is VariantB.B1_REGLE_SIMPLE:
            choice = choose_b1(per_product)
            source = "regle_preetablie_aucun_apprentissage"
        elif spec.variant is VariantB.B2_SEGMENT_APPRIS:
            rule = learn_b2_rule(history)
            choice = apply_b2_rule(per_product.reset_index(), rule)
            choice.index = per_product.index
            source = "aucune_fenetre_anterieure_repli_autoets" if history.empty else "segments_fenetres_anterieures"
        else:
            rule = learn_b3_rule(history)
            choice = apply_b3_rule(per_product.reset_index(), rule)
            choice.index = per_product.index
            source = "aucune_fenetre_anterieure_repli_autoets" if history.empty else "produits_fenetres_anterieures"

        current["modele_choisi"] = current["unique_id"].map(choice)
        current["y_pred"] = np.where(
            current["modele_choisi"] == MODEL_B, current["pred_wa28"], current["pred_autoets"]
        )
        current["source_decision"] = source
        parts.append(current[["unique_id", "ds", "window", "y", "y_pred", "modele_choisi", "source_decision"]])

        n_wa = int((choice == MODEL_B).sum())
        decisions.append({
            "window": int(window),
            "n_produits": int(len(choice)),
            "n_windowaverage28": n_wa,
            "n_autoets": int(len(choice) - n_wa),
            "part_windowaverage28": n_wa / len(choice) if len(choice) else 0.0,
            "source": source,
            "fenetres_utilisees": sorted(int(x) for x in history["window"].unique()),
        })

    out = pd.concat(parts, ignore_index=True)
    out["modele"] = spec.name
    return out, pd.DataFrame(decisions)
