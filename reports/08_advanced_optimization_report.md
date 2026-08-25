<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres pricing et complément panier de ce rapport (`WAPE = 0,4164` et les métriques de complément panier) sont
> **`invalidated_due_to_target_leakage / invalidated_due_to_target_category_leakage`**.
>
> Motif : fuite `n_lignes` côté pricing et fuite de la catégorie cible côté complément panier.
>
> Ce document est conservé **tel quel** comme témoin de ce qui a été publié ; seul ce
> bandeau a été ajouté. Il ne doit plus servir de référence ni de cible.
>
> 👉 Résultats en vigueur : [`reports/45_final_corrected_decision.md`](45_final_corrected_decision.md) · [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md)

# Rapport d'optimisation avancée

Branche isolée : `experiment/advanced-model-optimization`. La livraison validée sur `rebuild/final-enriched-dataset` reste inchangée.

## État des domaines

| Domaine | État | Décision provisoire |
|---|---|---|
| Forecasting | terminé | CrostonOptimized quotidien inchangé ; LightGBM direct candidat expérimental cumul 30 j |
| Pricing | terminé | aucun challenger promu ; simulateur observationnel uniquement |
| Recommandation | terminé | popularité globale = baseline officielle ; rankers = challengers exploratoires |

## Forecasting

Six backtests de 30 jours ont été exécutés avec validation temporelle stricte. Le LightGBM direct par horizon atteint WAPE jour 1,0870, WAPE7 0,4546, WAPE30 0,2583 et biais -0,0259. Il améliore le cumul 30 jours du LightGBM_Tweedie validé de 16,83 %, avec un IC95 % apparié de la différence WAPE [-0,06048 ; -0,04488]. Son gain quotidien de 0,69 % reste sous le seuil de 5 % : CrostonOptimized demeure la décision quotidienne.

Les intervalles conformes, calibrés seulement sur les fenêtres antérieures, couvrent 78,76 % au niveau 80 % et 95,32 % au niveau 95 % globalement ; les résultats ABC-A et intermittents sont comparables. Les challengers CatBoost, XGBoost, hurdle, quantile et ensemble expanding ne dépassent pas le direct sur le cumul 30 jours. La médiane quantile est rejetée pour sous-prévision massive.

Détails reproductibles : [forecasting_advanced.md](advanced/forecasting_advanced.md).

## Pricing

La cible reste la quantité confirmée au grain produit × jour × remise, évaluée sur toutes les lignes de trois tests de 60 jours. L'expérience exclut les proxies contemporains `n_lignes`, prix payé, CA/marge réalisés et achat web. CatBoost enrichi est le meilleur challenger honnête (WAPE 0,5569, biais +0,0206), mais ne franchit pas 0,38 et ne bat la baseline aucune remise que sur deux fenêtres sur trois. Aucun modèle n'est promu.

La référence LightGBM_calibre (WAPE 0,4164) reste figée mais utilisait `n_lignes`, corrélé à 0,708 avec la quantité et indisponible avant les ventes : elle n'est pas une preuve qu'une prédiction décisionnelle à 0,4164 soit réalisable. Le support commun n'a filtré aucune ligne. L'AIPW est publié comme sensibilité observationnelle uniquement. Le simulateur respecte coût et marge minimale sur 300 produits, mais recommande 0 % partout ; application automatique et interprétation causale restent interdites.

Détails reproductibles : [pricing_advanced.md](advanced/pricing_advanced.md).

## Recommandation générale avancée

Quatre fenêtres de 30 jours ont été évaluées, avec apprentissage strictement antérieur, candidats issus uniquement du passé, exclusions des articles déjà vus et vérité terrain sur commandes confirmées. Les métriques sont end-to-end (clients sans vérité conservés et scorés à zéro) et aucune population n'a été réduite.

| Système | Recall@10 moyen | NDCG@10 moyen | Couverture catalogue | Statut |
|---|---:|---:|---:|---|
| popularité globale | 0,0669 | 0,0377 | 0,061 | baseline officielle |
| hybride_web_historique | 0,0643 | 0,0373 | 0,298 | challenger exploratoire |
| CatBoost ranker | 0,0614 | 0,0349 | 0,405 | challenger |
| LightGBM ranker | 0,0536 | 0,0310 | 0,654 | challenger |
| BPR implicite | 0,0421 | 0,0248 | 0,906 | challenger |

Le gain hybride n'est pas présent : différence NDCG@10 vs popularité = -0,00665, IC95 % [-0,00943 ; -0,00401] au bootstrap client-fenêtre (5 000 tirages). Il ne satisfait ni Recall ≥ 0,08, ni NDCG ≥ 0,045, ni la stabilité sur 3/4 fenêtres. Aucun modèle n'est donc retenu ; la popularité globale reste la baseline utilisable. Les ablations confirment que web, stock et commandes changent la couverture mais pas la pertinence.

Le diagnostic sessionnel existant reste négatif : le pilote R3 perd 1,29 % de NDCG et 2,09 % de Recall face à la baseline sur les clients personnalisables, avec forte sparsité (~0,96). L'absence de signal persiste après alignement temporel et exclusions ; aucun modèle sessionnel n'est conservé comme utilisable. Le système « complémentaires panier » demeure séparé, évalué sur cooccurrence d'`order_id` et non comparable au recommender général.

Artefacts : `models/advanced/recommendation/general_metadata.json`, `general_recommender.joblib`, `manifest.sha256.json` et checkpoints par fenêtre. Disponibilités : BM25 manuel et BPR CPU ; LightFM/implicit et modèles séquentiels profonds non installés et non lancés.

## Gouvernance

Aucun artefact validé n'est remplacé, aucune fusion dans `main`, aucun déploiement et aucune écriture Supabase. Les domaines pricing et recommandation feront l'objet de commits distincts avant la conclusion finale.
