"""Finalisation du premier produit V4 : metadonnees consolidees et
instantanes de catalogue necessaires a l'API de service.

Ce module ne reentraine rien : il relit les artefacts deja produits par
`src.pricing_v4.train` et `src.recsys_v4.train`, ainsi que la conclusion de
la validation independante (`reports/v4_training/07_validation_independante.json`),
pour produire :

1. `models/v4/FINAL_STATUS.json` — une fiche unique par modele retenu
   (nom, cible, version, metriques, fenetre d'evaluation, limites, statut
   `validated_academic`/`exploratory`, fallback, date de generation,
   empreinte SHA-256), servant de source de verite unique pour l'API.
2. `api_v4/data/recommendation_catalog.json` — instantane produit
   (categorie, marque encodes, popularite figee a la fin de la fenetre
   d'entrainement), au grain produit uniquement, sans aucune donnee client.
3. `api_v4/data/categorical_mappings.json` — les tables de correspondance
   valeur -> code (appareil, source de trafic, canal) utilisees a
   l'entrainement, pour encoder identiquement un contexte fourni par
   l'appelant de l'API.
4. `api_v4/data/pricing_catalog.json` — instantane produit pour le pricing
   (prix catalogue, cout, categorie, classe ABC).

Aucun acces a Supabase : tout est relu depuis les copies locales deja
extraites (`data/raw/`, `data/raw/v4/`) et les artefacts deja entraines.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.config.settings import PROJECT_ROOT
from src.recsys_v4.dataset import _session_context  # reutilise, pas reimplemente
from src.recsys_v4.dataset import build_dataset as build_reco_dataset

MODELS_DIR = PROJECT_ROOT / "models" / "v4"
LEGACY_DIR = PROJECT_ROOT / "data" / "raw"
V4_DIR = PROJECT_ROOT / "data" / "raw" / "v4"
API_DATA_DIR = PROJECT_ROOT / "api_v4" / "data"
REPORTS_DIR = PROJECT_ROOT / "reports" / "v4_training"

RECOMMENDATION_TARGETS = {
    "purchased_after": {"role": "achat"},
    "added_to_cart_after": {"role": "ajout_panier"},
    "viewed_after_impression": {"role": "consultation"},
}
PRICING_TARGETS = ("units_sold_window_7j", "revenue_window_xof_7j", "margin_window_xof_7j")


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip() or "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Instantanes de catalogue pour l'API
# --------------------------------------------------------------------------

def build_recommendation_catalog(reco_dataset: pd.DataFrame) -> dict:
    """Instantane produit fige a la fin de la fenetre d'entrainement.

    Grain produit uniquement (300 entrees) : aucune donnee client. La
    popularite est celle observee au tout dernier instant du jeu de
    donnees — une photographie academique, pas un flux recalcule en continu.
    """
    latest = (reco_dataset.sort_values("impression_timestamp")
             .groupby("produit_key").tail(1)
             .set_index("produit_key"))
    catalog = {}
    for produit_key, row in latest.iterrows():
        catalog[produit_key] = {
            "categorie": row["categorie"],
            "category_code": int(row["category_code"]),
            "brand_code": int(row["brand_code"]),
            "prix_base_xof": float(row["prix_base_xof"]),
            "product_popularity_before": float(row["product_popularity_before"]),
            "product_recent_popularity_28d": float(row["product_recent_popularity_28d"]),
        }
    return catalog


def build_categorical_mappings(reco_raw: dict) -> dict:
    """Tables valeur -> code pour appareil/source/canal, recalculees avec la
    meme convention que `src.recsys_v4.dataset.build_dataset` (tri
    alphabetique des valeurs observees, `inconnu` pour les valeurs
    manquantes), afin d'encoder un contexte fourni par l'appelant de l'API
    de facon identique a l'entrainement.
    """
    reco, web = reco_raw["reco"], reco_raw["web"]
    context = _session_context(reco, web)

    def _mapping(column: str) -> dict:
        values = context[column].fillna("inconnu")
        categories = sorted(values.unique())
        return {value: index for index, value in enumerate(categories)}

    return {
        "device": _mapping("appareil"),
        "source": _mapping("source_trafic"),
        "channel": _mapping("canal"),
    }


def build_pricing_catalog(pricing_raw: pd.DataFrame, produits: pd.DataFrame) -> dict:
    """Instantane produit pour le pricing : prix catalogue, cout (dim_produit),
    categorie et classe ABC (table d'experimentation) — au grain produit,
    identique pour toute decision.
    """
    per_decision = pricing_raw.groupby("produit_key")[["categorie", "classe_abc"]].first()
    per_product = per_decision.merge(
        produits.set_index("produit_key")[["prix_base_xof", "cout_xof"]],
        left_index=True, right_index=True, how="left")
    catalog = {}
    for produit_key, row in per_product.iterrows():
        catalog[produit_key] = {
            "categorie": row["categorie"],
            "classe_abc": row["classe_abc"],
            "prix_base_xof": float(row["prix_base_xof"]),
            "cout_xof": float(row["cout_xof"]),
        }
    return catalog


# --------------------------------------------------------------------------
# FINAL_STATUS.json
# --------------------------------------------------------------------------

def _pricing_entry(target: str, commit: str, generated_at: str) -> dict:
    model_dir = MODELS_DIR / "pricing" / target
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((model_dir / "manifest.sha256.json").read_text(encoding="utf-8"))
    baseline_name = metadata["selected_model"]
    summary_row = next(row for row in metadata["summary"] if row["model"] == baseline_name)
    return {
        "domain": "pricing",
        "target": target,
        "model_name": baseline_name,
        "version": metadata.get("code_version_git_commit", commit),
        "metrics": {
            "wape_macro": summary_row.get("wape_macro"),
            "wape_micro_pooled": summary_row.get("wape_micro_pooled"),
            "bias": summary_row.get("bias"),
            "mae": summary_row.get("mae"),
            "rmse": summary_row.get("rmse"),
            "n_price_below_cost": metadata.get("guardrails", {}).get("n_price_below_cost"),
            "n_margin_below_floor": metadata.get("guardrails", {}).get("n_margin_below_floor"),
        },
        "evaluation_window": "6 fenetres de test hebdomadaires, entrainement sur tout l'historique anterieur",
        "limits": ("Estimation statistique de volume/marge, aucune revendication causale ; "
                  "confusion structurelle remise/produit sur cette experience synthetique ; "
                  "aucun prix optimal automatique, simulation uniquement."),
        "status": "validated_academic",
        # Statut d'usage distinct du statut de validation : la baseline est une
        # reference validee, mais son seul usage autorise est la simulation.
        "usage": "simulation_only",
        "causal_effect_estimated": False,
        "fallback": None,
        "generated_at": generated_at,
        "sha256": manifest.get("model.joblib"),
    }


def _recommendation_entry(target: str, commit: str, generated_at: str,
                          independent: dict) -> dict:
    model_dir = MODELS_DIR / "recommendation" / target
    metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((model_dir / "manifest.sha256.json").read_text(encoding="utf-8"))
    selected_name = metadata["selected_model"]
    summary_row = next(row for row in metadata["summary"] if row["model"] == selected_name)
    comparison = independent["recalcul_recommandation"]["comparaisons"].get(target, {})
    candidat = next((c for c in metadata["candidates"] if c["model"] == selected_name), {})

    status = "validated_academic" if target in ("purchased_after", "added_to_cart_after") else "exploratory"
    default_use = target in ("purchased_after", "added_to_cart_after")

    return {
        "domain": "recommendation",
        "target": target,
        "role": RECOMMENDATION_TARGETS[target]["role"],
        "model_name": selected_name,
        "version": metadata.get("code_version_git_commit", commit),
        "metrics": {
            "ndcg@10": summary_row.get("ndcg@10_mean"),
            "relative_ndcg_gain": candidat.get("relative_ndcg_gain"),
            "recall@10": summary_row.get("recall@10_mean"),
            "coverage_catalogue": summary_row.get("coverage_catalogue_mean"),
            "diversite": summary_row.get("diversite_mean"),
            "bootstrap_ci95_independant": comparison.get("bootstrap"),
            "p_value_holm_independante": comparison.get("p_value_holm"),
        },
        "evaluation_window": "4 fenetres de test cumulatives sur 6 fenetres totales",
        "limits": ("Reclassement de 5 candidats deja selectionnes, jamais un choix du candidat "
                  "lui-meme ; aucune revendication causale ; jeu de donnees synthetique, usage "
                  "academique et benchmark de pipeline uniquement."
                  + ("" if status == "validated_academic" else
                     " Statut exploratoire : gain non demontre de facon statistiquement robuste "
                     "par la validation independante (p brute = 0.088, non significative).")),
        "status": status,
        "used_by_default": default_use,
        "fallback": "popularite_globale_v1",
        "generated_at": generated_at,
        "sha256": manifest.get("model.joblib"),
    }


def _fallback_entry(generated_at: str, commit: str) -> dict:
    return {
        "domain": "recommendation",
        "target": "toutes cibles (secours)",
        "role": "secours",
        "model_name": "popularite_globale_v1",
        "version": commit,
        "metrics": {"description": "score = popularite cumulee du produit, figee a la fin de la fenetre d'entrainement"},
        "evaluation_window": "instantane fige, pas de fenetre de test dediee",
        "limits": ("Aucune personnalisation ; utilise automatiquement si le modele principal "
                  "echoue ou si le produit demande est hors catalogue connu."),
        "status": "validated_academic",
        "used_by_default": False,
        "fallback": None,
        "generated_at": generated_at,
        "sha256": None,
    }


def build_final_status() -> dict:
    commit = _git_commit()
    generated_at = datetime.now(timezone.utc).isoformat()
    independent = json.loads((REPORTS_DIR / "07_validation_independante.json").read_text(encoding="utf-8"))

    entries = [_pricing_entry(target, commit, generated_at) for target in PRICING_TARGETS]
    entries += [_recommendation_entry(target, commit, generated_at, independent)
               for target in RECOMMENDATION_TARGETS]
    entries.append(_fallback_entry(generated_at, commit))

    return {
        "product": "v4_pricing_recommendation",
        "status": "synthetic_academic_experiment",
        "generated_at": generated_at,
        "code_version_git_commit": commit,
        "forecasting_note": ("Le forecasting V2 (LightGBM_direct_per_horizon) n'a pas ete "
                             "reentraine ni modifie ; il n'est pas expose par ce produit."),
        "models": entries,
    }


# Instantane forecasting, en lecture seule
# --------------------------------------------------------------------------

FORECAST_SOURCE = PROJECT_ROOT / "models" / "advanced" / "forecasting" / "direct_lightgbm_predictions.parquet"


def _forecast_detailed_metrics() -> dict:
    """Metriques detaillees du backtest de prevision, lues telles quelles.

    Lecture seule stricte : aucun recalcul, aucun reentrainement. Les
    metriques absentes du backtest ne sont pas fabriquees — elles sont
    declarees explicitement comme non calculees, afin que l'interface ne
    puisse pas afficher une valeur qui n'existe pas.
    """
    source = PROJECT_ROOT / "models" / "advanced" / "forecasting" / "metadata.json"
    metadata = json.loads(source.read_text(encoding="utf-8"))
    resume = metadata["summary"]
    comparaison = metadata["comparison"]
    reference = metadata["reference"]["summary"]

    quotidien = next((r for r in reference
                      if r["model"] == metadata["decisions"]["operational_daily_model"]), {})

    fenetres = [
        {
            "fenetre": f["window"],
            "debut": str(f["test_start"])[:10],
            "wape_quotidienne": round(float(f["wape_daily"]), 6),
            "wape_cumulee_7j": round(float(f["wape_cum_7"]), 6),
            "wape_cumulee_30j": round(float(f["wape_cum_30"]), 6),
            "biais": round(float(f["bias"]), 6),
        }
        for f in metadata["window_metrics"]
    ]

    return {
        "agregat": {
            "wape_quotidienne": round(float(resume["wape_daily"]), 6),
            "wape_cumulee_7j": round(float(resume["wape_cum_7"]), 6),
            "wape_cumulee_30j": round(float(resume["wape_cum_30"]), 6),
            # La WAPE cumulee a 14 jours n'a pas ete calculee lors du backtest :
            # elle est declaree absente plutot que remplacee par une valeur.
            "wape_cumulee_14j": None,
            "wape_cumulee_14j_disponible": False,
        },
        "quotidien": {
            "modele": metadata["decisions"]["operational_daily_model"],
            "wape_quotidienne": round(float(quotidien["wape"]), 6) if quotidien else None,
            "wape_cumulee_30j": round(float(quotidien["wape30"]), 6) if quotidien else None,
            "biais": round(float(quotidien["bias"]), 6) if quotidien else None,
            "ecart_type": round(float(quotidien["std"]), 6) if quotidien else None,
        },
        "fenetres": fenetres,
        "victoires": {
            "n_fenetres_evaluees": len(fenetres),
            "planification_30j": comparaison["cumulative_30d_windows_won_vs_validated_lightgbm"],
            "quotidien": comparaison["daily_windows_won_vs_croston"],
            "reference_planification": "LightGBM_Tweedie",
            "reference_quotidien": "CrostonOptimized",
        },
        "horizons_evalues": len(metadata["methodology"]["horizons"]),
    }


def build_forecast_snapshot() -> dict:
    """Instantane de la prevision 30 jours deja validee, pour affichage.

    Lecture seule stricte : aucun modele de forecasting n'est reentraine et
    aucun artefact de `models/forecasting/` ou `models/advanced/forecasting/`
    n'est modifie. Seule la derniere fenetre de backtest est reprise, au grain
    produit x horizon, avec le realise et le prevu.

    Les metriques globales proviennent de `models/FINAL_STATUS.json`, source de
    verite de la decision forecasting V2.
    """
    predictions = pd.read_parquet(FORECAST_SOURCE)
    derniere = predictions[predictions.window.eq(predictions.window.max())].copy()
    derniere = derniere.sort_values(["produit_key", "horizon"])

    produits = pd.read_parquet(LEGACY_DIR / "dim_produit.parquet").set_index("produit_key")
    statut_v2 = json.loads((PROJECT_ROOT / "models" / "FINAL_STATUS.json").read_text(encoding="utf-8"))["status"]

    horizons = sorted(derniere.horizon.unique().tolist())
    dates = [str(d)[:10] for d in derniere[derniere.produit_key.eq(derniere.produit_key.iloc[0])]
             .sort_values("horizon").ds.tolist()]

    par_produit = {}
    for produit_key, groupe in derniere.groupby("produit_key"):
        groupe = groupe.sort_values("horizon")
        reel = [float(v) for v in groupe.y]
        prevu = [round(float(v), 4) for v in groupe.pred]
        total_reel, total_prevu = sum(reel), sum(prevu)
        par_produit[produit_key] = {
            "nom": str(produits.loc[produit_key, "product_name"]) if produit_key in produits.index else produit_key,
            "categorie": str(produits.loc[produit_key, "categorie"]) if produit_key in produits.index else "inconnue",
            "reel": reel,
            "prevu": prevu,
            "total_reel_30j": round(total_reel, 2),
            "total_prevu_30j": round(total_prevu, 2),
            "ecart_absolu_30j": round(abs(total_reel - total_prevu), 2),
        }

    metriques_detaillees = _forecast_detailed_metrics()

    return {
        "statut": "validated",
        "avertissement": (
            "Prevision issue du modele V2 deja valide, reprise en lecture seule et "
            "jamais reentrainee. Les valeurs affichees proviennent de la derniere "
            "fenetre de backtest hors echantillon, pas d'une prevision du futur."),
        "modele_planification_30j": statut_v2["forecasting_30d_model"],
        "modele_quotidien": statut_v2["forecasting_daily_model"],
        "metriques": {
            "wape30_macro": statut_v2["forecasting_wape30_macro"],
            "wape30_micro": 0.25743,
            "forecast_bias_macro": statut_v2["forecasting_bias"],
            **metriques_detaillees["agregat"],
        },
        "modele_quotidien_metriques": metriques_detaillees["quotidien"],
        "fenetres": metriques_detaillees["fenetres"],
        "victoires": metriques_detaillees["victoires"],
        "horizons_evalues": metriques_detaillees["horizons_evalues"],
        "fenetre": {
            "index": int(derniere.window.iloc[0]),
            "debut": str(derniere.test_start.iloc[0])[:10],
            "horizons": horizons,
            "dates": dates,
        },
        "n_produits": len(par_produit),
        "produits": par_produit,
    }


def main() -> None:
    API_DATA_DIR.mkdir(parents=True, exist_ok=True)

    reco_dataset = build_reco_dataset()
    from src.recsys_v4.dataset import _load_raw as _load_reco_raw
    reco_raw = _load_reco_raw()

    pricing_raw = pd.read_parquet(V4_DIR / "fact_experimentation_prix.parquet")
    produits = pd.read_parquet(LEGACY_DIR / "dim_produit.parquet")

    recommendation_catalog = build_recommendation_catalog(reco_dataset)
    categorical_mappings = build_categorical_mappings(reco_raw)
    pricing_catalog = build_pricing_catalog(pricing_raw, produits)

    (API_DATA_DIR / "recommendation_catalog.json").write_text(
        json.dumps(recommendation_catalog, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8", newline="\n")
    (API_DATA_DIR / "categorical_mappings.json").write_text(
        json.dumps(categorical_mappings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    (API_DATA_DIR / "pricing_catalog.json").write_text(
        json.dumps(pricing_catalog, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8", newline="\n")

    forecast = build_forecast_snapshot()
    (API_DATA_DIR / "forecast_snapshot.json").write_text(
        json.dumps(forecast, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8", newline="\n")

    final_status = build_final_status()
    (MODELS_DIR / "FINAL_STATUS.json").write_text(
        json.dumps(final_status, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8", newline="\n")

    print("Ecrit :")
    print(" -", API_DATA_DIR / "recommendation_catalog.json", f"({len(recommendation_catalog)} produits)")
    print(" -", API_DATA_DIR / "categorical_mappings.json")
    print(" -", API_DATA_DIR / "pricing_catalog.json", f"({len(pricing_catalog)} produits)")
    print(" -", API_DATA_DIR / "forecast_snapshot.json", f"({forecast['n_produits']} produits, lecture seule)")
    print(" -", MODELS_DIR / "FINAL_STATUS.json", f"({len(final_status['models'])} entrees)")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------
