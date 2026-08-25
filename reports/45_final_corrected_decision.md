# 45 — Décision finale corrigée

> Série « correction » du 2026-08-18. Document de décision faisant autorité
> sur les trois domaines.
> Série « correction » du 2026-08-18, numérotée 42 à 45 pour ne coexister
> avec aucun rapport historique. Elle supersède les rapports antérieurs sans
> les supprimer : chacun conserve son contenu d'origine et porte un bandeau
> d'invalidation. Voir [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md).

Branche : branche d'audit independant dediee.
Aucun push, aucune fusion, aucun déploiement, aucune écriture Supabase.

---

## 1. Décision par domaine

| Domaine | Modèle officiel | Métrique | Statut |
|---|---|---|---|
| Forecasting 30 j | `LightGBM_direct_per_horizon` | WAPE30 macro **0,25831**, micro **0,25743**, biais **−0,02589** | **valide, inchangé** |
| Forecasting quotidien | `CrostonOptimized` | WAPE ≈ 1,0765 | valide, inchangé |
| Pricing — prédicteur WAPE | `lgbm_l1_mediane` | WAPE 0,5218, biais −0,1814 | **non promu**, non utilisable comme simulateur |
| Pricing — volume à biais acceptable | `lgbm_tweedie_moyenne` | WAPE 0,5526, biais +0,0013 | **non promu** (gain 0,77 % < 5 %) |
| Pricing — simulateur de marge | alimenté par le modèle de volume | — | garde-fous inchangés |
| Reco. prochain achat | `popularite_globale` | Recall@10 ≈ 0,0634, NDCG@10 ≈ 0,0363 | valide, inchangé |
| Reco. complément panier | `none_validated` | baseline `popularite_globale` : Recall@10 0,0556, NDCG@10 0,0240 | **aucun modèle validé** |
| Reco. sessionnel | `non_utilisable` | — | inchangé |

**Aucun modèle n'est promu sur aucun des trois domaines.**

## 1 bis. Statuts officiels

Source de vérité : [`models/FINAL_STATUS.json`](../models/FINAL_STATUS.json),
généré par `python -m src.pipelines.final_status` et vérifié contre les
artefacts publiés par `tests/test_final_status.py`.

```text
forecasting_status                = validated
forecasting_daily_model           = CrostonOptimized
forecasting_30d_model             = LightGBM_direct_per_horizon
forecasting_wape30_macro          = 0.25831
forecasting_bias                  = -0.02589

pricing_previous_result_status    = invalidated_due_to_target_leakage
pricing_accuracy_model            = lgbm_l1_mediane
pricing_accuracy_wape             = 0.5218
pricing_accuracy_bias             = -0.1814
pricing_operational_volume_model  = lgbm_tweedie_moyenne
pricing_operational_wape          = 0.5526
pricing_operational_bias          = 0.0013
pricing_status                    = exploratory_non_causal
automatic_pricing_allowed         = false

general_recommendation_model      = popularite_globale
basket_complement_model           = none_validated
basket_complement_baseline        = popularite_globale
basket_previous_results_status    = invalidated_due_to_target_leakage_and_in_sample_evaluation
session_model_status              = non_utilisable
rrf_status                        = exploratory_diversity_challenger
```

`forecasting_wape30_macro` et `forecasting_bias` sont tous deux **macro**,
c'est-à-dire moyennés sur les six fenêtres. Les équivalents poolés valent
respectivement 0,25743 et −0,02593 ; les deux définitions ne doivent jamais être
présentées l'une pour l'autre.

### Contrainte bloquante sur le simulateur de marge

> **`lgbm_l1_mediane` ne doit jamais alimenter le simulateur de marge.**
>
> Son Forecast Bias est de **−18,14 %** : il estime la **médiane**
> conditionnelle, ce qui est optimal pour la WAPE mais systématiquement
> inférieur à l'espérance. L'utiliser sous-estimerait toute projection de marge
> d'environ 18 %, toujours dans le même sens, sans compensation possible.
>
> Seul **`lgbm_tweedie_moyenne`** (biais **+0,13 %**) peut alimenter le
> simulateur. Cette règle est encodée dans `MARGIN_SIMULATOR_RULE` et vérifiée
> par `test_margin_simulator_refuses_the_biased_accuracy_model`.


## 2. Le forecasting est le seul domaine dont la référence a survécu à l'audit

Reproduit à l'identique depuis les prédictions stockées (54 000 lignes =
300 produits × 30 horizons × 6 fenêtres, aucune population réduite) :

| Métrique | Annoncée | Recalculée |
|---|---:|---:|
| WAPE30 macro | 0,25831 | 0,2583140754 |
| WAPE30 micro | 0,25743 | 0,2574324397 |
| Forecast Bias | −0,02593 | −0,0258949 |
| WAPE quotidienne macro | 1,0870 | 1,0869756 |

Marge résiduelle quantifiée par bornes oracle : un oracle connaissant le niveau
moyen réel de chaque produit sur la période de test atteint **0,24361**, soit
5,4 % relatif sous le modèle ; le plancher de bruit binomial négatif est
d'environ **0,22**. Le candidat testé (cible cumulative 30 j sous perte L1,
alignée sur la métrique) atteint 0,28654 sur F1–F2 contre un gate à 0,26443 :
**gate échoué**, exécution six fenêtres non lancée.

## 3. Ce qui a réellement changé

Aucun score n'a été amélioré. Ce qui a changé, c'est la **validité de la base de
comparaison** :

| Élément | Avant | Après |
|---|---:|---:|
| Référence pricing | 0,4164 | **invalidée** ; honnête = 0,5526 |
| Référence complément panier | 0,437 / 0,213 | **invalidée** ; honnête = 0,0556 / 0,0240 |
| Référence complément héritée | 0,1006 / 0,0485 | **invalidée** (in-sample) |
| Gate candidat complément | franchi (0,87–0,93) | **non franchi** (0,22–0,30) |
| Gain apparent cooccurrence | +18,2 %, IC95 positif | **+3,1 %**, IC95 traversant zéro |
| Forecasting | 0,25831 | **0,25831**, confirmé |

## 4. Objectifs initiaux, réévalués

| Objectif fixé | Verdict |
|---|---|
| Forecasting : WAPE30 < 0,25831 avec gain sur 4/6 fenêtres | non atteint ; marge réelle ≤ 5 % |
| Forecasting : WAPE 0,15 | **hors d'atteinte**, plancher de bruit ≈ 0,22 |
| Pricing : améliorer 0,4164 de 5 % | **objectif invalide** : 0,4164 est sous le plancher oracle honnête (0,487) |
| Pricing : marge simulée sous garde-fous | livré, alimenté par le modèle de volume non biaisé |
| Reco. : NDCG@10 +5 % avec IC95 favorable | non atteint ; meilleur challenger +7,1 % mais IC95 traverse zéro |
| Reco. : couverture catalogue | 0,042 → 0,630 disponible via RRF, mais sans gain de pertinence validé |

## 5. Ce qui reste impossible avec les données actuelles

- **Causalité pricing** : prix catalogue fixe sur les 300 produits, campagnes non
  randomisées, seules les remises varient. Aucun prix optimal continu estimable.
- **WAPE pricing < 0,487** sans information contemporaine de la cible : borne
  oracle.
- **WAPE forecasting 30 j < 0,22** : plancher de bruit binomial négatif.
- **Complémentarité panier** : les paniers sont des tirages statistiquement
  indépendants (0,2182 observé contre 0,222 attendu sous indépendance).
- **Modèle sessionnel** : cible déjà vue dans 100 % des cas.
- **Demande réelle** : aucune donnée de rupture ni de demande perdue ;
  `quantite_vendue` du stock inclut tous les statuts sans réintégration des
  annulations et retours.

Données qui débloqueraient ces axes : historique plus long, date de lancement
commercial réelle, demande perdue et disponibilité intra-journalière, variation
effective des prix catalogue, expérimentation randomisée des remises, et une
structure de panier réellement corrélée.

## 6. Reproductibilité

```bash
python -m src.pipelines.final_pricing
python -m src.experiments.pricing_corrected
python -m src.experiments.complement_leak_audit
python -m src.experiments.complement_honest_baseline
python -m src.experiments.complement_end_to_end
python -m src.experiments.complement_candidate_pilot
python -m src.experiments.cumulative_l1_forecasting
python -m src.pipelines.refresh_manifests
python -m pytest tests -q
```

Graine unique 42. Suite complète : **222 passés, 30 ignorés, 0 échec**.
Les 30 skips sont historiques et documentés en §7.

## 7. Skips historiques

| Fichier | Skips | Motif |
|---|---:|---|
| `tests/test_dataset_integrity.py` | 24 | requiert les sorties V1 de `src.pipelines.extract` + `prepare`, supplantées par la reconstruction `data/processed/final/` |
| `tests/test_lightgbm_recursive_no_leakage.py` | 6 | requiert `data/processed/table_analytique.parquet`, artefact intermédiaire V1 non régénéré |

Ces 30 tests portent sur une chaîne de données antérieure, conservée pour
traçabilité mais plus alimentée. Aucun ne concerne les domaines corrigés.

## 8. Actions nécessitant une autorisation explicite

1. Tout `git push` ou fusion vers `main`.
2. Toute publication externe des résultats corrigés.
3. Toute écriture Supabase (la base reste strictement en lecture seule).
4. Régénération éventuelle de la chaîne V1 pour lever les 30 skips historiques.
