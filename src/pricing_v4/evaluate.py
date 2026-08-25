"""Metriques, bootstrap, permutation et correction de Holm — grain produit.

Toutes les statistiques d'inference (bootstrap, permutation) rééchantillonnent
des PRODUITS entiers, jamais des lignes individuelles : une decision n'est pas
une unite statistiquement independante de ses voisines temporelles pour le
meme produit (regroupement par produit, cf. consigne).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
MARGIN_FLOOR_RATE = 0.05


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = max(float(np.abs(y_true).sum()), 1e-9)
    return float(np.abs(y_pred - y_true).sum() / denom)


def forecast_bias(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = max(float(np.abs(y_true).sum()), 1e-9)
    return float((y_pred - y_true).sum() / denom)


def point_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    y_pred = np.maximum(0.0, np.asarray(y_pred, dtype=float))
    y_true = np.asarray(y_true, dtype=float)
    error = y_pred - y_true
    return {
        "wape_micro": wape(y_true, y_pred),
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "forecast_bias": forecast_bias(y_true, y_pred),
        "n": int(len(y_true)),
    }


def macro_wape_by_product(frame: pd.DataFrame, y_true_col: str, y_pred_col: str) -> float:
    """WAPE moyennee par produit (chaque produit pese autant, quel que soit son volume)."""
    per_product = frame.groupby("produit_key").apply(
        lambda g: wape(g[y_true_col].to_numpy(), g[y_pred_col].to_numpy()), include_groups=False)
    return float(per_product.mean())


def margin_metrics(frame: pd.DataFrame, predicted_units: np.ndarray, unit_margin_col: str) -> dict:
    """Erreur et niveau de marge, a partir des unites predites et de la marge unitaire observee."""
    predicted_margin = predicted_units * frame[unit_margin_col].to_numpy()
    real_margin = frame["margin_window_xof_7j"].to_numpy()
    denom = max(float(np.abs(real_margin).sum()), 1e-9)
    margin_error = float(np.abs(predicted_margin - real_margin).sum() / denom)
    mean_margin = float(np.mean(predicted_margin))
    return {"margin_error": margin_error, "mean_predicted_margin_xof": mean_margin}


def margin_floor_violations(frame: pd.DataFrame) -> dict:
    """Verifie les garde-fous metier sur le prix reellement applique (jamais sur le prix propose)."""
    price = frame["prix_applique_xof"].to_numpy()
    cost = frame["cout_xof"].to_numpy()
    below_cost = int((price < cost).sum())
    margin_rate = np.divide(price - cost, price, out=np.zeros_like(price), where=price > 0)
    below_floor = int((margin_rate < MARGIN_FLOOR_RATE).sum())
    return {"n_price_below_cost": below_cost, "n_margin_below_floor": below_floor,
            "margin_floor_rate": MARGIN_FLOOR_RATE}


def synthetic_elasticity_recovery(frame: pd.DataFrame, predicted_units: np.ndarray) -> dict:
    """Diagnostic : elasticite implicite reelle vs predite, comparee au 1,8 du generateur.

    Purement diagnostique — ne sert jamais a selectionner un modele. Regression
    log(1+y) ~ discount_applied + effet fixe categorie, sur les donnees reelles
    puis sur les predictions, en pourcentage par point de remise.
    """
    def _slope(y: np.ndarray) -> float:
        x = frame["discount_applied"].to_numpy(dtype=float)
        log_y = np.log1p(np.maximum(0.0, y))
        categories = pd.get_dummies(frame["categorie"], prefix="cat", dtype=float).to_numpy()
        design = np.column_stack([np.ones(len(x)), x, categories])
        coefficients, *_ = np.linalg.lstsq(design, log_y, rcond=None)
        return float(coefficients[1])

    real_slope = _slope(frame["units_sold_window_7j"].to_numpy())
    predicted_slope = _slope(np.maximum(0.0, predicted_units))
    reference_elasticity = 1.8 / 100  # 1,8 en variation relative pour 100 points de remise
    return {
        "real_log_units_slope_per_discount_point": real_slope,
        "predicted_log_units_slope_per_discount_point": predicted_slope,
        "reference_generator_elasticity_100pts": 1.8,
        "note": "diagnostic uniquement ; jamais utilise comme critere de selection du modele",
    }


def _product_level_partial_sums(frame: pd.DataFrame, y_true_col: str,
                                pred_a: np.ndarray, pred_b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Somme par produit de |y_true|, |pred_a-y_true| et |pred_b-y_true|.

    La WAPE est un ratio de sommes ; rééchantillonner des produits revient donc
    à rééchantillonner ces trois sommes partielles, ce qui rend chaque tirage
    un simple produit matriciel au lieu d'une concaténation de sous-tables.
    """
    codes, _ = pd.factorize(frame["produit_key"].to_numpy())
    n_products = codes.max() + 1
    y_true = frame[y_true_col].to_numpy(dtype=float)
    error_a = np.abs(np.asarray(pred_a, dtype=float) - y_true)
    error_b = np.abs(np.asarray(pred_b, dtype=float) - y_true)
    sum_y = np.bincount(codes, weights=np.abs(y_true), minlength=n_products)
    sum_error_a = np.bincount(codes, weights=error_a, minlength=n_products)
    sum_error_b = np.bincount(codes, weights=error_b, minlength=n_products)
    return sum_y, sum_error_a, sum_error_b


def product_level_bootstrap(frame: pd.DataFrame, y_true_col: str, pred_a: np.ndarray,
                            pred_b: np.ndarray, draws: int = 3000, seed: int = SEED) -> dict:
    """IC95% bootstrap de la difference de WAPE (a - b), reechantillonnage par produit."""
    sum_y, sum_error_a, sum_error_b = _product_level_partial_sums(frame, y_true_col, pred_a, pred_b)
    n = len(sum_y)
    observed = float((sum_error_a.sum() - sum_error_b.sum()) / max(sum_y.sum(), 1e-9))
    rng = np.random.default_rng(seed)
    draw_index = rng.integers(0, n, size=(draws, n))
    denom = sum_y[draw_index].sum(axis=1)
    denom = np.where(denom == 0, 1e-9, denom)
    samples = (sum_error_a[draw_index].sum(axis=1) - sum_error_b[draw_index].sum(axis=1)) / denom
    return {"observed_diff": observed,
            "ci95_low": float(np.quantile(samples, .025)),
            "ci95_high": float(np.quantile(samples, .975)),
            "draws": draws, "n_products": int(n)}


def product_level_permutation(frame: pd.DataFrame, y_true_col: str, pred_a: np.ndarray,
                              pred_b: np.ndarray, draws: int = 2000, seed: int = SEED) -> float:
    """P-value brute d'un test de permutation, en echangeant a/b par produit entier."""
    sum_y, sum_error_a, sum_error_b = _product_level_partial_sums(frame, y_true_col, pred_a, pred_b)
    n = len(sum_y)
    total_y = max(sum_y.sum(), 1e-9)
    observed = float((sum_error_a.sum() - sum_error_b.sum()) / total_y)
    rng = np.random.default_rng(seed)
    swap = rng.random((draws, n)) < 0.5
    # Sous permutation, chaque produit echange (error_a, error_b) avec probabilite 1/2.
    swapped_a = np.where(swap, sum_error_b, sum_error_a)
    swapped_b = np.where(swap, sum_error_a, sum_error_b)
    stats = (swapped_a.sum(axis=1) - swapped_b.sum(axis=1)) / total_y
    count_as_extreme = int((np.abs(stats) >= abs(observed)).sum())
    return (count_as_extreme + 1) / (draws + 1)


def holm_correction(p_values: dict[str, float]) -> dict[str, float]:
    """Correction de Holm-Bonferroni pour comparaisons multiples."""
    items = sorted(p_values.items(), key=lambda item: item[1])
    m = len(items)
    corrected = {}
    running_max = 0.0
    for rank, (name, raw_p) in enumerate(items, start=1):
        adjusted = min(1.0, raw_p * (m - rank + 1))
        running_max = max(running_max, adjusted)
        corrected[name] = running_max
    return corrected
