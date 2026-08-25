"""Évaluation du candidat P1 — recalibration des prédictions Pricing V1.

    python -m v2.pricing.run_p1

Déroulé, dans cet ordre strict :

1. **Reproduction de la V1.** Le modèle V1 est réentraîné par fenêtre avec le
   code figé, et l'on vérifie que les WAPE et biais retrouvés sont identiques à
   ceux archivés. Sans cette étape, aucun écart V1/P1 ne serait interprétable.
2. **Calibration.** Trois variantes, chacune estimée uniquement sur les
   fenêtres antérieures.
3. **Évaluation** contre les seuils figés dans
   ``v2/config/pricing_v2_thresholds.json``.

Aucune écriture Supabase, aucun déploiement, aucun artefact V1 modifié.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.pipelines.pricing_prototype import build_pricing_windows
from src.pricing.eligibility import classify_eligibility
from src.pricing.panel import build_panel
from src.pricing.predictors import MLChallengerPredictor
from v2.pricing.candidate_p1 import (
    FACTEUR_NEUTRE,
    K_REGULARISATION,
    MIN_SUPPORT_CATEGORIE,
    VARIANTES,
    estimate_factors,
)

V2_EVAL = PROJECT_ROOT / "v2" / "evaluation"
V2_CONFIG = PROJECT_ROOT / "v2" / "config"
PRICING_V1_DIR = PROJECT_ROOT / "reports" / "pricing_final"

# Tolérance de reproduction. Le modèle V1 est un LightGBM : sa graine est fixée,
# mais l'ordonnancement des threads peut introduire une dérive de dernier bit.
# On exige une reproduction au 1e-6, et tout dépassement est signalé, jamais absorbé.
TOL_REPRODUCTION = 1e-6


def wape(y: np.ndarray, y_pred: np.ndarray) -> float:
    denom = float(np.abs(y).sum())
    return float(np.abs(y_pred - y).sum() / denom) if denom > 0 else float("nan")


def biais_unitaire(y: np.ndarray, y_pred: np.ndarray) -> float:
    """Définition V1 : moyenne des résidus, en unités par ligne produit-jour."""
    return float((y_pred - y).mean())


def biais_normalise(y: np.ndarray, y_pred: np.ndarray) -> float:
    """SUM(yhat - y) / SUM(y) — invariant au grain."""
    denom = float(np.abs(y).sum())
    return float((y_pred - y).sum() / denom) if denom > 0 else float("nan")


# --------------------------------------------------------------------------- #
# 1. Reproduction de la V1
# --------------------------------------------------------------------------- #
def regenerer_predictions_v1(panel: pd.DataFrame) -> tuple[dict[int, pd.DataFrame], dict]:
    """Réentraîne le modèle V1 par fenêtre et conserve les prédictions ligne à ligne."""
    windows = build_pricing_windows(panel)
    reference = pd.read_csv(PRICING_V1_DIR / "validation_temporelle_precision.csv")
    reference = reference[reference["methode"] == MLChallengerPredictor.name].set_index("fenetre")

    par_fenetre: dict[int, pd.DataFrame] = {}
    controle = {"tolerance": TOL_REPRODUCTION, "fenetres": [], "reproduction_exacte": True}

    for win in windows:
        k = win["index"]
        train = panel[panel["ds"] <= win["train_end"]]
        test = panel[(panel["ds"] >= win["test_start"]) & (panel["ds"] <= win["test_end"])]

        t0 = time.perf_counter()
        predictor = MLChallengerPredictor().fit(train)
        y_pred = predictor.predict(test)
        duree = time.perf_counter() - t0

        y = test["quantite_vendue"].to_numpy(dtype="float64")
        obtenu_wape, obtenu_biais = wape(y, y_pred), biais_unitaire(y, y_pred)
        attendu_wape = float(reference.loc[k, "WAPE_quantite"])
        attendu_biais = float(reference.loc[k, "biais_quantite"])

        # La référence archivée est arrondie à 6 décimales par le CSV : on compare
        # à cette précision, pas à une précision que le fichier ne porte pas.
        ecart_wape = abs(round(obtenu_wape, 6) - attendu_wape)
        ecart_biais = abs(round(obtenu_biais, 6) - attendu_biais)
        ok = ecart_wape <= TOL_REPRODUCTION and ecart_biais <= TOL_REPRODUCTION
        controle["reproduction_exacte"] &= ok
        controle["fenetres"].append(
            {
                "fenetre": k, "n_test": int(len(test)),
                "wape_attendu": attendu_wape, "wape_obtenu": obtenu_wape, "ecart_wape": ecart_wape,
                "biais_attendu": attendu_biais, "biais_obtenu": obtenu_biais, "ecart_biais": ecart_biais,
                "reproduit": bool(ok), "duree_s": round(duree, 2),
            }
        )

        par_fenetre[k] = pd.DataFrame(
            {
                "unique_id": test["unique_id"].to_numpy(),
                "categorie": test["categorie"].to_numpy(),
                "ds": test["ds"].to_numpy(),
                "y": y,
                "y_pred": np.asarray(y_pred, dtype="float64"),
            }
        )

    return par_fenetre, controle


# --------------------------------------------------------------------------- #
# 2-3. Calibration et évaluation
# --------------------------------------------------------------------------- #
def evaluer_variante(par_fenetre: dict[int, pd.DataFrame], variante: str) -> dict:
    lignes, facteurs_log = [], []

    for k in sorted(par_fenetre):
        df = par_fenetre[k]
        fac = estimate_factors(par_fenetre, k, variante)
        y = df["y"].to_numpy(float)
        y_pred_v1 = df["y_pred"].to_numpy(float)
        cats = df["categorie"] if variante != "P1a_global" else None
        y_pred_cal = fac.apply(y_pred_v1, cats)

        lignes.append(
            {
                "fenetre": k, "n_test": int(len(df)),
                "wape_v1": wape(y, y_pred_v1), "wape_p1": wape(y, y_pred_cal),
                "biais_unitaire_v1": biais_unitaire(y, y_pred_v1),
                "biais_unitaire_p1": biais_unitaire(y, y_pred_cal),
                "biais_normalise_v1": biais_normalise(y, y_pred_v1),
                "biais_normalise_p1": biais_normalise(y, y_pred_cal),
            }
        )
        facteurs_log.append(
            {
                "fenetre": k, "source": fac.source,
                "fenetres_utilisees": list(fac.fenetres_utilisees),
                "facteur_global": fac.global_,
                "facteurs_par_categorie": fac.par_categorie,
                "supports_par_categorie": fac.supports,
                "n_categories_avec_facteur_propre": sum(
                    1 for c, n in fac.supports.items() if n >= MIN_SUPPORT_CATEGORIE
                ),
            }
        )

    d = pd.DataFrame(lignes)
    ameliorees = int((d["wape_p1"] < d["wape_v1"]).sum())
    return {
        "variante": variante,
        "par_fenetre": d.to_dict(orient="records"),
        "facteurs": facteurs_log,
        "wape_moyen_v1": float(d["wape_v1"].mean()),
        "wape_moyen_p1": float(d["wape_p1"].mean()),
        "biais_unitaire_moyen_p1": float(d["biais_unitaire_p1"].mean()),
        "biais_normalise_moyen_p1": float(d["biais_normalise_p1"].mean()),
        "fenetres_ameliorees": ameliorees,
        "fenetres_ameliorees_hors_fenetre_1": int(
            (d.loc[d["fenetre"] > 1, "wape_p1"] < d.loc[d["fenetre"] > 1, "wape_v1"]).sum()
        ),
        "gain_relatif_wape": float(
            (d["wape_v1"].mean() - d["wape_p1"].mean()) / d["wape_v1"].mean()
        ),
    }


def appliquer_seuils(resultat: dict, seuils: dict) -> dict:
    c = seuils["criteres_de_validation"]
    verdicts = {}

    verdicts["C1_precision"] = {
        "valeur": resultat["wape_moyen_p1"], "seuil": c["C1_precision"]["seuil"],
        "passe": bool(resultat["wape_moyen_p1"] < c["C1_precision"]["seuil"]),
    }
    b_u, b_n = abs(resultat["biais_unitaire_moyen_p1"]), abs(resultat["biais_normalise_moyen_p1"])
    verdicts["C2_biais"] = {
        "biais_unitaire_abs": b_u, "biais_normalise_abs": b_n,
        "seuil": c["C2_biais"]["seuil_biais_unitaire"],
        "passe": bool(b_u <= c["C2_biais"]["seuil_biais_unitaire"]
                      and b_n <= c["C2_biais"]["seuil_biais_normalise"]),
    }
    verdicts["C3_robustesse"] = {
        "fenetres_ameliorees": resultat["fenetres_ameliorees"], "seuil": c["C3_robustesse"]["seuil"],
        "passe": bool(resultat["fenetres_ameliorees"] >= c["C3_robustesse"]["seuil"]),
    }

    verdicts["_global"] = {
        "tous_criteres_precision_passes": all(v["passe"] for v in verdicts.values()),
        "criteres_c4_a_c7_evalues": False,
        "note": (
            "C4 (garde-fou marge), C5 (aucune extrapolation), C6 (hors support) et C7 (stabilité "
            "des remises) portent sur les sorties du simulateur, pas sur la précision. Ils ne sont "
            "évalués que pour un candidat ayant d'abord franchi C1-C3 — conformément à la règle "
            "« un critère non évaluable compte comme ÉCHOUÉ », un candidat qui échoue C1-C3 est "
            "rejeté sans qu'il soit utile de lancer le simulateur."
        ),
    }
    return verdicts


def main() -> None:
    panel = build_panel()
    classify_eligibility(panel)  # cohérence de périmètre : mêmes groupes qu'en V1

    seuils = json.loads((V2_CONFIG / "pricing_v2_thresholds.json").read_text(encoding="utf-8"))

    print("1. Reproduction des prédictions V1...")
    par_fenetre, controle = regenerer_predictions_v1(panel)
    for f in controle["fenetres"]:
        etat = "OK" if f["reproduit"] else "ECART"
        print(f"   F{f['fenetre']}: WAPE {f['wape_obtenu']:.6f} (attendu {f['wape_attendu']:.6f}, "
              f"ecart {f['ecart_wape']:.2e}) biais {f['biais_obtenu']:+.6f} -> {etat}")

    if not controle["reproduction_exacte"]:
        print("\n   ATTENTION : la V1 n'est pas reproduite a l'identique.")
        print("   Les resultats P1 ci-dessous ne sont PAS interpretables comme un gain de calibration :")
        print("   une part de l'ecart pourrait venir de la divergence de reproduction.")

    print("\n2. Evaluation des variantes...")
    resultats = {}
    for v in VARIANTES:
        r = evaluer_variante(par_fenetre, v)
        r["verdicts"] = appliquer_seuils(r, seuils)
        resultats[v] = r
        print(f"   {v:30s} WAPE {r['wape_moyen_v1']:.6f} -> {r['wape_moyen_p1']:.6f} "
              f"({r['gain_relatif_wape']:+.2%}) | fenetres ameliorees {r['fenetres_ameliorees']}/3 "
              f"(hors F1 : {r['fenetres_ameliorees_hors_fenetre_1']}/2) | "
              f"C1={'OK' if r['verdicts']['C1_precision']['passe'] else 'ECHEC'} "
              f"C2={'OK' if r['verdicts']['C2_biais']['passe'] else 'ECHEC'} "
              f"C3={'OK' if r['verdicts']['C3_robustesse']['passe'] else 'ECHEC'}")

    payload = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "candidat": "P1_recalibration",
        "hyperparametres_fixes_a_priori": {
            "min_support_categorie": MIN_SUPPORT_CATEGORIE,
            "k_regularisation": K_REGULARISATION,
            "facteur_neutre_fenetre_1": FACTEUR_NEUTRE,
        },
        "controle_reproduction_v1": controle,
        "resultats": resultats,
        "artefacts_v1_modifies": False,
        "ecriture_supabase": False,
        "deploiement": False,
    }
    V2_EVAL.mkdir(parents=True, exist_ok=True)
    out = V2_EVAL / "pricing_p1_metrics.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nEcrit : {out}")


if __name__ == "__main__":
    main()
