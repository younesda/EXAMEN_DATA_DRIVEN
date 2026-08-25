"""Statuts officiels finaux des trois domaines, apres correction des fuites.

Source de verite unique, serialisee dans `models/FINAL_STATUS.json` et reprise
dans `reports/45_final_corrected_decision.md`. Les valeurs sont figees : elles
ne sont pas recalculees ici, elles sont recopiees depuis les artefacts publies
et verifiees contre eux par `tests/test_final_status.py`.
"""
from __future__ import annotations

import hashlib
import json

from src.config.settings import PROJECT_ROOT

OUT = PROJECT_ROOT / "models" / "FINAL_STATUS.json"

STATUS: dict[str, object] = {
    # ---------------------------------------------------------- forecasting
    "forecasting_status": "validated",
    "forecasting_daily_model": "CrostonOptimized",
    "forecasting_30d_model": "LightGBM_direct_per_horizon",
    "forecasting_wape30_macro": 0.25831,   # micro poolee : 0,25743
    # MACRO : moyenne des six fenetres. Le biais poole vaut -0,02593.
    "forecasting_bias": -0.02589,
    # -------------------------------------------------------------- pricing
    "pricing_previous_result_status": "invalidated_due_to_target_leakage",
    "pricing_accuracy_model": "lgbm_l1_mediane",
    "pricing_accuracy_wape": 0.5218,
    "pricing_accuracy_bias": -0.1814,
    "pricing_operational_volume_model": "lgbm_tweedie_moyenne",
    "pricing_operational_wape": 0.5526,
    "pricing_operational_bias": 0.0013,
    "pricing_status": "exploratory_non_causal",
    "automatic_pricing_allowed": False,
    # ------------------------------------------------------- recommandation
    "general_recommendation_model": "popularite_globale",
    "basket_complement_model": "none_validated",
    "basket_complement_baseline": "popularite_globale",
    "basket_previous_results_status":
        "invalidated_due_to_target_leakage_and_in_sample_evaluation",
    "session_model_status": "non_utilisable",
    "rrf_status": "exploratory_diversity_challenger",
}

#: Contrainte operationnelle bloquante, a ne jamais perdre en route.
MARGIN_SIMULATOR_RULE = {
    "margin_simulator_volume_model": "lgbm_tweedie_moyenne",
    "margin_simulator_forbidden_model": "lgbm_l1_mediane",
    "margin_simulator_forbidden_reason": (
        "lgbm_l1_mediane presente un Forecast Bias de -18,14 % : il estime la "
        "MEDIANE conditionnelle, optimale pour la WAPE mais systematiquement "
        "inferieure a l'esperance. L'utiliser sous-estimerait toute projection "
        "de marge de ~18 % dans le meme sens, sans compensation possible. Seul "
        "lgbm_tweedie_moyenne (biais +0,13 %) peut alimenter le simulateur."),
    "margin_simulator_guardrails": {
        "prix_minimum": "cout_xof",
        "marge_minimale": 0.05,
        "remises": "support historique observe uniquement",
        "validation_humaine": True,
        "application_automatique": False,
        "effet_causal_estime": False,
    },
}

PROVENANCE = {
    "corrected_on": "2026-08-18",
    "branch": "audit-independant-2026-08-18",
    "reports": {
        "leakage_correction": "reports/42_leakage_correction_report.md",
        "pricing": "reports/43_corrected_pricing_results.md",
        "recommendation": "reports/44_corrected_recommendation_results.md",
        "final_decision": "reports/45_final_corrected_decision.md",
        "superseded_index": "SUPERSEDED_RESULTS.md",
    },
    "evidence": {
        "forecasting": "models/advanced/forecasting/direct_lightgbm_predictions.parquet",
        "pricing": "reports/advanced/pricing_corrected.json",
        "recommendation": "reports/advanced/complement_honest_baseline.json",
        "leak_audit": "reports/advanced/complement_leak_audit.json",
    },
    "invalidated_preserved": {
        "pricing": "models/pricing/metadata.invalidated.json",
        "recommendation": "models/advanced/recommendation_ranking/invalidated/",
    },
    "no_model_promoted": True,
    "supabase_read_only": True,
    "pushed": False,
}


def payload() -> dict:
    return {"status": STATUS, "margin_simulator": MARGIN_SIMULATOR_RULE,
            "provenance": PROVENANCE}


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload(), indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    (OUT.parent / "FINAL_STATUS.sha256.json").write_text(
        json.dumps({OUT.name: digest}, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(STATUS, indent=2, ensure_ascii=False))
    print()
    print("sha256:", digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
