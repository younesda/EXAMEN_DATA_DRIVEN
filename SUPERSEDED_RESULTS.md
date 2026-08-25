# Résultats supersédés et invalidés

**Date d'invalidation : 2026-08-18.**
Auteur : audit indépendant (branche d'audit dédiée, 2026-08-18).

Ce document est la référence unique pour savoir quel résultat de ce dépôt est
encore valide. **Aucun résultat n'a été supprimé** : tout est conservé, étiqueté
et traçable. L'historique Git et les branches distantes ne sont pas modifiés ;
les rapports de la série « correction » (42 à 45) les supersèdent.

---

## 1. Résultats FORECASTING — valides

| Élément | Valeur | Statut |
|---|---:|---|
| Modèle planification 30 j | `LightGBM_direct_per_horizon` | **valide** |
| WAPE30 macro (6 fenêtres) | 0,25831 | **valide, reproduite à l'identique** |
| WAPE30 micro poolée | 0,25743 | **valide** |
| Forecast Bias | −0,02589 | **valide** |
| WAPE quotidienne macro | 1,0870 | **valide** |
| Modèle quotidien | `CrostonOptimized` | **valide** |

Audit de fuite négatif : filtre d'entraînement sur `target_ds <= test_start − 1 j`,
tuning sur pseudo-cutoff antérieur, features exclusivement
`shift`/`rolling`/`expanding` arrière. Seule information future : `planned_discount`,
hypothèse métier explicite, documentée et ablatée.

Marge résiduelle : oracle de niveau à 0,24361, plancher de bruit ≈ 0,22.

---

## 2. Résultats PRICING — invalidés

**Motif : `invalidated_due_to_target_leakage`.**

`src/pipelines/final_pricing.py` utilisait `n_lignes` comme feature. `n_lignes`
est le nombre de lignes de commande confirmées du produit-jour ; la cible
`quantite` en est la somme (ratio borné à [1 ; 5], corrélation 0,708). La
variable n'existe qu'après la journée de ventes.

**Preuve indépendante :** un oracle honnête (médiane produit × remise calculée
dans le test) plafonne à 0,4866 / 0,4838 / 0,4931. Une WAPE de 0,4164 est sous
ce plancher.

| Modèle | WAPE publiée (fuitée) | WAPE après retrait de `n_lignes` | Statut |
|---|---:|---:|---|
| `LightGBM_calibre` | 0,41637 | 0,56254 | **invalidé** |
| `GLM_Tweedie` | 0,42069 | 0,56329 | **invalidé** |
| `GLM_Poisson` | 0,42211 | 0,56307 | **invalidé** |
| `panel_effets_fixes` | 0,42299 | 0,56138 | **invalidé** |
| `hierarchique_categorie` | 0,56272 | 0,56272 | valide (n'utilisait pas la variable) |
| `baseline_moyenne_produit` | 0,56430 | 0,56430 | valide |
| `descriptif_intra_produit` | 0,56606 | 0,56606 | valide |

**Conservation :** `models/pricing/metadata.invalidated.json` (charge historique
intégrale + motif).

---

## 3. Résultats COMPLÉMENT PANIER — invalidés

### 3.1 Périmètre leave-one-item-out F2–F4

**Motif : `invalidated_due_to_target_category_leakage`.**

`complement_end_to_end.py` et `complement_candidate_pilot.py` dérivaient la
catégorie de scoring de la cible masquée
(`cat = g.loc[g.produit_key.eq(target),'categorie'].iloc[0]`).

| Élément | Valeur publiée | Statut |
|---|---:|---|
| Recall@10 (moyenne F2–F4) | 0,3775 | **invalidé** |
| NDCG@10 (moyenne F2–F4) | 0,1853 | **invalidé** |
| Recall@10 F2 / F3 / F4 | 0,4374 / 0,3604 / 0,3346 | **invalidé** |
| NDCG@10 F2 / F3 / F4 | 0,2126 / 0,1802 / 0,1630 | **invalidé** |
| Recall@50 candidat F2–F4 | 0,8676 / 0,8895 / 0,9332 | **invalidé** |
| Statut métier `popularite_categorie` | référence | **non déployable** |

Inflation mesurée : +0,15977 de NDCG@10, IC95 [0,15555 ; 0,16393], n = 16 014.
Facteur ≈ 7×.

### 3.2 Métrique end-to-end héritée

**Motif : `invalidated_due_to_in_sample_evaluation_without_temporal_split`.**

`src/pipelines/final_recommendation.py`, bloc « Complémentaires panier » :
similarité item-item issue de la dernière fenêtre d'entraînement, évaluation sur
la **totalité** des commandes sans découpe train/test, cible masquée `ps[-1]`.

| Élément | Valeur publiée | Statut |
|---|---:|---|
| Recall@10 | 0,1006 | **invalidé** |
| NDCG@10 | 0,0485 | **invalidé** |
| Couverture catalogue | 0,8933 | **invalidé** |

Ces valeurs ne sont **ni valides, ni comparables** à celles de §3.1 : deux
protocoles différents, invalides pour des raisons différentes.

**Conservation :** `models/advanced/recommendation_ranking/invalidated/`
(10 artefacts + `INVALIDATION.json` + manifeste SHA-256 dédié).

---

## 4. Nouveaux résultats corrigés

### Pricing

| Modèle | WAPE | Biais | Rôle |
|---|---:|---:|---|
| `lgbm_l1_mediane` | 0,5218 | −0,1814 | meilleur prédicteur WAPE, **non utilisable comme simulateur** |
| `lgbm_l1_calibre_bloc_anterieur` | 0,5486 | −0,0304 | calibration de biais apprise sur le passé |
| `lgbm_tweedie_moyenne` | **0,5526** | **+0,0013** | **modèle de volume officiel**, alimente le simulateur |

Aucun modèle promu : gain 0,77 % contre le meilleur challenger honnête publié
(0,5569), sous le gate de 5 %.

### Complément panier

```text
basket_complement_model    = none_validated
basket_complement_baseline = popularite_globale
reason                     = no_complementarity_signal
```

| Modèle | Recall@10 | NDCG@10 | Couverture | IC95 vs référence |
|---|---:|---:|---:|---|
| `popularite_globale` (référence) | 0,0556 | 0,0240 | 0,042 | — |
| `rrf_contexte` | 0,0564 | 0,0257 | 0,630 | [−0,00016 ; 0,00351] |
| `popularite_categorie_contexte` | 0,0544 | 0,0253 | 0,319 | [−0,00075 ; 0,00339] |
| `cooccurrence_item_item` | 0,0551 | 0,0247 | 0,661 | [−0,00117 ; 0,00270] |
| `bm25_panier` | 0,0518 | 0,0231 | 0,764 | [−0,00306 ; 0,00121] |
| `association_lift` | 0,0366 | 0,0162 | 0,771 | [−0,00993 ; −0,00557] |

Aucun IC95 entièrement positif : aucune promotion.

**Preuve d'absence de signal :** `P(catégorie cible ∈ contexte) = 0,2182` contre
`0,222` attendus sous indépendance. Les paniers sont des tirages indépendants.

---

## 5. Fichiers et rapports remplacés

| Élément superseédé | Remplacé par | Motif |
|---|---|---|
| `reports/09_pricing_advanced_optimization.md` (référence 0,4164) | `reports/43_corrected_pricing_results.md` | fuite `n_lignes` |
| `reports/11_recommendation_advanced_ranking.md` (0,437 / 0,213 et 0,1006 / 0,0485) | `reports/44_corrected_recommendation_results.md` | fuite catégorie cible + évaluation in-sample |
| `reports/08_advanced_optimization_report.md` (synthèse pricing et reco.) | `reports/45_final_corrected_decision.md` | idem |
| `reports/final/03_pricing.md` | `reports/43_corrected_pricing_results.md` | fuite `n_lignes` |
| `reports/final/04_recommendation.md` (NDCG@10 0,0485) | `reports/44_corrected_recommendation_results.md` | évaluation in-sample |
| `reports/final/06_methodology_addendum.md` (NDCG@10 0,0485) | `reports/44_corrected_recommendation_results.md` | évaluation in-sample |
| `models/pricing/metadata.json` (version fuitée) | `models/pricing/metadata.invalidated.json` + version régénérée | fuite `n_lignes` |
| `models/advanced/recommendation_ranking/complement_*` (versions fuitées) | `.../invalidated/` + versions régénérées | fuite catégorie cible |
| `models/advanced/pricing/metadata.json` (challengers honnêtes) | `models/advanced/pricing_corrected/` | complété, non invalidé |

Les rapports supersédés conservent **leur contenu d'origine intégral** : ils
restent le témoin de ce qui a été publié. Seul un bandeau d'invalidation a été
ajouté en tête de chacun, afin qu'un lecteur y arrivant directement — sans passer
par le README — voie immédiatement le statut. Aucune valeur, aucun tableau et
aucune conclusion d'origine n'a été retouché.

Rapports portant un bandeau : `reports/08_advanced_optimization_report.md`,
`reports/09_pricing_advanced_optimization.md`,
`reports/11_recommendation_advanced_ranking.md`, `reports/final/03_pricing.md`,
`reports/final/04_recommendation.md`,
`reports/final/06_methodology_addendum.md`.

C'est ce document et la série 42–45 qui font foi.

---

## 6. Résumé pour un lecteur pressé

- **Forecasting : valide.** 0,25831 tient, reproduit à l'identique.
- **Pricing : la référence 0,4164 n'existe pas.** Le vrai niveau honnête est
  0,5526 à biais nul.
- **Complément panier : les deux références publiées sont invalides.** Le niveau
  honnête est NDCG@10 0,0240, et aucun modèle ne le bat de façon crédible.
- **Aucun modèle n'est promu nulle part.**
