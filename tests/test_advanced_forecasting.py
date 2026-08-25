"""Tests anti-fuite et déterminisme du forecasting avancé."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.experiments.advanced_forecasting import horizon_frame


def _features() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=40)
    rows = []
    for product in ("P1", "P2"):
        for idx, date in enumerate(dates):
            rows.append({"produit_key": product, "ds": date, "y": float(idx % 3), "remise_pct": 5.0})
    return pd.DataFrame(rows)


def test_cible_directe_est_exactement_j_plus_h():
    data = _features()
    frame = horizon_frame(data, 7)
    row = frame[(frame.produit_key == "P1") & (frame.ds == pd.Timestamp("2026-01-10"))].iloc[0]
    assert row.target_ds == pd.Timestamp("2026-01-17")
    expected = data[(data.produit_key == "P1") & (data.ds == row.target_ds)].y.item()
    assert row.target == expected


def test_perturber_le_futur_ne_change_pas_les_colonnes_du_cutoff():
    data = _features()
    original = horizon_frame(data, 5)
    perturbed = data.copy()
    perturbed.loc[perturbed.ds > pd.Timestamp("2026-01-20"), "y"] = 9999
    changed = horizon_frame(perturbed, 5)
    columns = [c for c in original.columns if c not in {"target", "y"}]
    left = original[original.ds <= pd.Timestamp("2026-01-20")][columns].reset_index(drop=True)
    right = changed[changed.ds <= pd.Timestamp("2026-01-20")][columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_horizon_frame_deterministe():
    data = _features()
    pd.testing.assert_frame_equal(horizon_frame(data, 30), horizon_frame(data, 30))


def test_purchase_web_absent_des_features_autorisees():
    from src.experiments.advanced_forecasting import BASE_FEATURES
    assert all("purchase" not in feature for feature in BASE_FEATURES)
    assert "stock_at_cutoff" in BASE_FEATURES
    assert all("stock_future" not in feature for feature in BASE_FEATURES)
