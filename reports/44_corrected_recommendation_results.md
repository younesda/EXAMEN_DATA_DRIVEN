# 44 — Résultats recommandation corrigés

> Série « correction » du 2026-08-18. Supersède `Recall@10 0,437 / NDCG@10 0,213`
> (`invalidated_due_to_target_category_leakage`) et `Recall@10 0,1006 /
> NDCG@10 0,0485` (`invalidated_due_to_in_sample_evaluation_without_temporal_split`).
> Série « correction » du 2026-08-18, numérotée 42 à 45 pour ne coexister
> avec aucun rapport historique. Elle supersède les rapports antérieurs sans
> les supprimer : chacun conserve son contenu d'origine et porte un bandeau
> d'invalidation. Voir [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md).

Reproduction :
`python -m src.experiments.complement_honest_baseline`,
`python -m src.experiments.complement_end_to_end`,
`python -m src.experiments.complement_candidate_pilot`.

---

## 1. Statut métier officiel

```text
basket_complement_model    = none_validated
basket_complement_baseline = popularite_globale
reason                     = no_complementarity_signal
```

## 2. Périmètre, inchangé

21 352 commandes multi-produits, quatre découpes chronologiques, fenêtres
**F2–F4** évaluables, **une cible masquée par commande** (`sorted(items)[0]`),
contexte = les autres articles, catalogue de 300 produits, unité métrique =
commande, 5 338 commandes par fenêtre. F1 reste `non_evaluable_no_history`
(0 commande d'entraînement) : ce n'est pas une exclusion opportuniste.

Train strictement antérieur au test, vérifié par test sur chaque fenêtre.

## 3. Baselines honnêtes sur F2–F4

Toutes n'utilisent que le contexte observé et l'historique antérieur, avec une
règle de classement identique.

| Modèle | Recall@10 | NDCG@10 | Couverture | IC95 vs référence | Fenêtres | Promu |
|---|---:|---:|---:|---|---:|---|
| **`popularite_globale` (référence)** | **0,0556** | **0,0240** | 0,042 | — | — | — |
| `rrf_contexte` | 0,0564 | 0,0257 | 0,630 | [−0,00016 ; 0,00351] | 2/3 | non |
| `popularite_categorie_contexte` | 0,0544 | 0,0253 | 0,319 | [−0,00075 ; 0,00339] | 2/3 | non |
| `cooccurrence_item_item` | 0,0551 | 0,0247 | 0,661 | [−0,00117 ; 0,00270] | 2/3 | non |
| `bm25_panier` | 0,0518 | 0,0231 | 0,764 | [−0,00306 ; 0,00121] | 2/3 | non |
| `association_lift` | 0,0366 | 0,0162 | 0,771 | [−0,00993 ; −0,00557] | 0/3 | non |

Détail par fenêtre — NDCG@10 :

| Modèle | F2 | F3 | F4 |
|---|---:|---:|---:|
| `popularite_globale` | 0,0322 | 0,0212 | 0,0186 |
| `rrf_contexte` | 0,0295 | 0,0246 | 0,0230 |
| `popularite_categorie_contexte` | 0,0295 | 0,0243 | 0,0220 |
| `cooccurrence_item_item` | 0,0325 | 0,0236 | 0,0221 |
| `bm25_panier` | 0,0259 | 0,0218 | 0,0215 |
| `association_lift` | 0,0181 | 0,0178 | 0,0131 |

Bootstrap apparié commande × fenêtre, 4 000 tirages, n = 16 014.

Le meilleur challenger, `rrf_contexte`, atteint **+7,14 %** de NDCG@10 et
**+1,46 %** de Recall@10 — mais son IC95 `[−0,00016 ; 0,00351]` **traverse
zéro** et il ne gagne que 2 fenêtres sur 3. Le gate exige un IC95 entièrement
positif : **aucune promotion**.

## 4. Avant / après la correction

| Métrique | Publié (fuité) | Honnête | Rapport |
|---|---:|---:|---:|
| Recall@10 F2 | 0,4374 | 0,0620 | ÷ 7,1 |
| Recall@10 F3 | 0,3604 | 0,0532 | ÷ 6,8 |
| Recall@10 F4 | 0,3346 | 0,0476 | ÷ 7,0 |
| NDCG@10 moyen | 0,1853 | 0,0253 | ÷ 7,3 |
| Recall@50 candidat F2 | 0,8676 | 0,2964 | ÷ 2,9 |
| Recall@50 candidat F3 | 0,8895 | 0,2486 | ÷ 3,6 |
| Recall@50 candidat F4 | 0,9332 | 0,2241 | ÷ 4,2 |

Le gate candidat ≥ 0,50 n'est plus franchi sur aucune fenêtre.

## 5. Pourquoi aucun modèle ne peut combler l'écart

Test structurel, indépendant de tout modèle, sur les 21 352 commandes
multi-produits :

```text
P(catégorie de la cible présente dans le contexte) = 0,2182
P attendue si les articles étaient tirés indépendamment = 0,222
```

Les deux valeurs coïncident. **Les paniers sont statistiquement des tirages
indépendants** : il n'existe pas de complémentarité à exploiter. Cela explique
sans recours à un modèle pourquoi la cooccurrence, l'association et BM25 se
tiennent tous autour de NDCG@10 ≈ 0,02–0,03, et pourquoi la référence fuitée
paraissait sept fois meilleure.

## 6. Requalification des anciennes valeurs, par provenance exacte

### `Recall@10 0,437 / NDCG@10 0,213`

`invalidated_due_to_target_category_leakage`.
Provenance : `src/experiments/complement_end_to_end.py`, périmètre
leave-one-item-out F2–F4. La catégorie de scoring était celle de la cible
masquée. Inflation mesurée : +0,1598 de NDCG@10, IC95 [0,1556 ; 0,1639].

### `Recall@10 0,1006 / NDCG@10 0,0485 / couverture 0,8933`

`invalidated_due_to_in_sample_evaluation_without_temporal_split`.
Provenance : `src/pipelines/final_recommendation.py`, bloc
« Complémentaires panier ». Trois défauts cumulés : matrice de similarité issue
de la dernière fenêtre d'entraînement, évaluation sur la **totalité** des
commandes sans découpe train/test, et cible masquée `ps[-1]` — périmètre
distinct du leave-one-item-out. Ces valeurs ne sont donc **ni valides, ni
comparables** aux précédentes : ce sont deux protocoles différents, tous deux
invalides pour des raisons différentes.

## 7. Prochain achat — inchangé et valide

Le pipeline `advanced_recommendation.py` a été audité séparément : entraînement
sur `date_commande < cutoff`, aucune feature dérivée de la cible. **Aucune
fuite.** `popularite_globale` reste la baseline officielle, et le rejet des
rankers personnalisés est confirmé — conclusion cohérente avec l'absence de
structure de co-achat établie en §5.

## 8. Sessionnel

`session_model_status = non_utilisable`, inchangé : cible déjà vue dans 100 %
des cas.
