import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "models" / "advanced" / "pricing" / "metadata.json"
MANIFEST = ROOT / "models" / "advanced" / "pricing" / "manifest.sha256.json"


def test_pilot_gate_is_explicit_and_not_promoted():
    metadata = json.loads(META.read_text(encoding="utf-8"))
    decision = metadata["decision"]
    assert decision["validated_reference"] == "LightGBM_calibre"
    assert decision["pilot_windows"] == [1, 2]
    assert decision["gate_wape"] == 0.3956
    assert decision["pilot_gate_passed"] is False
    assert decision["optuna_launched"] is False
    assert decision["pricing_optimization_status"] == "stopped_after_pilot"


def test_pricing_populations_and_observational_guards_are_declared():
    metadata = json.loads(META.read_text(encoding="utf-8"))
    assert set(metadata["populations"]) == {
        "estimation_individuelle_supportee",
        "pooling_categorie",
        "insufficient_evidence",
    }
    flags = metadata["simulation_flags"]
    assert flags["automatic_application_allowed"] is False
    assert flags["human_validation_required"] is True
    assert flags["causal_effect_estimated"] is False
    assert flags["off_policy_evaluation_validated"] is False


def test_pricing_manifest_matches_artifacts():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for relative_path, expected_hash in manifest.items():
        artifact = MANIFEST.parent / relative_path
        assert artifact.exists(), relative_path
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        assert digest == expected_hash, relative_path
