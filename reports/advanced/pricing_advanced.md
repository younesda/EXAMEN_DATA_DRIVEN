<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres `WAPE = 0,4164` (référence pricing citée) de ce rapport sont **`invalidated_due_to_target_leakage`**.
>
> Motif : la référence citée utilisait `n_lignes`, dont la cible `quantite` est la somme.
>
> Document conservé **tel quel** ; seul ce bandeau a été ajouté.
>
> 👉 Résultats en vigueur : [`43_corrected_pricing_results.md`](../43_corrected_pricing_results.md) · [`SUPERSEDED_RESULTS.md`](../../SUPERSEDED_RESULTS.md)

# Optimisation avancée — pricing

## Verdict

**Aucun challenger ne remplace le pricing validé.** CatBoost enrichi est le meilleur prédicteur avancé sans proxy contemporain, avec WAPE quantité 0,5569 et biais moyen +0,0206. Il n'atteint ni le seuil 0,38 ni l'idéal 0,35, et ne dépasse la baseline « aucune remise historique » que sur deux fenêtres sur trois.

La référence figée LightGBM_calibre affiche WAPE 0,4164 au même grain, mais elle utilise `n_lignes`, information contemporaine des ventes, corrélée à 0,708 avec la quantité. L'expérience avancée exclut `n_lignes`, le prix payé réalisé, CA, marge réalisée et achats web contemporains. L'écart ne doit donc pas être interprété comme une simple supériorité algorithmique de la référence.

## Cible et protocole

- Cible : `quantite` des commandes confirmées.
- Grain : `produit_key × ds × remise_pct` ; 55 586 lignes, sans doublon de grain.
- WAPE : somme des erreurs absolues divisée par la somme des quantités, poolée sur **toutes** les lignes de chaque test de 60 jours.
- Fenêtres test : 2026-02-02, 2026-04-03 et 2026-06-02 ; blocs non chevauchants.
- Pour chaque fenêtre, le fit s'arrête avant un bloc de calibration de 60 jours, lui-même strictement antérieur au test. Le tuning contrôlé LightGBM/CatBoost est réalisé dans ce passé seulement.
- Le support commun ne filtre jamais la population primaire.

## Résultats globaux

| Modèle/politique | WAPE | Biais | Écart-type fenêtre | Statut |
|---|---:|---:|---:|---|
| CatBoost enrichi | **0,5569** | +0,0206 | 0,0113 | meilleur challenger honnête, non promu |
| GLM Tweedie | 0,5590 | +0,0296 | 0,0119 | challenger |
| GLM Poisson | 0,5598 | +0,0323 | 0,0130 | challenger |
| Aucune remise historique | 0,5626 | +0,0324 | 0,0085 | baseline officielle simple |
| LightGBM enrichi | 0,5629 | +0,0360 | 0,0197 | challenger |
| Moyenne produit | 0,5643 | +0,0416 | 0,0087 | baseline |
| LightGBM pondéré propension | 0,5644 | +0,0429 | 0,0187 | sensibilité sélection |
| Effets fixes Poisson | 0,5650 | +0,0478 | 0,0207 | challenger |
| Politique historique produit×remise | 0,5661 | +0,0372 | 0,0081 | baseline historique |
| LightGBM_calibre validé | 0,4164 | -0,0035 | 0,0051 | référence figée, inclut `n_lignes` contemporain |

### CatBoost par fenêtre

| Fenêtre | WAPE | Biais | Baseline aucune remise | Verdict |
|---:|---:|---:|---:|---|
| 1 | 0,5689 | +0,0799 | 0,5684 | perd |
| 2 | 0,5551 | -0,0012 | 0,5666 | gagne |
| 3 | 0,5466 | -0,0171 | 0,5529 | gagne |

Le biais moyen respecte 0,03, mais la première fenêtre présente +0,080 : la stabilité temporelle nécessaire à une promotion n'est pas démontrée.

## Variables

Toutes les variables comportementales sont strictement décalées : ventes, vues, paniers, commandes, clients distincts et taille de panier en lags 1/7/28 et moyennes 7/28/84 ; conversion view→cart historique ; dernier stock connu ; fréquence passée de réapprovisionnement ; mix de segments fidélité sur 90 jours ; réponses produit/remise et catégorie/remise calculées avant la date ; exposition passée aux campagnes ; calendrier, catégorie, marque, produit ; remise planifiée, prix théorique et marges unitaires avant/après.

Principales importances CatBoost sur la dernière fenêtre : mois 5,89 %, moyenne historique produit 3,63 %, semaine 3,07 %, vues moyennes 84 j 2,84 %, taux de marge après remise 2,79 %, weekend 2,70 %, ventes moyennes 28 j 2,53 %, paniers moyens 28 j 2,49 %. Ce sont des associations prédictives, pas des effets causaux.

## Support commun, promotions et ablations

Le taux de support commun au seuil de propension 0,02 vaut 91,88 %, 87,73 % et 95,59 % selon les fenêtres. Les lignes hors support restent dans les métriques primaires. La remise 40 % ne compte que 9 agrégats et est exclue du simulateur par le seuil de support produit ≥ 10.

Audit validé des promotions confirmées :

| Portée | Lignes confirmées | Désalignement cible | Désalignement date | Remises |
|---|---:|---:|---:|---|
| catégorie | 11 584 | 0 | 0 | 5–30 % |
| produit | 384 | 0 | 0 | 5–40 % |

Sur CatBoost, la portée catégorie dispose de 719/1 786/728 lignes test et de WAPE 0,5606/0,5552/0,5471. La portée produit ne dispose que de 24/30/40 lignes et donne 0,5698/0,7030/0,5782 : elle est trop petite et instable pour une conclusion autonome.

Ablations LightGBM à configuration fixe, sans retuning :

| Variante | WAPE | Écart vs complet (0,5629) |
|---|---:|---:|
| sans promotion | 0,5598 | -0,0031 |
| sans stock | 0,5625 | -0,0004 |
| sans commandes/segments | 0,5635 | +0,0006 |
| sans web | 0,5639 | +0,0010 |

Les signaux commandes et web sont faiblement utiles. Les variables promotion/stock ne montrent pas de gain robuste dans cette spécification ; elles restent nécessaires au contrôle de support et aux contraintes, mais pas comme preuve d'uplift.

## Sensibilité observationnelle de l'uplift

Une estimation AIPW compare « remise positive observée » à « aucune remise », avec nuisances apprises avant le test, propension tronquée [0,02 ; 0,98] et bootstrap par produit (2 000 tirages).

| Fenêtre | Taux traité | Uplift quantité moyen | IC95 % |
|---:|---:|---:|---|
| 1 | 10,38 % | +0,291 | [0,154 ; 0,431] |
| 2 | 23,39 % | +0,398 | [0,346 ; 0,446] |
| 3 | 9,37 % | +0,184 | [0,140 ; 0,233] |

Ces valeurs restent **strictement observationnelles** : remise non randomisée, niveaux de remise regroupés en un traitement binaire, support imparfait et confondeurs potentiels. Elles ne prouvent aucun effet causal et ne permettent pas d'annoncer un prix optimal.

## Simulateur sous contraintes

Le scénario de marge utilise uniquement les remises observées au moins dix fois par produit, impose prix ≥ coût et marge ≥ 5 %, et exige validation humaine. Sur 300 produits : 0 NaN, 0 quantité négative, 0 prix sous coût, 0 violation du plancher ; marge minimale observée 10,24 %. Il recommande 0 % de remise aux 300 produits.

Cette sortie prudente est un **simulateur observationnel** sur la dernière ligne de features observée de chaque produit, pas une évaluation off-policy. Application automatique interdite, causalité interdite, write-back interdit.

## Ressources et décision métier

Exécution séquentielle, deux threads, checkpoints par modèle/fenêtre. Maximum observé 28,2 s par étape et environ 419 Mo RSS ; aucun échec final. Les artefacts validés restent inchangés. Usage autorisé : analyse exploratoire et simulation humaine de remises historiquement supportées. Usage interdit : tarification automatique, inférence causale, extrapolation hors support ou promesse de marge incrémentale.
