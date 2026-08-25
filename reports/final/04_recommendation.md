<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres complément panier de ce rapport (`NDCG@10 = 0,0485`) sont
> **`invalidated_due_to_in_sample_evaluation_without_temporal_split`**.
>
> Motif : similarité item-item issue de la dernière fenêtre d'entraînement et évaluation sur la totalité des commandes, sans découpe train/test.
>
> Ce document est conservé **tel quel** comme témoin de ce qui a été publié ; seul ce
> bandeau a été ajouté. Il ne doit plus servir de référence ni de cible.
>
> 👉 Résultats en vigueur : [`reports/44_corrected_recommendation_results.md`](../44_corrected_recommendation_results.md) · [`SUPERSEDED_RESULTS.md`](../../SUPERSEDED_RESULTS.md)

# 04 — Recommandation finale

**Baseline officielle : `popularite_globale`. Hybride : `challenger_exploratoire`.**

| model                   | scenario            |    recall |      ndcg |      map10 |   coverage |   diversity |
|:------------------------|:--------------------|----------:|----------:|-----------:|-----------:|------------:|
| hybride_achats_web      | decouverte          | 0.0633947 | 0.0372424 | 0.0203406  |  0.186667  |    0.331401 |
| popularite_globale      | decouverte          | 0.0639174 | 0.0362866 | 0.0191677  |  0.0622222 |    0.240142 |
| popularite_recente      | decouverte          | 0.0648965 | 0.0361818 | 0.0188579  |  0.0544444 |    0.282723 |
| item_item_commandes     | decouverte          | 0.0624796 | 0.0361222 | 0.019256   |  0.284444  |    0.332588 |
| popularite_categorie    | decouverte          | 0.0461116 | 0.0275151 | 0.0150791  |  0.402222  |    0.1      |
| SVD_implicite           | decouverte          | 0.0443932 | 0.0256776 | 0.0132733  |  0.537778  |    0.519324 |
| regles_association_lift | decouverte          | 0.027821  | 0.0161885 | 0.00865182 |  0.718889  |    0.569659 |
| hybride_achats_web      | reapprovisionnement | 0.064488  | 0.0378804 | 0.0207565  |  0.183333  |    0.32277  |
| item_item_commandes     | reapprovisionnement | 0.0629341 | 0.0368374 | 0.0198598  |  0.286667  |    0.323178 |
| popularite_globale      | reapprovisionnement | 0.0632927 | 0.0364506 | 0.0193851  |  0.0333333 |    0.2      |
| popularite_recente      | reapprovisionnement | 0.0638579 | 0.0357523 | 0.0186643  |  0.0333333 |    0.266667 |
| SVD_implicite           | reapprovisionnement | 0.0479943 | 0.0289703 | 0.0156899  |  0.445556  |    0.489306 |
| popularite_categorie    | reapprovisionnement | 0.04732   | 0.0278971 | 0.0152582  |  0.266667  |    0.1      |
| regles_association_lift | reapprovisionnement | 0.0276558 | 0.0162255 | 0.0087174  |  0.714444  |    0.569181 |

## Comparaison hybride vs baseline par fenêtre

|   window |   global_recall |   hybrid_recall |   global_ndcg |   hybrid_ndcg |   n_client_windows |   recall_diff |   ndcg_diff |
|---------:|----------------:|----------------:|--------------:|--------------:|-------------------:|--------------:|------------:|
|        1 |       0.0673296 |       0.0658008 |     0.0370773 |     0.0384632 |               2430 |  -0.00152881  | 0.00138587  |
|        2 |       0.062755  |       0.0619017 |     0.0351641 |     0.0361994 |               2470 |  -0.000853255 | 0.00103523  |
|        3 |       0.0616676 |       0.0624815 |     0.0366185 |     0.0370647 |               2484 |   0.000813954 | 0.000446189 |

## Bootstrap apparié client-fenêtre

- ΔNDCG@10 : 0.000952, IC95% [-0.000842; 0.002764].
- ΔRecall@10 : -0.000515, IC95% [-0.003584; 0.002512].

## Systèmes spécialisés

- Complémentaires panier : système métier séparé, NDCG@10 0.0485.
- Sessions : modèle non utilisable, NDCG@10 2.35922e-05.

Les achats confirmés fournissent les cibles. Les `purchase` web ne sont jamais additionnés aux ventes; leur statut vient de la commande. Les bots sont exclus. Les anonymes restent des identités de session, sans client inventé.

LightFM/ALS/BPR natifs indisponibles dans l’environnement; SVD implicite légère évaluée. Aucun Transformer ou réseau profond, volume insuffisant pour le justifier.

Diagnostic session : {"usable_model": false, "temporal_alignment": "contexte strictement antérieur au premier purchase confirmé", "temporal_violations": 0, "candidate_catalog_size": 300, "targets_outside_candidates": 0, "exclude_seen_applied": false, "already_seen_target_rate": 1.0, "target_survival_if_seen_excluded": 0.0, "self_only_context_session_rate": 1.0, "confirmed_purchase_events": 80130, "confirmed_purchase_sessions": 47368, "sessions_with_pre_purchase_product_context": 47368, "ground_truth": "tous les produits des purchase reliés à une commande confirmée de la session; cutoff au premier purchase"}

Commande : `python -m src.pipelines.final_recommendation`.
