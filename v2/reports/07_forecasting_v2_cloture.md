# 07 — Clôture Forecasting V2

_Généré le 2026-08-15T12:28:27.575740+00:00. Branche `feature/v2-model-improvements`, non fusionnée dans `main`._

## 1. Statut officiel

```
central_forecast_model: v1_autoets_naive
central_forecast_v2_validated: false
interval_calibration_v2_validated: true
interval_calibration_method: C3_abc_x_intermitence
system_name: forecasting_v1_with_v2_interval_calibration
```

**La V2 améliore la QUANTIFICATION DE L'INCERTITUDE, pas la précision centrale. C3 est une méthode de calibration d'intervalles — jamais un modèle de prévision.**

## 2. Ce qui change et ce qui ne change pas

| Volet | État |
|---|---|
| Prévision centrale | **Inchangée** — v1_autoets_naive |
| Intervalles | **Recalibrés** par classe ABC × profil de demande |

Métriques centrales, identiques à la V1 par construction :

| Métrique | Valeur |
|---|---:|
| WAPE cumulée 30 j | 0.277179 |
| WAPE cumulée 14 j | 0.350794 |
| WAPE cumulée 7 j | 0.461864 |
| WAPE quotidienne | 1.094727 |

Amélioration apportée par C3 (niveau 80 %) :

| Indicateur | V1 | V2 (C3) | Cible |
|---|---:|---:|---|
| Couverture produits A | 0.7439 | **0.7903** | [0,78 ; 0,84] |
| Couverture globale | — | 0.8110 | [0,78 ; 0,84] |
| Largeur moyenne | 3.6042 | 3.5951 | — |

La correction est obtenue **sans élargir les intervalles** : seule leur répartition entre segments change.

## 3. Archivage des expériences

| Expérience | Statut | Raison |
|---|---|---|
| A | `non_retenu` | gain non généralisable |
| B | `non_retenu` | segmentation instable |
| C | `retenu` | calibration des intervalles améliorée |
| D | `non_lance` | absence de nouveau signal |
| E | `non_retenu` | non retenu à 30 jours malgré un signal court terme intéressant |

## 4. Registre futur

```
direct_multi_horizon_forecasting
priority: high
status: future_experiment
evidence: gains de 6,30 % à 8,61 % à 7 jours avec variables métier
condition: ne pas utiliser de stratégie récursive
```

_Ne pas appeler V3 à ce stade ; aucun entraînement engagé._

## 5. Contrôles de clôture

| Contrôle | Résultat |
|---|:---:|
| Prévisions centrales identiques bit à bit à la V1 | ✅ |
| Intervalles C3 recalculables et reproductibles | ✅ |
| Couverture globale et produits A dans les seuils | ✅ |
| Bornes ordonnées et non négatives | ✅ |
| Aucune fuite (calibration strictement antérieure) | ✅ |
| V1 intacte (22 artefacts verrouillés) | ✅ |
| Statut des expériences A à E conforme | ✅ |
| Aucun secret ni donnée brute | ✅ |
| Suite de tests | ✅ |

**TOUS LES CONTROLES PASSENT** — 180 passed in 26.61s

_Note sur la fenêtre 1_ : en régime strict, elle n'a aucune fenêtre antérieure pour se calibrer et reste donc non calibrable (0.1486 des points). Elle conserve l'intervalle V1 plutôt qu'une calibration inventée — c'est un choix assumé, pas une lacune.

## 6. Ce qui n'a pas été fait

- **Aucun modèle de prévision centrale V2** : les candidats A, B et E ont tous échoué aux seuils fixés à l'avance.
- **Candidat D non lancé** (déjà rejeté en V1, aucun signal nouveau).
- **Prévision directe par horizon non entraînée** — inscrite au registre futur uniquement.
- Aucune fusion dans `main`, aucun déploiement, aucune écriture Supabase.
