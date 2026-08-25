<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres complément panier de ce rapport (`Recall@10 = 0,437`, `NDCG@10 = 0,213`, `Recall@10 = 0,1006`, `NDCG@10 = 0,0485`) sont
> **`invalidated_due_to_target_category_leakage`**.
>
> Motif : le scoring recevait la catégorie de l'article masqué ; les valeurs héritées 0,1006 / 0,0485 proviennent en outre d'une évaluation in-sample sans découpe temporelle.
>
> Ce document est conservé **tel quel** comme témoin de ce qui a été publié ; seul ce
> bandeau a été ajouté. Il ne doit plus servir de référence ni de cible.
>
> 👉 Résultats en vigueur : [`reports/44_corrected_recommendation_results.md`](44_corrected_recommendation_results.md) · [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md)

# 11 — Recommendation avancée : audit des candidats

Statut : audit borné de couverture, sans nouveau ranker lourd ni modification des branches validées.

## Références verrouillées

- Recommandation générale officielle : `popularite_globale`, Recall@10 ≈ 0,0634, NDCG@10 ≈ 0,0363, couverture ≈ 6,22 %.
- Complément panier : Recall@10 ≈ 0,1006, NDCG@10 ≈ 0,0485, couverture ≈ 89,33 %. Ce système reste séparé du recommender général.

## Réconciliation prochain achat

Les anciennes métriques sont end-to-end sur 4 fenêtres de 60 jours, avec 2 321–2 490 clients, 2 266–2 440 clients ayant une cible, politique générale incluant réapprovisionnement, et couverture catalogue calculée sur les 300 produits : environ 5,67–6,33 % (17–19 produits uniques recommandés au Top-10).

Le nouveau pilote F1–F2 est conditionnel au candidate set, sur des fenêtres de 30 jours, 1 538 puis 2 228 clients évaluables, 867 puis 1 024 clients avec une cible découverte présente dans les candidats. Les produits déjà achetés sont exclus. La couverture précédente « 100 % » était une couverture des clients recevant une liste, pas une couverture catalogue ; la couverture catalogue correcte est `produits uniques recommandés / 300`, soit 14/300 = 4,67 % en F1 et 18/300 = 6,00 % pour `popularite_globale` au Top-10.

Les valeurs 0,1305 et 0,1139 du pilote ne sont donc pas comparables aux 0,0634–0,0759 end-to-end : elles sont calculées uniquement sur les candidats déjà générés et une population découverte de 30 jours. La formule Recall@10 reste `hits@10 / nombre de produits cibles`, moyennée par client ; la couverture catalogue est `nombre de produits uniques dans les Top-10 / 300 produits éligibles`.

## Audit des candidats

Le générateur général déjà validé fournit un plafond candidat@50 inférieur observé de 0,6131 / 0,5834 / 0,5933 / 0,5964 sur les quatre fenêtres. Le gate prochain achat ≥0,50 est donc franchi au niveau candidat, sans injecter les cibles futures. Les sources sont globales, récentes, catégorie, item-item commandes, BM25/SVD/BPR implicites et web historique.

Les 22 460 commandes multi-produits sont conservées pour le complément panier. Une fenêtre est évaluable seulement si elle possède au moins une commande d’entraînement, au moins deux produits connus et au moins une cible présente dans le catalogue train. F1 est donc `non_evaluable_no_history`, avec `model_evaluation_allowed=false` et `fallback_required=true`. Le gate candidat est évalué sur F2–F4 uniquement et est franchi (0,8676 / 0,8895 / 0,9332).

Le scénario sessionnel reste inutilisable : le diagnostic historique indique une cible déjà vue dans 100 % des cas et une exclusion des articles vus non appliquée. Aucune règle de restitution d’un article déjà présent n’est considérée comme recommandation.

## Ranking et décision

Aucun LightGBM LambdaRank, XGBoost ranking, CatBoostRanker, ALS/BPR ou modèle profond n’est relancé sur les mêmes données. Le prochain achat, le complément panier et la session ont des cibles et métriques strictement séparées. Les features doivent rester antérieures au cutoff ; aucun `purchase` futur ne peut entrer dans le ranking.

La popularité globale demeure le modèle officiel tant qu’un pilote hors échantillon n’apporte pas un gain NDCG stable, avec bootstrap client×fenêtre à IC95 % entièrement positif. Le complément panier reste un système métier indépendant ; aucune causalité ni personnalisation garantie n’est déduite.

## Pilote ranking prochain achat (F1–F2)

Le candidat set a été réutilisé avec négatifs reproductibles (seed 42) et hard negatives issus des générateurs. Les deux rankers ont été entraînés avec features strictement antérieures au cutoff et groupes `client_key×cutoff`.

| Modèle | Recall@10 moyen | NDCG@10 moyen | Couverture | Décision |
|---|---:|---:|---:|---|
| popularite_globale | 0,1305 | 0,0639 | 100 % | baseline |
| heuristique_rrf | 0,1212 | 0,0602 | 100 % | challenger |
| LightGBM_LambdaRank | 0,0882 | 0,0432 | 100 % | gate échoué |
| logistique_pointwise | 0,0747 | 0,0348 | 100 % | baseline supervisée |

Le gain NDCG ≥5 % n'est pas atteint et le Recall@10 baisse de plus de 2 %. Aucun passage F3–F4 ni bootstrap n'est justifié. La popularité globale reste officielle.

## Complément panier — candidat@50

Validation leave-one-item-out sur 22 460 commandes multi-produits, commandes entières dans un seul split. Les scores candidats ont été calculés séparément par cooccurrence, association support/confiance/lift, BM25 panier et popularité catégorie.

La popularité catégorie atteint 0,6820 en moyenne mais 0 en fenêtre 1, où aucun historique antérieur admissible n'est disponible. L'union Top-50 des générateurs atteint Recall@50 : 0,0000 / 0,8676 / 0,8895 / 0,9332 sur F1–F4 ; Recall@10 : 0,0000 / 0,4424 / 0,3771 / 0,3454 ; Recall@20 : 0,0000 / 0,7447 / 0,6469 / 0,5841. Les tailles moyennes d'union sont 0 / 48,0 / 48,8 / 49,5 candidats par panier. F1 n'est pas une fenêtre à zéro du modèle : elle est non évaluable. La baseline ordonnée `candidate_union_rrf` est publiée sur F2–F4 ; aucun modèle n'est promu sans comparaison end-to-end et bootstrap commande×fenêtre entièrement favorable. La référence métier reste Recall@10 0,1006, NDCG@10 0,0485, couverture 89,33 %.

Diagnostic F1 : 0 commande d'entraînement, 5 338 commandes test, 0 produit distinct dans le train, 188 produits distincts en test, 0 % des cibles présentes dans le catalogue train, 0 candidat moyen et 100 % de cold-start. Les cinq premiers paniers test sont CMD00000001 (PRD000024, PRD000212, PRD000295), CMD00000003 (PRD000113, PRD000225), CMD00000006 (PRD000143, PRD000252), CMD00000008 (PRD000215, PRD000239) et CMD00000011 (PRD000018, PRD000070, PRD000082). Il s'agit d'un split chronologique trop précoce, pas d'une incompatibilité d'identifiants ni d'une exclusion de cible.

## Protocole futur

Après de nouvelles données ou une définition sessionnelle corrigée, exécuter quatre fenêtres temporelles, tuning uniquement antérieur, checkpoints séquentiels, tests de fuite par perturbation, déterminisme, doublons Top-10, éligibilité, diversité, nouveauté, concentration et bootstrap à 95 %. Le reranking métier ne pourra réduire la pertinence de plus de 2 % hors scénario explicitement « découverte ».

## Sorties end-to-end complément panier F2–F4

Les recommandations Top-20 (dont le Top-10) sont matérialisées dans `complement_topk_predictions.parquet`. Chaque ligne conserve `order_id`, fenêtre, cible masquée, contexte, union de candidats, modèle, rang et score. La cible est absente du contexte, les commandes restent indivisibles entre splits et les produits sont dédupliqués.

Les métriques comparables sont publiées dans `complement_end_to_end_metrics.csv` pour référence, popularité globale, popularité catégorie, cooccurrence, BM25, association et `candidate_union_rrf`, sur 5/10/20. Le bootstrap stratifié par fenêtre au grain commande comporte 2 000 réplications : IC95 % de la différence NDCG@10 RRF − meilleure baseline = [-0,00268 ; -0,00033]. Le gain est donc défavorable ; RRF ne franchit pas le gate. Comme le Recall candidat@50 reste supérieur à 0,86, LambdaRank a été entraîné sur F2–F3 puis évalué sans retuning sur F4 : RRF obtient Recall@10 0,3290 et NDCG@10 0,1605, contre 0,3025 et 0,1516 pour LambdaRank. LambdaRank est rejeté et l’ancienne référence complément panier est conservée.

## Artefacts

Métadonnées, couverture candidat et manifeste SHA-256 : `models/advanced/recommendation_ranking/`. Aucun write-back Supabase, déploiement, merge ou push n’est autorisé dans ce commit.

## Décision comparative finale F2–F4

La meilleure baseline simple exacte est `popularite_categorie`, ex æquo avec l’ancienne référence recalculée sur ce même périmètre (la référence est donc cette règle, et non une ancienne métrique globale). F2/F3/F4 : Recall@10 = 0,4374 / 0,3604 / 0,3346 ; NDCG@10 = 0,2126 / 0,1802 / 0,1630 ; couverture catalogue = 30,67 % / 31,00 % / 31,33 %. La couverture reste sous 70 %, donc aucune promotion.

Le tableau complet (commandes, Recall/NDCG@5/10/20, MAP@10, MRR, HitRate@10, couverture, diversité, nombre moyen de recommandations) est dans `complement_end_to_end_metrics.csv`. Bootstrap apparié stratifié : catégorie−référence = 0 ; RRF−référence IC95 % [-0,00268 ; -0,00033] ; LambdaRank F4−catégorie IC95 % [-0,00449 ; -0,00050].

Les scores F4 élevés (RRF Recall@10 0,3290, NDCG@10 0,1605) proviennent du nouveau périmètre leave-one-item-out : une cible masquée par commande, commandes multi-produits uniquement et fenêtres F2–F4 évaluables. Les anciennes valeurs 0,1006 / 0,0485 sont end-to-end sur une population et une définition de cible différentes ; elles ne constituent pas une comparaison numérique directe.

## Statut métier final

- `general_recommendation_model = popularite_globale`.
- `basket_complement_model = ancienne_reference / popularite_categorie` (ex æquo sur le périmètre comparable F2–F4) ; RRF est seulement un challenger de diversité si sa couverture supérieure est utile.
- `session_model_status = non_utilisable`.

Périmètres et formules sont explicites : Recall@k = hits@k / cibles masquées ; NDCG@k = gain actualisé / gain idéal ; couverture catalogue = produits uniques recommandés / 300 produits éligibles. Le prochain axe d’amélioration est la couverture catalogue, autour de 31 % sur F2–F4, et non une nouvelle optimisation de pertinence. Aucune revendication croisée n’est faite entre les anciennes métriques et le leave-one-item-out.
