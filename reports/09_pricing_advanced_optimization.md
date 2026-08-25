<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres pricing de ce rapport (`WAPE = 0,4164`) sont
> **`invalidated_due_to_target_leakage`**.
>
> Motif : la référence citée utilisait `n_lignes`, dont la cible `quantite` est la somme.
>
> Ce document est conservé **tel quel** comme témoin de ce qui a été publié ; seul ce
> bandeau a été ajouté. Il ne doit plus servir de référence ni de cible.
>
> 👉 Résultats en vigueur : [`reports/43_corrected_pricing_results.md`](43_corrected_pricing_results.md) · [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md)

# 09 — Optimisation avancée du pricing

Branche : `experiment/pricing-advanced-optimization`.

## Référence et périmètre

Référence verrouillée : `LightGBM_calibre`, WAPE **0,4164**, biais environ **-0,0009** dans la livraison historique. Cette référence est un prédicteur observationnel ; elle n'est pas un estimateur causal validé et utilise `n_lignes`, proxy contemporain indisponible avant la fin de la journée.

La cible avancée est `quantite` confirmée au grain produit×jour×remise observée. La source canonique reste `fact_ventes` filtrée `statut_commande = confirmee`. Les lignes annulées/retournées et les événements web `purchase` ne sont jamais additionnés aux ventes ; leurs taux historiques décalés sont uniquement des variables de risque éventuelles.

Audit descriptif : remises observées 0/5/10/15/20/25/30/40 %, respectivement 47 702 / 1 810 / 1 879 / 1 695 / 963 / 861 / 667 / 9 agrégats ; 300 produits. Les campagnes produit et catégorie sont contrôlées séparément. La remise 40 % est insuffisamment représentée et exclue des recommandations.

Populations : `estimation_individuelle_supportee` (support produit×remise suffisant), `pooling_categorie` (support individuel insuffisant mais catégorie supportée) et `insufficient_evidence` (aucun support commun ou historique minimal). La population primaire d'évaluation n'est jamais filtrée par support.

## Gate pilote et modèles

Le gate économique est WAPE < **0,3956**, soit au moins 5 % d'amélioration par rapport à 0,4164. Sur les deux premières fenêtres disponibles, aucun challenger ne passe : CatBoost enrichi 0,5689 / 0,5551 ; GLM Tweedie 0,5722 / 0,5555 ; GLM Poisson 0,5744 / 0,5557 ; LightGBM enrichi 0,5849 / 0,5568 ; LightGBM IPW 0,5857 / 0,5574 ; effets fixes Poisson 0,5885 / 0,5569. Les baselines aucune remise sont 0,5684 / 0,5666.

Le meilleur challenger avancé sur trois fenêtres est CatBoost enrichi, WAPE moyenne 0,5569 et biais +0,0206. Aucun candidat ne franchit le gate, ne gagne de façon stable ni ne justifie Optuna ou une nouvelle exécution longue. La référence LightGBM_calibre reste inchangée comme repère historique, sans promotion automatique de son proxy contemporain.

| Modèle/politique | F1 | F2 | WAPE moyenne (3 fenêtres) | Biais moyen | Statut |
|---|---:|---:|---:|---:|---|
| CatBoost enrichi | 0,5689 | 0,5551 | 0,5569 | +0,0206 | challenger, non promu |
| GLM Tweedie | 0,5722 | 0,5555 | 0,5590 | +0,0296 | challenger |
| GLM Poisson | 0,5744 | 0,5557 | 0,5598 | +0,0323 | challenger |
| LightGBM enrichi | 0,5849 | 0,5568 | 0,5629 | +0,0360 | challenger |
| LightGBM IPW | 0,5857 | 0,5574 | 0,5644 | +0,0429 | sensibilité |
| Effets fixes Poisson | 0,5885 | 0,5569 | 0,5650 | +0,0478 | challenger |
| Aucune remise | 0,5684 | 0,5666 | 0,5626 | +0,0324 | baseline simple |

Les ablations LightGBM à configuration fixe donnent : complet 0,5629 ; sans promotions 0,5598 ; sans stock 0,5625 ; sans commandes/segments 0,5635 ; sans web 0,5639. Elles ne constituent pas une preuve d'uplift et aucune n'atteint le gate.

Les features autorisées sont toutes antérieures au cutoff : lags/rollings de ventes, commandes confirmées, clients, paniers, web décalé, promotions observées, prix/coût/marge théoriques, stock au cutoff, réapprovisionnements historiques, calendrier, segment client agrégé et taux de risque annulé/retour décalés. Aucun purchase web contemporain, statut futur, stock futur ou prix payé réalisé n'est utilisé.

## Uplift observationnel

Les analyses propensity multivaluées/IPTW et AIPW/DR sont publiées comme **association ajustée**, **uplift observationnel** et **scénario contrefactuel estimé** uniquement. Les taux traités et IC95 % sont calculés avec nuisance et propension apprises dans le passé ; le support commun est contrôlé (taux ≥0,02 : 91,88 %, 87,73 %, 95,59 %). Aucune causalité n'est revendiquée.

## Simulateur de marge

Le simulateur compare aucune remise, politique historique et remises effectivement supportées, avec prix ≥ coût, marge ≥5 %, support produit minimal et validation humaine. Sur 300 produits : 0 NaN, 0 quantité négative, 0 prix sous coût, 0 violation de marge ; la sortie actuelle recommande 0 % partout.

```text
automatic_application_allowed = false
human_validation_required = true
causal_effect_estimated = false
off_policy_evaluation_validated = false
simulation_status = observational_supported_scenarios
support_status = product_observed_support_only
```

La politique n'est pas un moteur causal de prix optimal et aucune application automatique n'est autorisée.

Coût observé de l'expérience séquentielle : jusqu'à 28,2 s par étape, environ 419 Mo RSS, checkpoints par modèle/fenêtre ; aucun entraînement supplémentaire n'est lancé après l'échec du pilote. Les tailles d'artefacts et les empreintes SHA-256 sont dans `models/advanced/pricing/manifest.sha256.json`.

## Décision

Les données ne permettent ni une causalité fiable ni un prix continu optimal. Le pricing avancé reste un prédicteur observationnel et un simulateur descriptif sous garde-fous. Aucune branche forecasting n'est modifiée.
