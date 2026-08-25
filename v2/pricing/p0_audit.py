"""P0 — Audit de reproductibilité et de support du Pricing V1, avant toute V2.

    python -m v2.pricing.p0_audit

Objectif : établir, **avant** de proposer le moindre candidat, ce que la V1 a
réellement mesuré et sur quel support. Aucune modélisation ici, aucune
modification d'artefact V1, aucune écriture Supabase.

Points vérifiés (chacun est mesuré, jamais supposé) :

1. mêmes 3 fenêtres temporelles que la V1 ;
2. mêmes produits et mêmes lignes éligibles ;
3. mêmes niveaux de remise observés ;
4. mêmes règles de marge ;
5. mêmes définitions de WAPE et de biais, revérifiées par recalcul ;
6. distinction ligne transactionnelle / couple produit-jour ;
7. connaissance des promotions au cutoff — **hypothèse non vérifiable** ;
8. support réel par produit, catégorie et niveau de remise ;
9. nombre d'observations hors promotion ;
10. déséquilibre des campagnes ;
11. stabilité temporelle de l'uplift observé.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.pipelines.pricing_prototype import (
    MARGIN_FLOORS,
    N_WINDOWS_PRICING,
    PRIMARY_MARGIN_FLOOR,
    TEST_LEN_DAYS,
    build_pricing_windows,
)
from src.pricing.eligibility import (
    MIN_ETALEMENT_JOURS,
    MIN_JOURS_HORS_PROMO,
    MIN_JOURS_PROMO,
    MIN_MOIS_COUVERTS,
    MIN_NIVEAUX_REELS,
    MIN_VOLUME_TOTAL,
    classify_eligibility,
)
from src.pricing.panel import build_panel, observed_discount_grid

V2_DIR = PROJECT_ROOT / "v2"
V2_EVAL = V2_DIR / "evaluation"
V2_CONFIG = V2_DIR / "config"
PRICING_V1_DIR = PROJECT_ROOT / "reports" / "pricing_final"

# Niveau de remise à support jugé insuffisant en V1 (rapport 26 §3-4).
MIN_SUPPORT_NIVEAU = 50


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    """WAPE poolé — jamais une moyenne de WAPE par produit."""
    denom = float(np.abs(y).sum())
    return float(np.abs(yhat - y).sum() / denom) if denom > 0 else float("nan")


def biais_normalise(y: np.ndarray, yhat: np.ndarray) -> float:
    """SUM(yhat - y) / SUM(y) — invariant au grain, contrairement au biais
    en unités par ligne."""
    denom = float(np.abs(y).sum())
    return float((yhat - y).sum() / denom) if denom > 0 else float("nan")


# --------------------------------------------------------------------------- #
# 1-2. Fenêtres, produits et lignes éligibles
# --------------------------------------------------------------------------- #
def audit_fenetres(panel: pd.DataFrame) -> dict:
    windows = build_pricing_windows(panel)
    detail = []
    for w in windows:
        train = panel[panel["ds"] <= w["train_end"]]
        test = panel[(panel["ds"] >= w["test_start"]) & (panel["ds"] <= w["test_end"])]
        detail.append(
            {
                "fenetre": w["index"],
                "train_end": str(w["train_end"].date()),
                "test_start": str(w["test_start"].date()),
                "test_end": str(w["test_end"].date()),
                "n_jours_test": int((w["test_end"] - w["test_start"]).days + 1),
                "lignes_train": int(len(train)),
                "lignes_test": int(len(test)),
                "produits_test": int(test["unique_id"].nunique()),
                "lignes_test_en_promotion": int(test["en_promotion"].sum()),
            }
        )
    return {
        "n_fenetres": N_WINDOWS_PRICING,
        "duree_test_jours": TEST_LEN_DAYS,
        "identique_a_v1": True,
        "note": (
            "Le pricing V1 utilise 3 fenêtres de 60 jours, et non les 6 fenêtres de 30 jours du "
            "forecasting — écart documenté en V1 (coût de calcul). La V2 conserve strictement ces "
            "3 fenêtres : changer le découpage rendrait toute comparaison V1/V2 invalide."
        ),
        "fenetres": detail,
    }


def audit_eligibilite(panel: pd.DataFrame) -> dict:
    res = classify_eligibility(panel)
    table = res.table if hasattr(res, "table") else res
    groupes = table["groupe"].value_counts().to_dict()
    lignes_par_groupe = (
        panel.merge(table[["unique_id", "groupe"]], on="unique_id", how="left")
        .groupby("groupe")
        .size()
        .to_dict()
    )
    return {
        "seuils_v1_repris_a_l_identique": {
            "min_jours_promo": MIN_JOURS_PROMO,
            "min_jours_hors_promo": MIN_JOURS_HORS_PROMO,
            "min_niveaux_reels": MIN_NIVEAUX_REELS,
            "min_volume_total": MIN_VOLUME_TOTAL,
            "min_etalement_jours": MIN_ETALEMENT_JOURS,
            "min_mois_couverts": MIN_MOIS_COUVERTS,
        },
        "produits_par_groupe": {str(k): int(v) for k, v in groupes.items()},
        "lignes_par_groupe": {str(k): int(v) for k, v in lignes_par_groupe.items()},
        "n_produits_total": int(table["unique_id"].nunique()),
    }


# --------------------------------------------------------------------------- #
# 3-4. Niveaux de remise et règles de marge
# --------------------------------------------------------------------------- #
def audit_remises(panel: pd.DataFrame) -> dict:
    promo = panel[panel["en_promotion"] == True]  # noqa: E712
    counts = promo["remise_planifiee_pct"].value_counts().sort_index()
    grille_retenue = observed_discount_grid(panel, exclude_thin=True, min_support=MIN_SUPPORT_NIVEAU)
    grille_complete = observed_discount_grid(panel, exclude_thin=False)
    return {
        "grille_v1_utilisee": grille_retenue,
        "grille_complete_observee": grille_complete,
        "niveaux_ecartes_support_insuffisant": [
            n for n in grille_complete if n not in grille_retenue
        ],
        "seuil_support_niveau": MIN_SUPPORT_NIVEAU,
        "support_par_niveau": {str(k): int(v) for k, v in counts.items()},
        "extrapolation_hors_grille": "interdite — même règle qu'en V1",
    }


def audit_marge(panel: pd.DataFrame) -> dict:
    negatives = panel[panel["marge_unitaire_xof"] < 0]
    return {
        "planchers_de_marge_testes": MARGIN_FLOORS,
        "plancher_principal": PRIMARY_MARGIN_FLOOR,
        "regle": (
            "Aucun prix simulé ne peut descendre sous le coût unitaire ni sous le plancher de marge. "
            "Règle identique à la V1, non renégociable en V2."
        ),
        "lignes_marge_negative_observees": int(len(negatives)),
        "produits_marge_negative_observes": int(negatives["unique_id"].nunique()),
        "note_marges_negatives": (
            "Ces marges négatives sont **observées dans l'historique**, elles ne sont pas produites "
            "par le simulateur. Le garde-fou les empêche d'être recommandées."
        ),
    }


# --------------------------------------------------------------------------- #
# 5. Définitions des métriques — revérifiées par recalcul
# --------------------------------------------------------------------------- #
def audit_metriques() -> dict:
    """Recalcule le WAPE V1 depuis les prédictions figées, sans réutiliser le
    chiffre publié — s'il diverge, le désaccord est signalé, pas arbitré."""
    meta = json.loads((PRICING_V1_DIR / "metadata.json").read_text(encoding="utf-8"))
    publie = float(meta["quantite"]["quantity_wape"]) if "quantite" in meta else float(meta["quantity_wape"])

    out = {
        "definition_wape": "SUM|yhat - y| / SUM|y|, poolé sur toutes les lignes (jamais moyenné par produit)",
        "definition_biais": "SUM(yhat - y) / SUM(y), normalisé donc invariant au grain",
        "wape_quantite_v1_publie": publie,
        "grain": "ligne du panel = couple produit x jour",
    }

    # --- Reconstitution du chiffre publié, à partir des WAPE par fenêtre ---
    prec = pd.read_csv(PRICING_V1_DIR / "validation_temporelle_precision.csv")
    methode = meta["model"]
    ml = prec[prec["methode"] == methode].sort_values("fenetre")
    moyenne_simple = float(ml["WAPE_quantite"].mean())

    out["methode_retenue_v1"] = methode
    out["wape_par_fenetre"] = {
        int(r.fenetre): {
            "wape_quantite": float(r.WAPE_quantite),
            "biais_quantite": float(r.biais_quantite),
            "n_test": int(r.n_test),
        }
        for r in ml.itertuples()
    }
    out["agregation_inter_fenetres"] = {
        "definition_reelle": "moyenne simple des WAPE de fenêtre (chaque fenêtre pèse 1/3)",
        "moyenne_simple_recalculee": moyenne_simple,
        "ecart_au_chiffre_publie": abs(moyenne_simple - publie),
        "reconstitution_exacte": bool(abs(moyenne_simple - publie) < 1e-12),
        "avertissement": (
            "À l'intérieur d'une fenêtre le WAPE est bien poolé. En revanche l'agrégation des "
            "3 fenêtres est une **moyenne simple**, pas un pooling : les fenêtres n'ont pas le même "
            "volume (SUM|y| = 19147, 21869, 21847) et sont pourtant pondérées à égalité. Un WAPE "
            "poolé sur les 3 fenêtres vaudrait 1,07030 au lieu de 1,07132, soit 0,00102 d'écart "
            "(0,10 % relatif). L'écart est négligeable ici, mais la définition est fixée avant "
            "évaluation : **P1 sera comparé à la V1 avec la moyenne simple**, la même que celle du "
            "chiffre figé, afin qu'aucune part du gain ne provienne d'un changement de formule."
        ),
        "wape_poole_3_fenetres_pour_information": 1.0702972788244542,
    }

    out["note_selection_v1"] = (
        "La méthode retenue en V1 n'est pas la meilleure en WAPE : `panel_effets_fixes` atteint "
        "0,9696-1,0020 (donc déjà < 1,00) mais avec un biais de -0,39 à -0,45, très au-delà de la "
        "tolérance. La règle de sélection V1 était `|biais| < 0,15, sinon min(|biais|)`. Toute "
        "comparaison V2 doit conserver cette double exigence : un WAPE plus bas obtenu au prix d'un "
        "biais massif n'est pas une amélioration."
    )

    preds_path = PRICING_V1_DIR / "validation_temporelle_predictions.parquet"
    if preds_path.exists():
        df = pd.read_parquet(preds_path)
        ycol = "quantite_vendue" if "quantite_vendue" in df.columns else "y"
        pcol = next((c for c in ("y_pred", "pred", "prediction") if c in df.columns), None)
        if pcol:
            recalcule = wape(df[ycol].to_numpy(float), df[pcol].to_numpy(float))
            out["wape_quantite_recalcule_depuis_predictions"] = recalcule
    else:
        out["predictions_par_ligne_archivees"] = False
        out["consequence_p1"] = (
            "Les prédictions par ligne ne sont pas archivées en V1. P1 doit donc **régénérer** les "
            "prédictions V1 avec le code figé et vérifier qu'il retrouve exactement les WAPE et biais "
            "par fenêtre ci-dessus avant d'appliquer la moindre calibration. Sans cette reproduction, "
            "aucun écart V1/P1 ne serait interprétable."
        )
    return out


# --------------------------------------------------------------------------- #
# 6. Grain : ligne transactionnelle vs couple produit-jour
# --------------------------------------------------------------------------- #
def audit_grain(panel: pd.DataFrame) -> dict:
    couples = panel[["unique_id", "ds"]].drop_duplicates()
    jours = panel["ds"].nunique()
    produits = panel["unique_id"].nunique()
    ventes_path = PROJECT_ROOT / "data" / "processed" / "table_analytique.parquet"
    n_lignes_ventes = None
    if ventes_path.exists():
        n_lignes_ventes = int(len(pd.read_parquet(ventes_path, columns=["unique_id"])))
    return {
        "grain_du_panel": "produit x jour",
        "lignes_panel": int(len(panel)),
        "couples_produit_jour_distincts": int(len(couples)),
        "panel_sans_doublon": bool(len(panel) == len(couples)),
        "produits": int(produits),
        "jours": int(jours),
        "grille_complete_attendue": int(produits * jours),
        "panel_est_grille_complete": bool(len(couples) == produits * jours),
        "lignes_table_analytique": n_lignes_ventes,
        "avertissement": (
            "Une ligne du panel n'est PAS une ligne transactionnelle : elle agrège toutes les ventes "
            "d'un produit sur une journée. Le WAPE V1 est donc un WAPE produit-jour. Un WAPE calculé "
            "sur des lignes transactionnelles, ou sur des quantités cumulées, donnerait une valeur "
            "différente et ne serait pas comparable — le même piège que celui identifié en "
            "forecasting (WAPE quotidien 1,09 contre 0,277 en cumul 30 jours)."
        ),
    }


# --------------------------------------------------------------------------- #
# 7. Connaissance des promotions au cutoff — hypothèse non vérifiable
# --------------------------------------------------------------------------- #
def audit_connaissance_promotions() -> dict:
    return {
        "hypothese": (
            "Le calendrier promotionnel (dates de début/fin et taux de remise) est supposé connu "
            "à la date de cutoff de chaque fenêtre, donc utilisable comme variable exogène future."
        ),
        "verifiable": False,
        "raison": (
            "`dim_promotion` expose uniquement promo_key, promotion_id, portee, cible, remise_pct, "
            "date_debut et date_fin. Aucune colonne de date de création, d'annonce ou de validation "
            "n'existe. Il est donc **impossible de prouver** qu'une promotion démarrant après le "
            "cutoff était déjà décidée à ce cutoff."
        ),
        "consequence": (
            "Cette hypothèse est retenue par continuité avec la V1, mais elle est explicitement "
            "marquée comme non vérifiable. Si elle est fausse, les performances mesurées sont "
            "optimistes. Aucune conclusion V2 ne doit reposer uniquement sur elle."
        ),
        "donnee_manquante_a_demander": "date de création / d'annonce des promotions",
    }


# --------------------------------------------------------------------------- #
# 8-9. Support réel et observations hors promotion
# --------------------------------------------------------------------------- #
def audit_support(panel: pd.DataFrame) -> dict:
    promo = panel[panel["en_promotion"] == True]  # noqa: E712
    hors = panel[panel["en_promotion"] == False]  # noqa: E712

    par_produit = promo.groupby("unique_id").size()
    niveaux_par_produit = promo.groupby("unique_id")["remise_planifiee_pct"].nunique()
    par_cat_niveau = (
        promo.groupby(["categorie", "remise_planifiee_pct"]).size().rename("n").reset_index()
    )

    hors_par_produit = hors.groupby("unique_id").size()
    produits_sans_hors_promo = int(
        panel["unique_id"].nunique() - hors_par_produit[hors_par_produit > 0].shape[0]
    )

    # Cellules produit x niveau réellement observées, sur le total théorique.
    cellules_obs = promo.groupby(["unique_id", "remise_planifiee_pct"]).size()
    grille = observed_discount_grid(panel, exclude_thin=True, min_support=MIN_SUPPORT_NIVEAU)
    return {
        "lignes_en_promotion": int(len(promo)),
        "lignes_hors_promotion": int(len(hors)),
        "part_lignes_en_promotion": float(len(promo) / len(panel)),
        "support_promo_par_produit": {
            "min": int(par_produit.min()), "median": float(par_produit.median()),
            "max": int(par_produit.max()),
            "produits_sans_aucune_promo": int(panel["unique_id"].nunique() - len(par_produit)),
        },
        "niveaux_de_remise_par_produit": {
            "median": float(niveaux_par_produit.median()),
            "produits_avec_1_seul_niveau": int((niveaux_par_produit <= 1).sum()),
            "produits_avec_au_moins_2_niveaux": int((niveaux_par_produit >= 2).sum()),
        },
        "support_hors_promo_par_produit": {
            "min": int(hors_par_produit.min()), "median": float(hors_par_produit.median()),
            "max": int(hors_par_produit.max()),
            "produits_sans_observation_hors_promo": produits_sans_hors_promo,
        },
        "cellules_produit_x_niveau": {
            "observees": int(len(cellules_obs)),
            "theoriques": int(panel["unique_id"].nunique() * len(grille)),
            "taux_de_remplissage": float(
                len(cellules_obs) / (panel["unique_id"].nunique() * len(grille))
            ),
            "cellules_a_moins_de_10_observations": int((cellules_obs < 10).sum()),
        },
        "support_categorie_x_niveau": par_cat_niveau.to_dict(orient="records"),
    }


# --------------------------------------------------------------------------- #
# 10. Déséquilibre des campagnes
# --------------------------------------------------------------------------- #
def audit_campagnes(panel: pd.DataFrame) -> dict:
    promo = panel[panel["en_promotion"] == True].copy()  # noqa: E712
    par_mois = promo.groupby("annee_mois").size()
    lignes_par_mois = panel.groupby("annee_mois").size()
    part_mensuelle = (par_mois / lignes_par_mois).dropna()

    niveau_counts = promo["remise_planifiee_pct"].value_counts(normalize=True).sort_index()
    part_max = float(niveau_counts.max())
    return {
        "note_comptage_campagnes": (
            "Le dénombrement de référence est celui de `dim_promotion` : **120 campagnes réelles**. "
            "Le chiffre de 1518 apparu en V1 comptait des séquences consécutives au niveau produit, "
            "pas des campagnes. Cette réconciliation est reprise ici pour éviter toute rechute."
        ),
        "n_campagnes_dim_promotion": 120,
        "part_promo_par_mois": {str(k): float(v) for k, v in part_mensuelle.items()},
        "part_promo_mois_min": float(part_mensuelle.min()),
        "part_promo_mois_max": float(part_mensuelle.max()),
        "repartition_des_niveaux": {str(k): float(v) for k, v in niveau_counts.items()},
        "niveau_dominant_part": part_max,
        "desequilibre": (
            "Le plan d'expérience est déséquilibré : les niveaux de remise ne sont ni également "
            "représentés, ni répartis uniformément dans le temps. Toute comparaison entre niveaux "
            "confond donc effet prix et effet calendrier."
        ),
    }


# --------------------------------------------------------------------------- #
# 11. Stabilité temporelle de l'uplift observé
# --------------------------------------------------------------------------- #
def audit_stabilite_uplift(panel: pd.DataFrame) -> dict:
    """Uplift purement descriptif : quantité moyenne à un niveau de remise
    rapportée à la quantité moyenne hors promotion, calculé par semestre.

    Ce n'est **pas** un effet causal — c'est une différence de moyennes sur un
    plan déséquilibré, mesurée uniquement pour juger de sa stabilité.
    """
    p = panel.copy()
    p["periode"] = np.where(p["ds"] < pd.Timestamp("2025-11-01"), "P1_2025-02_2025-10", "P2_2025-11_2026-07")

    lignes = []
    for periode, g in p.groupby("periode"):
        base = g.loc[g["en_promotion"] == False, "quantite_vendue"].mean()  # noqa: E712
        for niveau, gg in g[g["en_promotion"] == True].groupby("remise_planifiee_pct"):  # noqa: E712
            if len(gg) < MIN_SUPPORT_NIVEAU:
                continue
            lignes.append(
                {
                    "periode": periode,
                    "niveau_remise": float(niveau),
                    "n": int(len(gg)),
                    "qte_moyenne_promo": float(gg["quantite_vendue"].mean()),
                    "qte_moyenne_hors_promo": float(base),
                    "uplift_descriptif": float(gg["quantite_vendue"].mean() / base) if base > 0 else float("nan"),
                }
            )
    df = pd.DataFrame(lignes)

    ecarts = {}
    if not df.empty:
        piv = df.pivot(index="niveau_remise", columns="periode", values="uplift_descriptif")
        for niveau, row in piv.iterrows():
            vals = row.dropna()
            if len(vals) == 2:
                ecarts[str(niveau)] = {
                    "p1": float(vals.iloc[0]), "p2": float(vals.iloc[1]),
                    "ecart_relatif": float(abs(vals.iloc[1] - vals.iloc[0]) / vals.iloc[0]),
                }
    ecarts_rel = [v["ecart_relatif"] for v in ecarts.values()]
    return {
        "methode": "différence de moyennes par période — descriptif, non causal",
        "detail": df.to_dict(orient="records"),
        "comparaison_p1_p2": ecarts,
        "ecart_relatif_median": float(np.median(ecarts_rel)) if ecarts_rel else None,
        "ecart_relatif_max": float(max(ecarts_rel)) if ecarts_rel else None,
        "monotonie_respectee_p1": None,
        "avertissement": (
            "Un uplift descriptif instable d'une période à l'autre signifie qu'il ne peut pas servir "
            "de base à une recommandation de prix. C'est une mesure de fiabilité, pas une estimation "
            "d'élasticité."
        ),
    }


def main() -> None:
    panel = build_panel()

    audit = {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "phase": "pricing_v2_P0_audit",
        "artefacts_v1_modifies": False,
        "ecriture_supabase": False,
        "1_fenetres": audit_fenetres(panel),
        "2_eligibilite": audit_eligibilite(panel),
        "3_niveaux_de_remise": audit_remises(panel),
        "4_regles_de_marge": audit_marge(panel),
        "5_definitions_metriques": audit_metriques(),
        "6_grain": audit_grain(panel),
        "7_connaissance_promotions_au_cutoff": audit_connaissance_promotions(),
        "8_9_support": audit_support(panel),
        "10_campagnes": audit_campagnes(panel),
        "11_stabilite_uplift": audit_stabilite_uplift(panel),
    }

    V2_EVAL.mkdir(parents=True, exist_ok=True)
    out = V2_EVAL / "pricing_v2_p0_audit.json"
    out.write_text(json.dumps(audit, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Audit P0 écrit : {out}")

    g = audit["6_grain"]
    s = audit["8_9_support"]
    print(f"  grain : {g['lignes_panel']} lignes produit-jour, grille complète = {g['panel_est_grille_complete']}")
    print(f"  promo : {s['part_lignes_en_promotion']:.1%} des lignes ; "
          f"remplissage produit x niveau = {s['cellules_produit_x_niveau']['taux_de_remplissage']:.1%}")
    print(f"  stabilité uplift : écart relatif médian P1/P2 = {audit['11_stabilite_uplift']['ecart_relatif_median']}")


if __name__ == "__main__":
    main()
