# 05 — Reproductibilité

Statut : `synthetic_academic_experiment`. Toutes les commandes ci-dessous
s'exécutent en local, sans écriture Supabase, sans push ni déploiement.

## 1. Graine

Une graine unique, `SEED = 42`, est utilisée dans tous les modules
(`src/pricing_v4/models.py`, `src/pricing_v4/evaluate.py`,
`src/recsys_v4/models.py`, `src/recsys_v4/evaluate.py`) : construction des
modèles, tirages bootstrap, tests de permutation.

## 2. Version du code

Commit de départ de la branche de travail : `c5cb7d9e26c193502d3549c7e75dcc6b316ee6a9`
(branche `v4/pricing-recommendation-training`). Chaque fichier de métadonnées
produit (`models/v4/{pricing,recommendation}/{cible}/metadata.json`) enregistre
le commit exact utilisé pour l'entraînement (`code_version_git_commit`).

## 3. Environnement logiciel

| Composant | Version |
|---|---|
| Python | 3.13.7 |
| pandas | 2.3.3 |
| numpy | 2.2.6 |
| scikit-learn | 1.7.2 |
| lightgbm | 4.6.0 |
| catboost | 1.2.10 |
| xgboost | 3.2.0 |
| joblib | 1.5.2 |

## 4. Données utilisées

Extraction locale versionnée, jamais la base vivante directement pour
l'entraînement. Manifeste complet avec empreintes SHA-256 :
`models/v4/manifests/raw_data_manifest.json`. Chaque fichier de métadonnées
modèle référence ces empreintes (`raw_data_sha256`), de sorte qu'un
changement silencieux des données sources serait détectable.

| Fichier | Contenu |
|---|---|
| `data/raw/v4/fact_experimentation_prix.parquet` | 11 799 décisions pricing, extraction fraîche |
| `data/raw/v4/fact_exposition_reco.parquet` | 221 080 expositions, extraction fraîche |
| `data/raw/v4/fact_ventes.csv` | export dédié, entrée documentée du contrôle de cohérence pricing |
| `data/raw/{dim_client,dim_date,dim_produit,dim_promotion,fact_evenements_web,fact_stock,fact_ventes}.parquet` | tables historiques réutilisées depuis le cache V2, volumétrie revérifiée |
| `data/raw/v4/pricing_dataset.parquet` | jeu de données pricing final, sans fuite |
| `data/raw/v4/recommendation_dataset.parquet` | jeu de données recommandation final, sans fuite |

## 5. Commandes exactes, dans l'ordre

```bash
python -m scripts.extract_v4_data
python -m scripts.audit_v4
python -m src.pricing_v4.dataset
python -m src.recsys_v4.dataset
python -m src.pricing_v4.train
python -m src.recsys_v4.train
python -m pytest tests/test_v4_pricing.py tests/test_v4_recommendation.py -q
```

## 6. Temps d'entraînement et mémoire

Mesurés par fenêtre et par modèle (`tracemalloc` pour le pic mémoire Python,
chronométrage direct pour le temps d'ajustement). Détail complet dans
`models/v4/{pricing,recommendation}/{cible}/metadata.json` → `timing`, et par
ligne dans `per_window_metrics.csv` (colonnes `train_seconds`,
`peak_memory_mb`).

## 7. Artefacts produits

```
models/v4/
├── manifests/
│   └── raw_data_manifest.json
├── pricing/
│   ├── units_sold_window_7j/{model.joblib, metadata.json, oos_predictions.csv,
│   │                          per_window_metrics.csv, segment_metrics.csv,
│   │                          MODEL_CARD.md, manifest.sha256.json}
│   ├── revenue_window_xof_7j/{...}
│   └── margin_window_xof_7j/{...}
└── recommendation/
    ├── viewed_after_impression/{model.joblib, metadata.json, oos_predictions.csv,
    │                            per_window_metrics.csv, as_served_metrics.csv,
    │                            MODEL_CARD.md, manifest.sha256.json}
    ├── added_to_cart_after/{...}
    └── purchased_after/{...}
```

## 8. Vérification d'intégrité

Chaque sous-répertoire de modèle porte son propre `manifest.sha256.json`,
couvrant tous les fichiers qu'il contient. Un test automatisé
(`test_manifest_sha256_matches_artifacts`, dans les deux suites
`tests/test_v4_pricing.py` et `tests/test_v4_recommendation.py`) recalcule ces
empreintes et échoue si un fichier a été modifié après coup.

## 9. Rejouabilité du choix de modèle

`test_metrics_are_reproducible_across_reruns` et
`test_same_seed_gives_identical_predictions`/`_scores` réentraînent un modèle
deux fois avec les mêmes données et la même graine, et vérifient une égalité
stricte des métriques et des prédictions.
