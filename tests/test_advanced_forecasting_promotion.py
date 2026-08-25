import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parents[1]


def test_direct_candidate_promotion_scope_and_quality():
    metadata = json.loads((ROOT / "models/advanced/forecasting/metadata.json").read_text())
    assert metadata["decisions"]["planning_30d_model"] == "LightGBM_direct_per_horizon"
    assert metadata["decisions"]["operational_daily_model"] == "CrostonOptimized"
    assert metadata["comparison"]["cumulative_30d_windows_won_vs_validated_lightgbm"] >= 4
    assert metadata["bootstrap"]["cumulative_30d_vs_validated_lightgbm"]["ci95_high"] < 0
    assert metadata["quality"]["nan_or_infinite"] == 0
    assert metadata["quality"]["negative"] == 0


def test_direct_predictions_have_all_horizons_and_windows():
    path = ROOT / "models/advanced/forecasting/direct_lightgbm_predictions.parquet"
    frame = pd.read_parquet(path)
    assert set(frame.window.unique()) == set(range(1, 7))
    assert set(frame.horizon.unique()) == set(range(1, 31))
    assert frame.pred.notna().all()
    assert (frame.pred >= 0).all()
