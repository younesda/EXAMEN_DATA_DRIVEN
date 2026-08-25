from __future__ import annotations

import pandas as pd

from src.experiments.advanced_forecasting_candidates import metrics


def test_metriques_cumulees_ne_sont_pas_confondues_avec_le_quotidien():
    frame = pd.DataFrame({"produit_key": ["P", "P"], "horizon": [1, 2],
                          "y": [1.0, 1.0], "pred": [0.0, 2.0]})
    result = metrics(frame)
    assert result["wape_daily"] == 1.0
    assert result["wape_cum_30"] == 0.0


def test_biais_signe():
    frame = pd.DataFrame({"produit_key": ["P"], "horizon": [1], "y": [2.0], "pred": [1.0]})
    assert metrics(frame)["bias"] == -0.5
