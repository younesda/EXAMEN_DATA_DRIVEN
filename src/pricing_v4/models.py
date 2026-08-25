"""Zoo de modeles pricing V4.

Chaque modele est represente par un `FittedModel` : un nom, un type (`kind`)
et un `state` — un dictionnaire de composants picklables (modeles scikit-learn/
LightGBM/CatBoost, tables de moyennes, scalers). La prediction passe par la
fonction de dispatch `predict()`, definie au niveau module : contrairement a
une fermeture (closure) capturant des variables locales, cette conception est
serialisable par `joblib.dump` (une fermeture imbriquee ne l'est pas — verifie
lors de la mise au point de ce module).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.linear_model import PoissonRegressor, TweedieRegressor
from sklearn.preprocessing import StandardScaler

from src.pricing_v4.dataset import ALL_FEATURES

SEED = 42

try:
    from catboost import CatBoostRegressor
    _HAS_CATBOOST = True
except ImportError:
    _HAS_CATBOOST = False


def _design_matrix(frame: pd.DataFrame) -> np.ndarray:
    return frame[ALL_FEATURES].to_numpy(dtype=float)


def _clip(values: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, np.asarray(values, dtype=float))


@dataclass
class FittedModel:
    name: str
    kind: str
    state: dict[str, Any] = field(default_factory=dict)
    train_seconds: float = 0.0

    def predict_fn(self, frame: pd.DataFrame) -> np.ndarray:
        return predict(self, frame)


def predict(model: FittedModel, frame: pd.DataFrame) -> np.ndarray:
    """Dispatch de prediction unique, sans fermeture : serialisable en l'etat."""
    kind = model.kind
    state = model.state

    if kind == "baseline_map":
        values = frame.produit_key.map(state["table"]).fillna(state["overall"])
        return values.to_numpy(dtype=float)

    if kind == "sklearn_scaled":
        x = state["scaler"].transform(_design_matrix(frame))
        return _clip(state["model"].predict(x))

    if kind == "tree_direct":
        return _clip(state["model"].predict(frame[ALL_FEATURES]))

    if kind == "hurdle":
        probability_positive = state["classifier"].predict_proba(frame[ALL_FEATURES])[:, 1]
        expected_positive = _clip(state["regressor"].predict(frame[ALL_FEATURES]))
        return probability_positive * expected_positive

    if kind == "t_learner":
        non_treatment = state["non_treatment_features"]
        predictions = np.empty(len(frame))
        for arm, group in frame.groupby("treatment_group"):
            arm_model = state["arm_models"].get(arm, state["fallback"])
            predictions[frame.treatment_group.eq(arm).to_numpy()] = arm_model.predict(
                group[non_treatment])
        return _clip(predictions)

    if kind == "ensemble":
        total = np.zeros(len(frame))
        weight_sum = 0.0
        for member, weight in zip(state["members"], state["weights"]):
            if weight <= 0:
                continue
            total += weight * predict(member, frame)
            weight_sum += weight
        if weight_sum == 0:
            return np.zeros(len(frame))
        return _clip(total / weight_sum)

    raise ValueError(f"kind inconnu: {kind}")


def baseline_mean(train: pd.DataFrame, target: str) -> FittedModel:
    table = train.groupby("produit_key")[target].mean()
    overall = float(train[target].mean())
    return FittedModel("baseline_moyenne_produit", "baseline_map",
                       {"table": table, "overall": overall})


def baseline_median(train: pd.DataFrame, target: str) -> FittedModel:
    table = train.groupby("produit_key")[target].median()
    overall = float(train[target].median())
    return FittedModel("baseline_mediane_produit", "baseline_map",
                       {"table": table, "overall": overall})


def glm_poisson(train: pd.DataFrame, target: str) -> FittedModel:
    scaler = StandardScaler()
    x = scaler.fit_transform(_design_matrix(train))
    model = PoissonRegressor(alpha=0.3, max_iter=500)
    model.fit(x, np.maximum(0.0, train[target].to_numpy(dtype=float)))
    return FittedModel("GLM_Poisson", "sklearn_scaled", {"model": model, "scaler": scaler})


def glm_tweedie(train: pd.DataFrame, target: str) -> FittedModel:
    scaler = StandardScaler()
    x = scaler.fit_transform(_design_matrix(train))
    model = TweedieRegressor(power=1.3, alpha=0.3, link="log", max_iter=500)
    model.fit(x, np.maximum(1e-6, train[target].to_numpy(dtype=float)))
    return FittedModel("GLM_Tweedie", "sklearn_scaled", {"model": model, "scaler": scaler})


_LGBM_PARAMS = dict(n_estimators=180, num_leaves=15, min_child_samples=25,
                    learning_rate=0.05, subsample=0.85, colsample_bytree=0.85,
                    reg_lambda=0.5, random_state=SEED, n_jobs=2, verbosity=-1)


def lightgbm_poisson(train: pd.DataFrame, target: str) -> FittedModel:
    model = LGBMRegressor(objective="poisson", **_LGBM_PARAMS)
    model.fit(train[ALL_FEATURES], np.maximum(0.0, train[target]))
    return FittedModel("LightGBM_Poisson", "tree_direct", {"model": model})


def lightgbm_tweedie(train: pd.DataFrame, target: str) -> FittedModel:
    model = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, **_LGBM_PARAMS)
    model.fit(train[ALL_FEATURES], np.maximum(0.0, train[target]))
    return FittedModel("LightGBM_Tweedie", "tree_direct", {"model": model})


def lightgbm_l1(train: pd.DataFrame, target: str) -> FittedModel:
    model = LGBMRegressor(objective="regression_l1", **_LGBM_PARAMS)
    model.fit(train[ALL_FEATURES], train[target])
    return FittedModel("LightGBM_L1", "tree_direct", {"model": model})


def lightgbm_monotone(train: pd.DataFrame, target: str) -> FittedModel:
    """Contrainte monotone : la cible ne peut pas decroitre quand la remise augmente."""
    constraints = [1 if name in ("discount_proposed", "discount_applied") else 0
                  for name in ALL_FEATURES]
    model = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3,
                          monotone_constraints=constraints, **_LGBM_PARAMS)
    model.fit(train[ALL_FEATURES], np.maximum(0.0, train[target]))
    return FittedModel("LightGBM_Monotone", "tree_direct", {"model": model})


def catboost_model(train: pd.DataFrame, target: str) -> FittedModel | None:
    """CatBoost Poisson pour les unites (cible entiere, faible echelle) ; MAE pour
    le chiffre d'affaires et la marge (montants en XOF, jusqu'a plusieurs
    millions) — la perte Poisson de CatBoost n'est pas concue pour des cibles
    a cette echelle et y degenere silencieusement (WAPE=1, biais proche de -1
    constate en pilote)."""
    if not _HAS_CATBOOST:
        return None
    if target == "units_sold_window_7j":
        loss, name = "Poisson", "CatBoost_Poisson"
    else:
        loss, name = "MAE", "CatBoost_MAE"
    model = CatBoostRegressor(loss_function=loss, iterations=200, depth=5,
                              learning_rate=0.06, random_seed=SEED, verbose=False)
    model.fit(train[ALL_FEATURES], np.maximum(0.0, train[target]))
    return FittedModel(name, "tree_direct", {"model": model})


def hurdle_model(train: pd.DataFrame, target: str) -> FittedModel:
    """Classification zero/positif, puis regression sur la partie strictement positive."""
    is_positive = (train[target] > 0).astype(int)
    classifier = LGBMClassifier(n_estimators=120, num_leaves=15, min_child_samples=25,
                                learning_rate=0.05, random_state=SEED, n_jobs=2, verbosity=-1)
    classifier.fit(train[ALL_FEATURES], is_positive)

    positive_rows = train[train[target] > 0]
    regressor = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.2, **_LGBM_PARAMS)
    regressor.fit(positive_rows[ALL_FEATURES], positive_rows[target])
    return FittedModel("Hurdle_zero_positif", "hurdle",
                       {"classifier": classifier, "regressor": regressor})


def s_learner(train: pd.DataFrame, target: str) -> FittedModel:
    """Un seul modele, la remise (proposee/appliquee) est une feature parmi les autres."""
    model = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, **_LGBM_PARAMS)
    model.fit(train[ALL_FEATURES], np.maximum(0.0, train[target]))
    return FittedModel("S_learner", "tree_direct", {"model": model})


_NON_TREATMENT_FEATURES = [name for name in ALL_FEATURES
                          if name not in ("discount_proposed", "discount_applied",
                                         "discount_x_category", "discount_x_abc")]


def t_learner(train: pd.DataFrame, target: str) -> FittedModel:
    """Un modele distinct par groupe de traitement (bras de remise)."""
    arm_models: dict[str, LGBMRegressor] = {}
    for arm, group in train.groupby("treatment_group"):
        model = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3,
                              n_estimators=120, num_leaves=11, min_child_samples=20,
                              learning_rate=0.06, random_state=SEED, n_jobs=2, verbosity=-1)
        model.fit(group[_NON_TREATMENT_FEATURES], np.maximum(0.0, group[target]))
        arm_models[arm] = model
    fallback = LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, **_LGBM_PARAMS)
    fallback.fit(train[_NON_TREATMENT_FEATURES], np.maximum(0.0, train[target]))
    return FittedModel("T_learner", "t_learner",
                       {"arm_models": arm_models, "fallback": fallback,
                        "non_treatment_features": _NON_TREATMENT_FEATURES})


def constrained_ensemble(fitted: list[FittedModel], weights: dict[str, float]) -> FittedModel:
    ordered_weights = [weights.get(member.name, 0.0) for member in fitted]
    return FittedModel("Ensemble_contraint", "ensemble",
                       {"members": fitted, "weights": ordered_weights})


MODEL_FACTORIES: dict[str, Any] = {
    "baseline_moyenne_produit": baseline_mean,
    "baseline_mediane_produit": baseline_median,
    "GLM_Poisson": glm_poisson,
    "GLM_Tweedie": glm_tweedie,
    "LightGBM_Poisson": lightgbm_poisson,
    "LightGBM_Tweedie": lightgbm_tweedie,
    "LightGBM_L1": lightgbm_l1,
    "LightGBM_Monotone": lightgbm_monotone,
    "CatBoost_Poisson": catboost_model,
    "Hurdle_zero_positif": hurdle_model,
    "S_learner": s_learner,
    "T_learner": t_learner,
}
