<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres `WAPE = 0,4164` (référence pricing citée) de ce rapport sont **`invalidated_due_to_target_leakage`**.
>
> Motif : la référence citée utilisait `n_lignes`, dont la cible `quantite` est la somme.
>
> Document conservé **tel quel** ; seul ce bandeau a été ajouté.
>
> 👉 Résultats en vigueur : [`43_corrected_pricing_results.md`](43_corrected_pricing_results.md) · [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md)

# 10 — Pricing au niveau campagne

Statut : diagnostic métrique et pilote borné, sans push ni écriture Supabase.

- Campagnes réelles indépendantes : **120** ; épisodes produit×campagne : **2406** ; épisodes sans chevauchement : **2003** ; épisodes en chevauchement : **403**.
- Produit×semaine : **23700** lignes ; produit×jour historique secondaire : WAPE **0,4164**.
- Features strictement pré-campagne ; campagnes entières dans un seul split ; overlaps exclus du benchmark principal et évalués séparément.

## Vérification indépendante de la WAPE

- Formule : somme des erreurs absolues / somme des réels ; somme réelle **19441**, somme prévue (taux×durée) **30081**, erreur absolue **24776**, biais **0.5473**.
- Cibles nulles : **602** (30.05%) ; prédictions négatives **0**, NaN **0**, extrêmes **0**.
- Baseline zéro : WAPE exactement 1,00 puisque le volume réel est positif ; aucun dénominateur nul n'a été remplacé silencieusement.
- Les quantiles y sont {'0': 0.0, '0.25': 0.0, '0.5': 7.0, '0.75': 15.0, '0.95': 29.0, '1': 71.0} et les quantiles prédits taux×durée {'0': 0.0, '0.25': 0.0, '0.5': 14.357142857142858, '0.75': 26.0, '0.95': 36.535714285714285, '1': 61.75}.

## Diagnostic de la WAPE > 1

La prévision taux pré-campagne×durée reste pire que zéro (WAPE 1,2744 micro) principalement par sur-prévision des séries nulles/intermittentes et par un taux historique élevé appliqué à toute la durée ; les dates inclusives et le mapping produit×campagne sont validés sur dix recalculs directs. Ce n'est pas un double comptage du benchmark principal : les 403 épisodes overlap sont exclus.

## Métriques par modèle

| grain            |   window | model                           |    n |   wape_micro |   forecast_bias |     mae |   wape_positive |   actual_total |   pred_total |   abs_error_total |   n_zero_targets |   zero_target_rate |   known_n |   cold_start_n |    brier |   log_loss |
|:-----------------|---------:|:--------------------------------|-----:|-------------:|----------------:|--------:|----------------:|---------------:|-------------:|------------------:|-----------------:|-------------------:|----------:|---------------:|---------:|-----------:|
| produit×campagne |        1 | baseline_zero                   |  801 |       1.0000 |         -1.0000 |  7.1186 |          1.0000 |      5702.0000 |       0.0000 |         5702.0000 |              371 |             0.4632 |         0 |            801 | nan      |   nan      |
| produit×campagne |        1 | mean_global_train               |  801 |       1.0000 |         -1.0000 |  7.1186 |          1.0000 |      5702.0000 |       0.0000 |         5702.0000 |              371 |             0.4632 |         0 |            801 | nan      |   nan      |
| produit×campagne |        1 | mean_produit_train              |  801 |       1.0000 |         -1.0000 |  7.1186 |          1.0000 |      5702.0000 |       0.0000 |         5702.0000 |              371 |             0.4632 |         0 |            801 | nan      |   nan      |
| produit×campagne |        1 | mean_categorie_remise_train     |  801 |       1.0000 |         -1.0000 |  7.1186 |          1.0000 |      5702.0000 |       0.0000 |         5702.0000 |              371 |             0.4632 |         0 |            801 | nan      |   nan      |
| produit×campagne |        1 | taux_pre_campaign_x_duree       |  801 |       1.7267 |          0.9357 | 12.2920 |          0.8865 |      5702.0000 |   11037.6071 |         9845.8929 |              371 |             0.4632 |         0 |            801 | nan      |   nan      |
| produit×campagne |        1 | derniere_periode_sans_promotion |  801 |       1.6509 |          0.8391 | 11.7522 |          0.8614 |      5702.0000 |   10486.3571 |         9413.5000 |              371 |             0.4632 |         0 |            801 | nan      |   nan      |
| produit×campagne |        2 | baseline_zero                   |  569 |       1.0000 |         -1.0000 |  9.8629 |          1.0000 |      5612.0000 |       0.0000 |         5612.0000 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | mean_global_train               |  569 |       0.8545 |         -0.2782 |  8.4279 |          0.6224 |      5612.0000 |    4050.4844 |         4795.4906 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | mean_produit_train              |  569 |       0.6433 |         -0.3687 |  6.3452 |          0.6290 |      5612.0000 |    3542.9167 |         3610.4167 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | mean_categorie_remise_train     |  569 |       0.8559 |         -0.3694 |  8.4414 |          0.6621 |      5612.0000 |    3538.8352 |         4803.1368 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | taux_pre_campaign_x_duree       |  569 |       1.2341 |          0.5602 | 12.1715 |          0.7515 |      5612.0000 |    8755.6429 |         6925.5714 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | derniere_periode_sans_promotion |  569 |       1.2080 |          0.5251 | 11.9147 |          0.7372 |      5612.0000 |    8558.6071 |         6779.4643 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | glm_poisson_regularise          |  569 |       0.8193 |         -0.2875 |  8.0811 |          0.5954 |      5612.0000 |    3998.6492 |         4598.1707 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | glm_tweedie_regularise          |  569 |       0.8260 |         -0.2898 |  8.1470 |          0.6016 |      5612.0000 |    3985.6463 |         4635.6163 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        2 | hurdle_poisson                  |  569 |       0.8227 |         -0.3390 |  8.1139 |          0.6157 |      5612.0000 |    3709.3046 |         4616.8077 |              183 |             0.3216 |       569 |              0 |   0.2464 |     0.6858 |
| produit×campagne |        2 | lightgbm_poisson_regularise     |  569 |       0.8109 |         -0.2891 |  7.9974 |          0.5879 |      5612.0000 |    3989.5079 |         4550.4969 |              183 |             0.3216 |       569 |              0 | nan      |   nan      |
| produit×campagne |        3 | baseline_zero                   |  633 |       1.0000 |         -1.0000 | 12.8389 |          1.0000 |      8127.0000 |       0.0000 |         8127.0000 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | mean_global_train               |  633 |       0.6151 |         -0.3568 |  7.8974 |          0.5663 |      8127.0000 |    5227.5635 |         4999.0832 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | mean_produit_train              |  633 |       0.6343 |         -0.3756 |  8.1431 |          0.6233 |      8127.0000 |    5074.1476 |         5154.5714 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | mean_categorie_remise_train     |  633 |       0.5712 |         -0.3776 |  7.3332 |          0.5320 |      8127.0000 |    5058.2501 |         4641.8855 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | taux_pre_campaign_x_duree       |  633 |       0.9849 |          0.2659 | 12.6448 |          0.9032 |      8127.0000 |   10287.8929 |         8004.1786 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | derniere_periode_sans_promotion |  633 |       0.9669 |          0.2366 | 12.4141 |          0.8910 |      8127.0000 |   10049.7143 |         7858.1429 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | glm_poisson_regularise          |  633 |       0.5486 |         -0.3068 |  7.0440 |          0.5012 |      8127.0000 |    5633.4069 |         4458.8775 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | glm_tweedie_regularise          |  633 |       0.5635 |         -0.3277 |  7.2350 |          0.5166 |      8127.0000 |    5463.7367 |         4579.7661 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×campagne |        3 | hurdle_poisson                  |  633 |       0.5846 |         -0.4128 |  7.5051 |          0.5450 |      8127.0000 |    4771.8233 |         4750.7090 |               48 |             0.0758 |       633 |              0 |   0.2508 |     0.6947 |
| produit×campagne |        3 | lightgbm_poisson_regularise     |  633 |       0.5349 |         -0.3315 |  6.8679 |          0.4909 |      8127.0000 |    5432.8923 |         4347.3680 |               48 |             0.0758 |       633 |              0 | nan      |   nan      |
| produit×semaine  |        1 | moving_average_4_weeks          | 8100 |       0.5253 |         -0.0871 |  2.1073 |          0.5065 |     32494.0000 |   29665.0833 |        17068.7500 |             4098 |             0.5059 |      8100 |              0 | nan      |   nan      |
| produit×semaine  |        2 | moving_average_4_weeks          | 7800 |       0.4625 |         -0.0315 |  3.2625 |          0.4527 |     55019.0000 |   53283.7500 |        25447.2500 |             2337 |             0.2996 |      7800 |              0 | nan      |   nan      |
| produit×semaine  |        3 | moving_average_4_weeks          | 7800 |       0.4997 |         -0.0005 |  3.8132 |          0.4758 |     59521.0000 |   59491.2500 |        29743.2500 |              734 |             0.0941 |      7800 |              0 | nan      |   nan      |

| model                           |   wape_macro |   wape_micro |     actual |   bias_mean |
|:--------------------------------|-------------:|-------------:|-----------:|------------:|
| baseline_zero                   |       1.0000 |       1.0000 | 19441.0000 |     -1.0000 |
| derniere_periode_sans_promotion |       1.2753 |       1.2371 | 19441.0000 |      0.5336 |
| glm_poisson_regularise          |       0.6840 |       0.6592 | 13739.0000 |     -0.2972 |
| glm_tweedie_regularise          |       0.6948 |       0.6707 | 13739.0000 |     -0.3088 |
| hurdle_poisson                  |       0.7036 |       0.6818 | 13739.0000 |     -0.3759 |
| lightgbm_poisson_regularise     |       0.6729 |       0.6476 | 13739.0000 |     -0.3103 |
| mean_categorie_remise_train     |       0.8090 |       0.7791 | 19441.0000 |     -0.5823 |
| mean_global_train               |       0.8232 |       0.7971 | 19441.0000 |     -0.5450 |
| mean_produit_train              |       0.7592 |       0.7441 | 19441.0000 |     -0.5814 |
| taux_pre_campaign_x_duree       |       1.3152 |       1.2744 | 19441.0000 |      0.5873 |

WAPE campagne macro (baseline zéro) : **1.0000** ; WAPE micro poolée : **1.0000**. Les deux conventions sont distinctes.

Le meilleur pilote régularisé (LightGBM Poisson, WAPE micro 0,6476, biais -0,3103) bat zéro et les baselines historiques, mais échoue au gate biais absolu <0,10 et au second gate <0,50. Le grain campagne n'est donc pas promu comme modèle prédictif.

## Dataset et exemples

Durée inclusive : 4–15 jours ; épisodes uniques produit×campagne : 2003 ; doublons : 0 ; campagnes par fenêtre : {'1': 801, '2': 569, '3': 633}. Dix recomputations directes depuis `fact_ventes`, `dim_promotion` et `dim_date` sont dans `campaign_examples_direct_recalculation.csv`; toutes doivent avoir `match=true`.

## Support et garde-fous

- Les produits sans support individuel sont affectés au pooling catégorie ; sinon `insufficient_evidence`.
- Aucun effet causal, aucune élasticité continue, aucune extrapolation et aucune application automatique ne sont autorisés.

## Décision

Le modèle officiel reste donc `LightGBM_calibre` au grain produit×jour (WAPE 0,4164). Le dataset campagne est conservé pour l'analyse descriptive des politiques et l'évaluation observationnelle ; l'agrégation campagne n'a pas réduit l'incertitude.

## Protocole futur, après données supplémentaires

Aucune nouvelle expérimentation sur les données actuelles n'est lancée. Une future étude devra être randomisée par catégorie et classe ABC, avec traitements 0/5/10/15 % et un groupe contrôle sans remise. L'éligibilité et la probabilité d'affectation seront journalisées ; la décision de traitement devra être figée avant le début de la campagne.

Avant lancement, un calcul de puissance devra confirmer le volume requis. L'analyse principale sera en intention de traiter et mesurera quantité, chiffre d'affaires, marge, annulations et retours. Un arrêt automatique s'appliquera en cas de marge insuffisante. Le réentraînement ne sera autorisé qu'après obtention d'un volume d'expositions suffisant et d'un suivi complet des résultats.

## Artifacts

Datasets : `pricing_product_campaign.parquet`, `pricing_product_week.parquet`, `pricing_product_day_reference.parquet`. Diagnostics, métriques et SHA-256 : `models/campaign_level_pricing/`.
