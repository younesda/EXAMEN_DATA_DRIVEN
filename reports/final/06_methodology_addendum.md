<!-- INVALIDATION-BANNER -->
> ## ⚠️ RÉSULTATS INVALIDÉS — 2026-08-18
>
> Les chiffres complément panier de ce rapport (`NDCG@10 = 0,0485`) sont
> **`invalidated_due_to_in_sample_evaluation_without_temporal_split`**.
>
> Motif : évaluation in-sample sans découpe temporelle.
>
> Ce document est conservé **tel quel** comme témoin de ce qui a été publié ; seul ce
> bandeau a été ajouté. Il ne doit plus servir de référence ni de cible.
>
> 👉 Résultats en vigueur : [`reports/44_corrected_recommendation_results.md`](../44_corrected_recommendation_results.md) · [`SUPERSEDED_RESULTS.md`](../../SUPERSEDED_RESULTS.md)

# 06 — Addendum méthodologique final

## Forecasting

Les trois fenêtres initiales couvraient uniquement les 90 derniers jours pour limiter le coût du premier benchmark. Ce n'était pas une contrainte des données : sur 546 jours, six fenêtres non chevauchantes de 30 jours laissent 366 jours de train avant la première. Les fenêtres existantes à 90/60/30 jours ont été réutilisées; les fenêtres 180/150/120 ont été ajoutées avec checkpoints. Après constat du coût inutile d'AutoETS, l'extension a été limitée aux deux modèles décisionnels et aux trois baselines simples.

| Usage | Modèle | WAPE quotidienne | WAPE cumulée 30 j | Victoires quotidiennes |
|---|---|---:|---:|---:|
| Quotidien | `CrostonOptimized` | 1,0945 | 0,3700 | 4/6 |
| Cumul 30 jours | `LightGBM_Tweedie` | 1,1010 | 0,3106 | 2/6 |
| Baseline robuste | `MovingAverage28` | 1,0979 | 0,3241 | 0/6 |

Aucun vainqueur global n'est déclaré.

Intervalles conformes de Croston, calibrés uniquement sur le bloc ou les fenêtres strictement antérieurs :

| Niveau | Segment | Couverture | Largeur moyenne | Points |
|---:|---|---:|---:|---:|
| 80 % | Global | 81,56 % | 2,841 | 54 000 |
| 80 % | ABC-A | 78,27 % | 3,181 | 28 290 |
| 80 % | Intermittents | 81,56 % | 2,841 | 54 000 |
| 95 % | Global | 94,95 % | 4,740 | 54 000 |
| 95 % | ABC-A | 94,57 % | 5,113 | 28 290 |
| 95 % | Intermittents | 94,95 % | 4,740 | 54 000 |

Toutes les 300 séries satisfont le critère d'intermittence ADI > 1,32, d'où l'identité des lignes global/intermittents. Contrôles : 0 NaN/infini, 0 négatif, 0 cold-start observé et 0 historique inférieur à 28 jours. Les replis existent néanmoins : moyenne globale pour cold-start; moyenne disponible puis SeasonalNaive7 pour historique court.

## Pricing

La WAPE `0,4164` porte sur la colonne `quantite`, au grain **produit × jour × remise**, commandes confirmées agrégées. Elle est poolée par fenêtre : `Σ|prédiction − quantité| / Σquantité`.

LightGBM est ajusté avant un bloc de calibration de 60 jours; le facteur multiplicatif est calculé sur ce bloc, dont la date maximale précède strictement le test dans les trois fenêtres.

| Fenêtre | Test | LightGBM calibré | Baseline moyenne produit |
|---:|---|---:|---:|
| 1 | 2026-02-02 → 2026-04-02 | 0,4197 | 0,5706 |
| 2 | 2026-04-03 → 2026-06-01 | 0,4189 | 0,5679 |
| 3 | 2026-06-02 → 2026-07-31 | 0,4105 | 0,5544 |

Promotions confirmées : catégorie, 11 584 lignes, 0 erreur de cible/date; produit, 384 lignes, 0 erreur de cible/date. Le livrable reste un simulateur observationnel de remises déjà observées, avec prix ≥ coût, marge minimale 5 %, validation humaine obligatoire, sans causalité ni prix optimal.

## Recommandation

| Fenêtre | NDCG global | NDCG hybride | ΔNDCG | Recall global | Recall hybride | ΔRecall |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0,03708 | 0,03846 | +0,00139 | 0,06733 | 0,06580 | -0,00153 |
| 2 | 0,03516 | 0,03620 | +0,00104 | 0,06275 | 0,06190 | -0,00085 |
| 3 | 0,03662 | 0,03706 | +0,00045 | 0,06167 | 0,06248 | +0,00081 |

Bootstrap apparié sur 7 384 unités client-fenêtre, 5 000 réplications, seed 42 :

- ΔNDCG@10 moyen `+0,000952`, IC95 % `[-0,000842 ; +0,002764]`;
- ΔRecall@10 moyen `-0,000515`, IC95 % `[-0,003584 ; +0,002512]`.

Les intervalles contiennent zéro et le Recall n'est pas stable : `hybride_achats_web` est classé `challenger_exploratoire`; `popularite_globale` est la baseline officielle.

Le scénario sessionnel est non utilisable : 0 violation temporelle et 0 cible hors catalogue, mais 100 % des cibles ont déjà été vues avant le purchase, 100 % des contextes ne contiennent que des articles de la vérité terrain, et la similarité item-item annule sa diagonale. Le modèle ne redonne donc aucun score direct à l'article vu qui est ensuite acheté. Exclure les vus ferait tomber l'éligibilité des cibles à 0 %. La vérité terrain est bien limitée aux purchases reliés à une commande confirmée.

`complémentaires panier` reste un système métier séparé (NDCG@10 0,0485), non comparable au recommender général.
