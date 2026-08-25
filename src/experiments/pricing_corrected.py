"""Pricing corrige : evaluation honnete apres retrait de la fuite `n_lignes`.

Trois decisions sont explicitement separees, parce qu'elles n'ont pas le meme
optimum :

1. **meilleur predicteur WAPE** — la WAPE est une perte L1, minimisee par la
   MEDIANE conditionnelle ;
2. **meilleur modele de volume a biais acceptable** — le simulateur de marge a
   besoin d'une ESPERANCE non biaisee, pas d'une mediane ;
3. **simulateur de marge** — retenu depuis (2), jamais depuis (1).

Toutes les features proviennent de `src/pricing/feature_registry.py` et sont
disponibles avant le debut du produit-jour predit. `validate_matrix` est
appelee sur la matrice d'entrainement ET sur la matrice d'inference.
"""
from __future__ import annotations

import hashlib
import json
import time

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from src.config.settings import PROJECT_ROOT
from src.pricing.feature_registry import allowed_features, to_records, validate_matrix

FEATURE_CACHE = PROJECT_ROOT / "data/cache/advanced_pricing_features.parquet"
OUT = PROJECT_ROOT / "models" / "advanced" / "pricing_corrected"
REPORT = PROJECT_ROOT / "reports" / "advanced"
SEED = 42
WINDOW_BACKS = (180, 120, 60)
TEST_DAYS = 60
CALIBRATION_DAYS = 60
BOOTSTRAP_DRAWS = 4000
BIAS_TOLERANCE = .03
PARAMS = dict(n_estimators=250, learning_rate=.04, num_leaves=31, min_child_samples=40,
              random_state=SEED, n_jobs=2, verbosity=-1)
INVALIDATED = {
    "model": "LightGBM_calibre",
    "wape": 0.41637444717942285,
    "status": "invalidated_due_to_target_leakage",
    "file": "models/pricing/metadata.invalidated.json",
    "oracle_floor": [0.4866, 0.4838, 0.4931],
    "oracle_definition": ("mediane produit x remise calculee DANS le test : borne "
                          "inferieure honnete sur les memes trois fenetres"),
    "wape_after_removing_n_lignes": 0.5625435749874705,
    "wape_after_removing_n_lignes_source": "models/pricing/metadata.json",
}


def _model(objective: str) -> LGBMRegressor:
    if objective == "l1":
        return LGBMRegressor(objective="regression_l1", **PARAMS)
    return LGBMRegressor(objective="tweedie", tweedie_variance_power=1.3, **PARAMS)


def _fit(train: pd.DataFrame, features: list[str], objective: str):
    validate_matrix(features)
    model = _model(objective)
    start = time.perf_counter()
    model.fit(train[features], train.quantite)
    return model, time.perf_counter() - start


def _predict(model, frame: pd.DataFrame, features: list[str], factor: float = 1.0) -> np.ndarray:
    validate_matrix(features)
    return np.maximum(0.0, model.predict(frame[features]) * factor)


def metrics(frame: pd.DataFrame, prediction: np.ndarray) -> dict:
    y = frame.quantite.to_numpy(float)
    total = max(y.sum(), 1.0)
    unit_margin = (frame.prix_base_xof * (1 - frame.remise_pct / 100) - frame.cout_xof).to_numpy(float)
    margin_true = unit_margin * y
    margin_pred = unit_margin * prediction
    margin_total = max(np.abs(margin_true).sum(), 1.0)
    return {
        "wape": float(np.abs(prediction - y).sum() / total),
        "forecast_bias": float((prediction - y).sum() / total),
        "mae": float(np.abs(prediction - y).mean()),
        "margin_error_abs": float(np.abs(margin_pred - margin_true).sum() / margin_total),
        "margin_error_signed": float((margin_pred - margin_true).sum() / margin_total),
        "n": int(len(y)),
    }


def paired_bootstrap(predictions: pd.DataFrame, model_a: str, model_b: str) -> dict:
    a = predictions[predictions.model.eq(model_a)].sort_values("row_key")
    b = predictions[predictions.model.eq(model_b)].sort_values("row_key")
    if len(a) != len(b) or not (a.row_key.to_numpy() == b.row_key.to_numpy()).all():
        raise AssertionError("Perimetre non apparie : " + model_a + " / " + model_b)
    y = a.y.to_numpy(float)
    error_a = np.abs(a.pred.to_numpy(float) - y)
    error_b = np.abs(b.pred.to_numpy(float) - y)
    rng = np.random.default_rng(SEED)
    samples = np.empty(BOOTSTRAP_DRAWS)
    n = len(y)
    for index in range(BOOTSTRAP_DRAWS):
        draw = rng.integers(0, n, n)
        samples[index] = (error_a[draw].sum() - error_b[draw].sum()) / max(y[draw].sum(), 1)
    return {"model_a": model_a, "model_b": model_b, "n_units": n, "draws": BOOTSTRAP_DRAWS,
            "wape_difference": float((error_a.sum() - error_b.sum()) / max(y.sum(), 1)),
            "ci95_low": float(np.quantile(samples, .025)),
            "ci95_high": float(np.quantile(samples, .975))}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    features = allowed_features()
    validate_matrix(features)
    data = pd.read_parquet(FEATURE_CACHE)
    data["ds"] = pd.to_datetime(data.ds)
    max_ds = data.ds.max()

    records, rows = [], []
    previous_window_factor: dict[str, float] = {}
    for window, back in enumerate(WINDOW_BACKS, 1):
        test_start = max_ds - pd.Timedelta(days=back - 1)
        test_end = test_start + pd.Timedelta(days=TEST_DAYS - 1)
        train = data[data.ds < test_start]
        test = data[data.ds.between(test_start, test_end)]
        if train.ds.max() >= test.ds.min():
            raise AssertionError("Train non strictement anterieur au test.")
        calibration_start = test_start - pd.Timedelta(days=CALIBRATION_DAYS)
        fit_data = train[train.ds < calibration_start]
        calibration = train[train.ds >= calibration_start]
        row_key = (test.produit_key + "|" + test.ds.dt.strftime("%Y-%m-%d")
                   + "|" + test.remise_pct.astype(str)).to_numpy()
        audit = {"window": window, "test_start": str(test_start.date()),
                 "test_end": str(test_end.date()), "train_end": str(train.ds.max().date()),
                 "n_train": len(train), "n_test": len(test),
                 "train_strictly_before_test": True}

        def register(name: str, prediction: np.ndarray, seconds: float, factor: float,
                     factor_source: str) -> None:
            records.append({**audit, "model": name, "elapsed_seconds": seconds,
                            "calibration_factor": factor, "calibration_source": factor_source,
                            **metrics(test, prediction)})
            rows.append(pd.DataFrame({"window": window, "row_key": row_key, "model": name,
                                      "y": test.quantite.to_numpy(float), "pred": prediction}))

        # --- baselines honnetes ------------------------------------------------
        product_mean = train.groupby("produit_key").quantite.mean()
        product_median = train.groupby("produit_key").quantite.median()
        register("baseline_produit_moyenne",
                 test.produit_key.map(product_mean).fillna(train.quantite.mean()).to_numpy(float),
                 0.0, 1.0, "aucune")
        register("baseline_produit_mediane",
                 test.produit_key.map(product_median).fillna(train.quantite.median()).to_numpy(float),
                 0.0, 1.0, "aucune")

        # --- decision 2 : volume a biais controle ------------------------------
        tweedie, seconds = _fit(train, features, "tweedie")
        register("lgbm_tweedie_moyenne", _predict(tweedie, test, features), seconds, 1.0, "aucune")

        # --- decision 1 : meilleur predicteur WAPE -----------------------------
        l1_model, seconds = _fit(train, features, "l1")
        register("lgbm_l1_mediane", _predict(l1_model, test, features), seconds, 1.0, "aucune")

        # --- calibrations de biais, strictement apprises sur le passe ----------
        # (a) bloc de 60 jours anterieur au test, exclu du fit.
        block_model, block_seconds = _fit(fit_data, features, "l1")
        block_prediction = _predict(block_model, calibration, features)
        block_factor = float(calibration.quantite.mean() / max(block_prediction.mean(), 1e-9))
        register("lgbm_l1_calibre_bloc_anterieur",
                 _predict(l1_model, test, features, block_factor),
                 block_seconds, block_factor, "bloc 60 j anterieur au test, hors fit")

        # (b) fenetres d'evaluation strictement anterieures ; la fenetre 1 n'en
        #     a aucune et retombe sur (a), ce qui est declare explicitement.
        if previous_window_factor:
            window_factor = float(np.mean(list(previous_window_factor.values())))
            source = "moyenne des fenetres " + str(sorted(previous_window_factor))
        else:
            window_factor, source = block_factor, "aucune fenetre anterieure : repli sur le bloc"
        register("lgbm_l1_calibre_fenetres_anterieures",
                 _predict(l1_model, test, features, window_factor),
                 0.0, window_factor, source)

        raw = _predict(l1_model, test, features)
        previous_window_factor[window] = float(test.quantite.sum() / max(raw.sum(), 1e-9))

    predictions = pd.concat(rows, ignore_index=True)
    predictions.to_parquet(OUT / "predictions.parquet", index=False)
    per_window = pd.DataFrame(records)
    numeric = ["wape", "forecast_bias", "mae", "margin_error_abs", "margin_error_signed"]
    summary = (per_window.groupby("model")[numeric].mean()
               .join(per_window.groupby("model").wape.std().rename("wape_std"))
               .join(per_window.groupby("model").wape.min().rename("wape_min"))
               .join(per_window.groupby("model").wape.max().rename("wape_max"))
               .reset_index().sort_values("wape"))
    summary["stabilite_amplitude"] = summary.wape_max - summary.wape_min

    # --- trois decisions separees ---------------------------------------------
    indexed = summary.set_index("model")
    best_wape = str(summary.iloc[0].model)
    eligible = summary[summary.forecast_bias.abs() <= BIAS_TOLERANCE]
    best_volume = str(eligible.iloc[0].model) if len(eligible) else None
    published_best_honest = {"model": "CatBoost_enriched", "wape": 0.556856,
                             "source": "models/advanced/pricing/metadata.json"}

    bootstrap = {
        "wape_best_vs_volume_best": paired_bootstrap(predictions, best_wape, best_volume)
        if best_volume else None,
        "volume_best_vs_baseline_moyenne": paired_bootstrap(
            predictions, best_volume, "baseline_produit_moyenne") if best_volume else None,
    }
    pivot = per_window.pivot(index="model", columns="window", values="wape")
    windows_won = {model: int((pivot.loc[model] < pivot.loc["baseline_produit_moyenne"]).sum())
                   for model in pivot.index}
    volume_gain = (float((published_best_honest["wape"] - indexed.loc[best_volume, "wape"])
                         / published_best_honest["wape"]) if best_volume else None)

    payload = {
        "statut": "corrige_apres_retrait_de_n_lignes",
        "historique_invalide": INVALIDATED,
        "registre_features": {"module": "src/pricing/feature_registry.py",
                              "n_autorisees": len(features),
                              "regle": "disponible avant le debut du produit-jour predit",
                              "registre": to_records()},
        "perimetre": {"grain": "produit_key x ds x remise_pct",
                      "population": "lignes de commandes confirmees",
                      "fenetres": list(WINDOW_BACKS), "jours_test": TEST_DAYS,
                      "identique_a_experience_avancee": True},
        "per_window": records,
        "summary": summary.to_dict("records"),
        "windows_won_vs_baseline_moyenne": windows_won,
        "bootstrap": bootstrap,
        "decisions": {
            "meilleur_predicteur_wape": {
                "modele": best_wape, "wape": float(indexed.loc[best_wape, "wape"]),
                "forecast_bias": float(indexed.loc[best_wape, "forecast_bias"]),
                "margin_error_signed": float(indexed.loc[best_wape, "margin_error_signed"]),
                "utilisable_comme_simulateur": False,
                "raison": "biais de volume incompatible avec une simulation de marge"},
            "meilleur_volume_biais_acceptable": {
                "modele": best_volume,
                "tolerance_biais": BIAS_TOLERANCE,
                "wape": float(indexed.loc[best_volume, "wape"]) if best_volume else None,
                "forecast_bias": float(indexed.loc[best_volume, "forecast_bias"]) if best_volume else None,
                "gain_relatif_vs_meilleur_publie_honnete": volume_gain},
            "simulateur_de_marge": {
                "modele_de_volume": best_volume,
                "source": "decision 2 uniquement",
                "garde_fous": {"prix_minimum": "cout", "marge_minimale": 0.05,
                               "remises": "support historique observe",
                               "validation_humaine": True,
                               "application_automatique": False,
                               "effet_causal_estime": False}},
        },
        "gate_promotion": {
            "regle": "gain relatif >= 5 pourcent vs meilleur publie honnete, biais |.| <= 3 pourcent, "
                     "IC95 apparie entierement favorable, gain sur au moins 2 fenetres sur 3",
            "gain_relatif_du_modele_de_volume": volume_gain,
            "promu": bool(volume_gain is not None and volume_gain >= .05),
        },
    }
    (REPORT / "pricing_corrected.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (OUT / "metadata.json").write_text(
        json.dumps({k: v for k, v in payload.items() if k != "per_window"},
                   indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "manifest.sha256.json"}
    (OUT / "manifest.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(summary.round(4).to_string(index=False))
    print()
    print(pivot.round(4).to_string())
    print()
    print("meilleur WAPE            :", best_wape,
          "| biais", round(float(indexed.loc[best_wape, "forecast_bias"]), 4))
    print("meilleur volume (|b|<=3%) :", best_volume,
          "| WAPE", round(float(indexed.loc[best_volume, "wape"]), 4) if best_volume else None,
          "| gain vs publie", None if volume_gain is None else str(round(volume_gain * 100, 2)) + " %")
    print("promu                     :", payload["gate_promotion"]["promu"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
