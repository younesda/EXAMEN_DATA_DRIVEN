import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed" / "final"
MODEL = ROOT / "models" / "campaign_level_pricing"


def test_campaign_dataset_has_required_grain_and_pre_campaign_features():
    frame = pd.read_parquet(OUT / "pricing_product_campaign.parquet")
    required = {"promo_key", "produit_key", "date_debut", "date_fin", "qty_campaign", "qty_control_28d", "overlap_status", "is_primary"}
    assert required <= set(frame.columns)
    assert frame[["promo_key", "produit_key"]].duplicated().sum() == 0
    assert frame["date_fin"].ge(frame["date_debut"]).all()
    assert frame["qty_campaign"].ge(0).all()
    assert frame["is_primary"].eq(frame["overlap_status"].eq("non_overlapping")).all()


def test_campaign_audit_counts_and_no_nan_targets():
    meta = json.loads((MODEL / "metadata.json").read_text(encoding="utf-8"))
    frame = pd.read_parquet(OUT / "pricing_product_campaign.parquet")
    assert meta["n_campaigns"] == 120
    assert meta["features_strictly_pre_campaign"] is True
    assert meta["post_campaign_features_used"] is False
    assert frame[["qty_campaign", "daily_mean_campaign", "remise_pct"]].notna().all().all()
    assert frame["qty_campaign"].ge(0).all()


def test_campaign_manifest_matches_artifacts():
    manifest = json.loads((MODEL / "manifest.sha256.json").read_text(encoding="utf-8"))
    for name, digest in manifest.items():
        path = ROOT / name if name.startswith("data/") else MODEL / name
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_metric_diagnostic_has_exact_wape_and_zero_baseline():
    diagnostics = json.loads((MODEL / "campaign_diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["formula"] == "sum(abs(y - y_pred)) / sum(y)"
    assert diagnostics["sum_actual"] > 0
    assert diagnostics["negative_predictions"] == 0
    assert diagnostics["nan_predictions"] == 0
    assert 0 <= diagnostics["zero_target_rate"] <= 1
    metrics = pd.read_csv(MODEL / "campaign_metrics.csv")
    zero = metrics[metrics.model.eq("baseline_zero")]
    assert (zero.wape_micro == 1.0).all()
