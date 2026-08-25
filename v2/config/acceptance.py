"""Seuils d'acceptation Forecasting V2 — définis AVANT toute expérimentation.

Chaque seuil est soit une constante absolue explicitement fixée par le métier
(ex. WAPE 30 j ≤ 0,265), soit une amélioration relative calculée par rapport
à la référence V1 **chargée depuis le snapshot** (jamais recopiée en dur).

Une V2 n'est retenue que si TOUS les critères sont satisfaits simultanément.
Si aucun candidat n'y parvient, la V1 reste officiellement le modèle retenu —
c'est le résultat par défaut, pas un échec.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from v2.config.v1_reference import V1Reference, load_v1_reference

# --- Seuils absolus fixés par le métier (registre V2, rapport SYNTHESE §8) ---
SEUIL_WAPE_CUMULE_30J = 0.265
SEUIL_WAPE_CUMULE_7J = 0.44

# --- Améliorations relatives exigées vs V1 ---
AMELIORATION_QUOTIDIENNE_MIN = 0.03      # ≥3 % de mieux que la WAPE quotidienne V1
DEGRADATION_ABC_A_MAX = 0.02             # ≤2 % de dégradation tolérée sur les produits A
N_FENETRES_AMELIOREES_MIN = 4            # sur 6, à l'horizon 30 j

# --- Couverture des intervalles 80 % (globale ET produits A) ---
COUVERTURE_80_MIN = 0.78
COUVERTURE_80_MAX = 0.84


@dataclass(frozen=True)
class AcceptanceThresholds:
    """Seuils résolus, mêlant constantes absolues et cibles dérivées de la V1."""

    wape_cumule_30j_max: float
    wape_cumule_7j_max: float
    wape_quotidien_max: float           # dérivé : V1 x (1 - amelioration_min)
    wape_abc_a_max: float | None        # dérivé une fois la WAPE A de la V1 mesurée
    n_fenetres_ameliorees_min: int
    couverture_80_min: float
    couverture_80_max: float
    v1_reference: dict

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_thresholds(v1: V1Reference | None = None, v1_wape_abc_a: float | None = None) -> AcceptanceThresholds:
    """Résout les seuils d'acceptation à partir de la référence V1.

    ``v1_wape_abc_a`` : WAPE V1 sur les produits ABC-A, au grain cumulé 30 j.
    Elle n'est pas dans le snapshot V1 (qui ne stocke pas le détail par
    segment) — elle est recalculée à l'identique sur les prédictions
    opérationnelles V1 au moment de l'évaluation, puis passée ici. Tant
    qu'elle n'est pas fournie, ``wape_abc_a_max`` vaut ``None`` : le critère
    ABC-A ne peut alors pas être évalué, et un candidat ne peut donc pas être
    déclaré conforme (voir `evaluate_candidate`).
    """
    v1 = v1 or load_v1_reference()
    return AcceptanceThresholds(
        wape_cumule_30j_max=SEUIL_WAPE_CUMULE_30J,
        wape_cumule_7j_max=SEUIL_WAPE_CUMULE_7J,
        wape_quotidien_max=v1.wape_quotidien * (1 - AMELIORATION_QUOTIDIENNE_MIN),
        wape_abc_a_max=(v1_wape_abc_a * (1 + DEGRADATION_ABC_A_MAX)) if v1_wape_abc_a is not None else None,
        n_fenetres_ameliorees_min=N_FENETRES_AMELIOREES_MIN,
        couverture_80_min=COUVERTURE_80_MIN,
        couverture_80_max=COUVERTURE_80_MAX,
        v1_reference=v1.to_dict(),
    )


def evaluate_candidate(
    *,
    wape_cumule_30j: float,
    wape_cumule_7j: float,
    wape_quotidien: float,
    wape_abc_a: float | None,
    n_fenetres_ameliorees_30j: int,
    couverture_80_globale: float,
    couverture_80_produits_a: float,
    valeurs_non_finies: int,
    valeurs_negatives: int,
    thresholds: AcceptanceThresholds,
) -> dict:
    """Applique les critères d'acceptation ; renvoie le détail par critère.

    Aucun critère n'est « presque satisfait » : chacun est vrai ou faux, et
    l'acceptation exige que tous soient vrais. Un critère non évaluable
    (ex. ABC-A absent) est traité comme NON satisfait, jamais ignoré.
    """
    criteres = {
        "wape_cumule_30j": {
            "valeur": wape_cumule_30j, "seuil": thresholds.wape_cumule_30j_max,
            "ok": wape_cumule_30j <= thresholds.wape_cumule_30j_max,
            "regle": "≤ seuil absolu",
        },
        "wape_cumule_7j": {
            "valeur": wape_cumule_7j, "seuil": thresholds.wape_cumule_7j_max,
            "ok": wape_cumule_7j <= thresholds.wape_cumule_7j_max,
            "regle": "≤ seuil absolu",
        },
        "wape_quotidien": {
            "valeur": wape_quotidien, "seuil": thresholds.wape_quotidien_max,
            "ok": wape_quotidien <= thresholds.wape_quotidien_max,
            "regle": f"≥{AMELIORATION_QUOTIDIENNE_MIN:.0%} d'amélioration vs V1",
        },
        "wape_abc_a": {
            "valeur": wape_abc_a, "seuil": thresholds.wape_abc_a_max,
            "ok": (
                wape_abc_a is not None
                and thresholds.wape_abc_a_max is not None
                and wape_abc_a <= thresholds.wape_abc_a_max
            ),
            "regle": f"≤{DEGRADATION_ABC_A_MAX:.0%} de dégradation vs V1 (non évaluable = non satisfait)",
        },
        "n_fenetres_ameliorees_30j": {
            "valeur": n_fenetres_ameliorees_30j, "seuil": thresholds.n_fenetres_ameliorees_min,
            "ok": n_fenetres_ameliorees_30j >= thresholds.n_fenetres_ameliorees_min,
            "regle": "≥ 4 fenêtres sur 6",
        },
        "couverture_80_globale": {
            "valeur": couverture_80_globale,
            "seuil": [thresholds.couverture_80_min, thresholds.couverture_80_max],
            "ok": thresholds.couverture_80_min <= couverture_80_globale <= thresholds.couverture_80_max,
            "regle": "dans [78 %, 84 %]",
        },
        "couverture_80_produits_a": {
            "valeur": couverture_80_produits_a,
            "seuil": [thresholds.couverture_80_min, thresholds.couverture_80_max],
            "ok": thresholds.couverture_80_min <= couverture_80_produits_a <= thresholds.couverture_80_max,
            "regle": "dans [78 %, 84 %]",
        },
        "aucune_valeur_non_finie": {
            "valeur": valeurs_non_finies, "seuil": 0,
            "ok": valeurs_non_finies == 0, "regle": "= 0",
        },
        "aucune_valeur_negative": {
            "valeur": valeurs_negatives, "seuil": 0,
            "ok": valeurs_negatives == 0, "regle": "= 0",
        },
    }
    accepte = all(c["ok"] for c in criteres.values())
    return {
        "accepte": accepte,
        "criteres": criteres,
        "criteres_echoues": [k for k, c in criteres.items() if not c["ok"]],
        "verdict": (
            "CANDIDAT RETENU (tous les critères satisfaits)" if accepte
            else "CANDIDAT REJETÉ — la V1 reste le modèle officiel"
        ),
    }
