<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres `WAPE = 0,4164` et les métriques de complément panier de ce rapport sont **`invalidated_due_to_target_leakage / invalidated_due_to_target_category_leakage`**.
>
> Motif : fuite `n_lignes` côté pricing et fuite de la catégorie cible côté complément panier.
>
> Document conservé **tel quel** ; seul ce bandeau a été ajouté.
>
> 👉 Résultats en vigueur : [`45_final_corrected_decision.md`](../45_final_corrected_decision.md) · [`SUPERSEDED_RESULTS.md`](../../SUPERSEDED_RESULTS.md)

# 05 — Synthèse exécutive

## Décision

La reconstruction finale est exploitable comme socle analytique contrôlé, pas comme système de décision autonome. Les trois domaines ont été réévalués sur des découpages temporels communs, avec des données fraîches, des cibles confirmées et des garde-fous explicites.

| Domaine | Modèle retenu | Indicateur de sélection | Décision opérationnelle |
|---|---|---|---|
| Forecasting quotidien | `CrostonOptimized` | WAPE 1,0945; 4 victoires sur 6 fenêtres | Prévision quotidienne supervisée |
| Forecasting cumulé 30 j | `LightGBM_Tweedie` | WAPE cumulée 0,3106 contre 0,3700 pour Croston | Planification agrégée supervisée; aucun vainqueur global |
| Pricing | `LightGBM_calibre` | WAPE 0,4164; calibration strictement antérieure | Simulateur observationnel sous contrainte de coût et marge |
| Recommandation | baseline `popularite_globale` | IC95 % du ΔNDCG hybride `[-0,00084 ; 0,00276]` | Hybride classé `challenger_exploratoire` |

## Qualité des données

L'extraction fraîche réconcilie exactement les volumes de référence, les clés, les statuts, les relations ventes/web et l'équation de stock. Les 49 872 commandes web correspondent aux commandes de vente. Les bots ont été retirés; les anonymes ont été conservés sans client artificiel. Les empreintes SHA-256 des cinq datasets sont publiées dans le rapport d'audit.

## Limites qui conditionnent l'usage

- La demande quotidienne est très bruitée et intermittente : une WAPE supérieure à 1 interdit de présenter les prévisions journalières comme précises.
- Les intervalles 80/95 % sont calibrés sur des résidus strictement antérieurs; la couverture 80 % des produits A reste légèrement basse à 78,27 %.
- Le prix catalogue ne varie pas intra-produit. L'effet des remises est observationnel et ne démontre aucune causalité.
- La recommandation apporte un gain NDCG limité face à la popularité. Le scénario sessionnel atteint seulement `2,36e-05` de NDCG@10 et n'est pas utilisable en production.
- LightFM et ALS/BPR natifs n'étaient pas disponibles; une SVD implicite légère a été évaluée sans justifier l'ajout d'un modèle profond.

## Garde-fous de mise en service

1. Conserver Supabase en lecture seule pour toute reproduction.
2. Exécuter les entraînements séquentiellement afin de préserver la mémoire de la machine.
3. Surveiller et recalibrer périodiquement les intervalles, notamment sur les produits A.
4. Valider humainement chaque scénario de remise; ne jamais appliquer automatiquement un prix.
5. Conserver la popularité globale comme baseline; soumettre l'hybride à un test en ligne contrôlé avant tout changement de statut.

## Traçabilité

Les rapports détaillés `01` à `07`, les métadonnées et les manifestes SHA-256 sont la preuve de livraison. La branche de référence est `rebuild/final-enriched-dataset`; aucun merge vers `main`, déploiement ou write-back Supabase n'est autorisé dans ce périmètre.
