"""Références V1 Recommandation — chargées depuis les artefacts, jamais codées en dur.

Même principe que pour le forecasting : les valeurs de comparaison viennent
des artefacts V1 figés (`reports/recsys_final/`), pas de constantes recopiées
dans le code V2. Les seuils, eux, sont dans
``v2/config/recsys_v2_thresholds.json`` (fixés a priori par le métier).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import pandas as pd

from src.config.settings import PROJECT_ROOT

RECSYS_V1_DIR = PROJECT_ROOT / "reports" / "recsys_final"
SUMMARIES_PATH = RECSYS_V1_DIR / "baselines_summaries.csv"
METADATA_PATH = RECSYS_V1_DIR / "metadata.json"
THRESHOLDS_PATH = PROJECT_ROOT / "v2" / "config" / "recsys_v2_thresholds.json"

BASELINE_V1 = "popularite_globale"
POLICY_DEFAUT = "defaut_exclut_achats_stock_filtre"
POLICY_REAPPRO = "inclut_produits_deja_achetes"


@dataclass(frozen=True)
class RecsysV1Reference:
    recall_at_5: float
    recall_at_10: float
    ndcg_at_5: float
    ndcg_at_10: float
    precision_at_10: float
    couverture_catalogue: float
    couverture_utilisateurs: float
    diversite_at_10: float
    par_fenetre: dict
    personalisation_validee: bool
    baseline: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_thresholds() -> dict:
    return json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def load_v1_reference(policy: str = POLICY_DEFAUT, modele: str = BASELINE_V1) -> RecsysV1Reference:
    """Références V1 pour un modèle et une politique donnés, moyennées sur les
    4 fenêtres, plus le détail par fenêtre."""
    s = pd.read_csv(SUMMARIES_PATH)
    d = s[(s["policy_combo"] == policy) & (s["modele"] == modele)]
    if d.empty:
        raise ValueError(f"Aucune ligne V1 pour modele={modele}, policy={policy}")

    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    par_fenetre = {
        int(r["fenetre"]): {
            "recall_at_5": float(r["recall_at_5"]),
            "recall_at_10": float(r["recall_at_10"]),
            "ndcg_at_5": float(r["ndcg_at_5"]),
            "ndcg_at_10": float(r["ndcg_at_10"]),
            "catalog_coverage": float(r["catalog_coverage"]),
            "n_evaluable": int(r["n_evaluable"]),
        }
        for _, r in d.iterrows()
    }

    return RecsysV1Reference(
        recall_at_5=float(d["recall_at_5"].mean()),
        recall_at_10=float(d["recall_at_10"].mean()),
        ndcg_at_5=float(d["ndcg_at_5"].mean()),
        ndcg_at_10=float(d["ndcg_at_10"].mean()),
        precision_at_10=float(d["precision_at_10"].mean()),
        couverture_catalogue=float(d["catalog_coverage"].mean()),
        couverture_utilisateurs=float(d["user_coverage"].mean()),
        diversite_at_10=float(d["diversity_at_10"].mean()),
        par_fenetre=par_fenetre,
        personalisation_validee=bool(meta.get("personalization_validated", False)),
        baseline=modele,
    )


def evaluate_against_thresholds(
    *,
    recall_at_10: float,
    ndcg_at_10: float,
    couverture_catalogue: float,
    n_fenetres_battues: int,
    recul_clients_peu_actifs: float,
    n_doublons_top10: int,
    n_produits_ineligibles: int,
    fuite_temporelle_detectee: bool,
    v1: RecsysV1Reference,
    thresholds: dict | None = None,
) -> dict:
    """Applique les seuils V2 figés. Un critère non évaluable = non satisfait."""
    t = (thresholds or load_thresholds())["seuils_v2"]
    dures = (thresholds or load_thresholds())["contraintes_dures"]
    compromis = (thresholds or load_thresholds())["regle_compromis_couverture"]

    couverture_doublee = couverture_catalogue >= compromis["couverture_doublee_seuil"]
    perte_ndcg = (v1.ndcg_at_10 - ndcg_at_10) / v1.ndcg_at_10 if v1.ndcg_at_10 else float("inf")
    # La règle de compromis n'assouplit QUE le NDCG, et seulement si la
    # couverture est au moins doublée.
    ndcg_ok = ndcg_at_10 >= t["ndcg_at_10_min"] or (
        couverture_doublee and perte_ndcg <= t["perte_ndcg_max_si_couverture_doublee"]
    )

    criteres = {
        "recall_at_10": {
            "valeur": recall_at_10, "seuil": t["recall_at_10_min"],
            "ok": recall_at_10 >= t["recall_at_10_min"], "regle": "≥ seuil absolu",
        },
        "ndcg_at_10": {
            "valeur": ndcg_at_10, "seuil": t["ndcg_at_10_min"],
            "ok": ndcg_ok,
            "regle": f"≥ seuil absolu, OU perte ≤{t['perte_ndcg_max_si_couverture_doublee']:.0%} si couverture doublée "
                     f"(≥{compromis['couverture_doublee_seuil']})",
            "couverture_doublee": couverture_doublee,
            "perte_ndcg_relative": perte_ndcg,
        },
        "couverture_catalogue": {
            "valeur": couverture_catalogue, "seuil": t["couverture_catalogue_min"],
            "ok": couverture_catalogue >= t["couverture_catalogue_min"], "regle": "≥ seuil absolu",
        },
        "n_fenetres_battues": {
            "valeur": n_fenetres_battues, "seuil": t["n_fenetres_battues_min"],
            "ok": n_fenetres_battues >= t["n_fenetres_battues_min"],
            "regle": f"≥ {t['n_fenetres_battues_min']} sur {t['n_fenetres_total']}",
        },
        "recul_clients_peu_actifs": {
            "valeur": recul_clients_peu_actifs, "seuil": t["recul_max_clients_peu_actifs"],
            "ok": recul_clients_peu_actifs <= t["recul_max_clients_peu_actifs"],
            "regle": f"recul ≤ {t['recul_max_clients_peu_actifs']:.0%}",
        },
        "aucun_doublon_top10": {
            "valeur": n_doublons_top10, "seuil": 0,
            "ok": n_doublons_top10 == 0 if dures["aucun_doublon_dans_top_10"] else True,
            "regle": "= 0",
        },
        "aucun_produit_ineligible": {
            "valeur": n_produits_ineligibles, "seuil": 0,
            "ok": n_produits_ineligibles == 0 if dures["aucun_produit_ineligible"] else True,
            "regle": "= 0",
        },
        "aucune_fuite_temporelle": {
            "valeur": fuite_temporelle_detectee, "seuil": False,
            "ok": not fuite_temporelle_detectee, "regle": "aucune fuite détectée",
        },
    }
    accepte = all(c["ok"] for c in criteres.values())
    return {
        "accepte": accepte,
        "criteres": criteres,
        "criteres_echoues": [k for k, c in criteres.items() if not c["ok"]],
        "verdict": (
            "CANDIDAT RETENU (tous les critères satisfaits)" if accepte
            else "CANDIDAT REJETÉ — la V1 (popularité globale) reste la baseline officielle"
        ),
    }
