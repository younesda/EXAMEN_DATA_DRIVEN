"""Les statuts officiels doivent correspondre aux artefacts publies.

Ce test empeche une derive silencieuse entre `models/FINAL_STATUS.json` et les
resultats reellement mesures. Aucun modele n'est re-entraine : les valeurs sont
relues depuis les predictions et les rapports deja produits.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from src.config.settings import PROJECT_ROOT
from src.pipelines.final_status import MARGIN_SIMULATOR_RULE, STATUS

FINAL = PROJECT_ROOT / "models" / "FINAL_STATUS.json"
REPORTS = PROJECT_ROOT / "reports" / "advanced"

EXPECTED_KEYS = {
    "forecasting_status", "forecasting_daily_model", "forecasting_30d_model",
    "forecasting_wape30_macro", "forecasting_bias",
    "pricing_previous_result_status", "pricing_accuracy_model", "pricing_accuracy_wape",
    "pricing_accuracy_bias", "pricing_operational_volume_model", "pricing_operational_wape",
    "pricing_operational_bias", "pricing_status", "automatic_pricing_allowed",
    "general_recommendation_model", "basket_complement_model", "basket_complement_baseline",
    "basket_previous_results_status", "session_model_status", "rrf_status",
}


def _final() -> dict:
    return json.loads(FINAL.read_text(encoding="utf-8"))


def test_every_required_status_key_is_present_and_serialised():
    assert set(STATUS) == EXPECTED_KEYS
    assert _final()["status"] == STATUS


def test_status_file_matches_its_own_manifest():
    manifest = json.loads(
        (PROJECT_ROOT / "models" / "FINAL_STATUS.sha256.json").read_text(encoding="utf-8"))
    assert manifest["FINAL_STATUS.json"] == hashlib.sha256(FINAL.read_bytes()).hexdigest()


def test_declared_forecasting_metrics_match_the_stored_predictions():
    """Les deux metriques publiees sont MACRO : moyenne des six fenetres.

    Le biais poole (-0,02593) et le biais macro (-0,02589) different ; publier
    l'un sous le nom de l'autre serait exactement le melange macro/micro que ce
    projet s'interdit. `forecasting_bias` est le macro, coherent avec
    `forecasting_wape30_macro`.
    """
    predictions = pd.read_parquet(
        PROJECT_ROOT / "models/advanced/forecasting/direct_lightgbm_predictions.parquet")
    totals = predictions.groupby(["window", "produit_key"])[["y", "pred"]].sum()
    macro_wape = (totals.groupby("window")
                  .apply(lambda g: (g.pred - g.y).abs().sum() / g.y.sum(),
                         include_groups=False).mean())
    macro_bias = (predictions.groupby("window")
                  .apply(lambda g: (g.pred - g.y).sum() / g.y.sum(),
                         include_groups=False).mean())
    pooled_bias = (predictions.pred - predictions.y).sum() / predictions.y.sum()
    assert STATUS["forecasting_wape30_macro"] == pytest.approx(macro_wape, abs=1e-5)
    assert STATUS["forecasting_bias"] == pytest.approx(macro_bias, abs=1e-5)
    # Le poole est distinct : la confusion doit rester detectable.
    assert pooled_bias == pytest.approx(-0.02593, abs=1e-5)
    assert STATUS["forecasting_bias"] != pytest.approx(pooled_bias, abs=1e-6)
    assert STATUS["forecasting_status"] == "validated"


def test_declared_pricing_metrics_match_the_corrected_experiment():
    payload = json.loads((REPORTS / "pricing_corrected.json").read_text(encoding="utf-8"))
    summary = {row["model"]: row for row in payload["summary"]}
    accuracy = summary[STATUS["pricing_accuracy_model"]]
    operational = summary[STATUS["pricing_operational_volume_model"]]
    assert STATUS["pricing_accuracy_wape"] == pytest.approx(accuracy["wape"], abs=5e-5)
    assert STATUS["pricing_accuracy_bias"] == pytest.approx(accuracy["forecast_bias"], abs=5e-5)
    assert STATUS["pricing_operational_wape"] == pytest.approx(operational["wape"], abs=5e-5)
    assert STATUS["pricing_operational_bias"] == pytest.approx(
        operational["forecast_bias"], abs=5e-5)
    assert payload["decisions"]["meilleur_predicteur_wape"]["modele"] == STATUS["pricing_accuracy_model"]
    assert payload["decisions"]["meilleur_volume_biais_acceptable"]["modele"] == (
        STATUS["pricing_operational_volume_model"])


def test_declared_recommendation_status_matches_the_corrected_experiment():
    payload = json.loads((REPORTS / "complement_honest_baseline.json").read_text(encoding="utf-8"))
    business = payload["statut_metier"]
    assert STATUS["basket_complement_model"] == business["basket_complement_model"]
    assert STATUS["basket_complement_baseline"] == business["basket_complement_baseline"]
    assert business["reason"] == "no_complementarity_signal"
    assert payload["modele_promu"] is None


def test_margin_simulator_refuses_the_biased_accuracy_model():
    rule = MARGIN_SIMULATOR_RULE
    assert rule["margin_simulator_volume_model"] == STATUS["pricing_operational_volume_model"]
    assert rule["margin_simulator_forbidden_model"] == STATUS["pricing_accuracy_model"]
    assert "-18,14" in rule["margin_simulator_forbidden_reason"]
    assert abs(STATUS["pricing_accuracy_bias"]) > .03
    assert abs(STATUS["pricing_operational_bias"]) <= .03
    assert rule["margin_simulator_guardrails"]["application_automatique"] is False
    assert rule["margin_simulator_guardrails"]["effet_causal_estime"] is False
    assert _final()["margin_simulator"] == rule


def test_no_automatic_action_is_authorised():
    assert STATUS["automatic_pricing_allowed"] is False
    assert STATUS["pricing_status"] == "exploratory_non_causal"
    assert STATUS["session_model_status"] == "non_utilisable"
    assert STATUS["rrf_status"] == "exploratory_diversity_challenger"
    provenance = _final()["provenance"]
    assert provenance["no_model_promoted"] is True
    assert provenance["supabase_read_only"] is True
    assert provenance["pushed"] is False


def test_provenance_points_at_files_that_exist():
    provenance = _final()["provenance"]
    for group in ("reports", "evidence"):
        for label, relative in provenance[group].items():
            assert (PROJECT_ROOT / relative).exists(), label + " -> " + relative
    for label, relative in provenance["invalidated_preserved"].items():
        assert (PROJECT_ROOT / relative).exists(), label + " -> " + relative


def test_renumbered_reports_exist_and_old_numbers_are_gone():
    reports = PROJECT_ROOT / "reports"
    for name in ("42_leakage_correction_report.md", "43_corrected_pricing_results.md",
                 "44_corrected_recommendation_results.md", "45_final_corrected_decision.md"):
        assert (reports / name).exists(), name
    for name in ("17_leakage_correction_report.md", "18_corrected_pricing_results.md",
                 "19_corrected_recommendation_results.md", "20_final_corrected_decision.md"):
        assert not (reports / name).exists(), name
    # Les rapports historiques homonymes doivent, eux, etre intacts.
    for name in ("17_verification_checkpoints.md", "18_backtest_rapport_final.md",
                 "19_verification_operationnelle.md", "20_backtest_lightgbm_log.jsonl"):
        assert (reports / name).exists(), name


def test_no_document_still_links_to_the_old_report_numbers():
    stale = ("17_leakage_correction_report", "18_corrected_pricing_results",
             "19_corrected_recommendation_results", "20_final_corrected_decision")
    offenders = []
    for path in list(PROJECT_ROOT.glob("*.md")) + list((PROJECT_ROOT / "reports").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in stale):
            offenders.append(path.name)
    assert not offenders, offenders


def test_no_tracked_file_leaks_an_absolute_local_path():
    """Un chemin absolu exposerait le nom d'utilisateur et l'arborescence locale."""
    import re
    import subprocess

    pattern = re.compile(r"C:[\/]{1,2}Users[\/]|/home/[a-z0-9_]+/|OneDrive[\/]")
    tracked = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True).stdout.split("\n")
    suffixes = {".md", ".json", ".py", ".yaml", ".yml", ".txt", ".csv", ".jsonl", ".cfg", ".ini"}
    offenders = []
    for relative in tracked:
        if not relative:
            continue
        path = PROJECT_ROOT / relative
        if path.suffix.lower() not in suffixes or not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        if pattern.search(text):
            offenders.append(relative)
    assert not offenders, "chemins locaux absolus versionnes : " + str(offenders)
