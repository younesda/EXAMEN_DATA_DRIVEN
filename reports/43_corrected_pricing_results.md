# 43 — Résultats pricing corrigés

> Série « correction » du 2026-08-18. Supersède toute mention de
> `WAPE = 0,4164`, désormais `invalidated_due_to_target_leakage`.
> Série « correction » du 2026-08-18, numérotée 42 à 45 pour ne coexister
> avec aucun rapport historique. Elle supersède les rapports antérieurs sans
> les supprimer : chacun conserve son contenu d'origine et porte un bandeau
> d'invalidation. Voir [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md).

Reproduction : `python -m src.experiments.pricing_corrected`
Sortie : `reports/advanced/pricing_corrected.json`,
`models/advanced/pricing_corrected/`.

---

## 1. Périmètre, inchangé

| Élément | Valeur |
|---|---|
| Cible | `quantite` confirmée |
| Grain | `produit_key × ds × remise_pct` |
| Population | lignes de commandes confirmées, aucune exclusion |
| Fenêtres | 3 tests de 60 jours (recul 180 / 120 / 60 j) |
| Lignes de test | 7 151 / 7 757 / 8 179 |
| Train | strictement antérieur au test, vérifié par test |

Périmètre identique à l'expérience avancée publiée : les comparaisons avec
`CatBoost_enriched` (0,5569) portent sur exactement les mêmes lignes.

## 2. Registre de features

`src/pricing/feature_registry.py` — 81 variables classées, **70 autorisées**,
**11 interdites**. Règle unique : une feature n'est autorisée que si sa valeur
est entièrement déterminée **avant `D 00:00`**.

| Famille | Nombre | Disponibilité | Exemples |
|---|---:|---|---|
| statique | 6 | catalogue figé | `prix_base_xof`, `cout_xof`, `product_code` |
| planifié | 14 | `D-1 23:59` ou déterministe | `remise_pct`, `product_campaign_active`, `dow` |
| historique | 50 | `D-1 23:59` | `sales_lag_1`, `orders_mean_28`, `stock_at_cutoff` |
| **interdit** | **11** | **`D 23:59`** | **`n_lignes`, `ca_xof`, `marge_xof`, `order_count`, `distinct_clients`, `avg_basket_quantity`, `prix_unitaire_paye_xof`, `niveau_stock`, `y`, `quantite_vendue`, `quantite`** |

Le registre complet, avec justification par ligne, est dans
`reports/advanced/pricing_corrected.json` → `registre_features.registre`.

Point important : `order_count`, `distinct_clients` et `avg_basket_quantity`
sont **interdites en valeur contemporaine** mais autorisées sous leurs formes
retardées (`orders_lag_1`, `clients_mean_28`, `basket_mean_84`…), toutes
construites par `shift(1)` puis `rolling`. Le test de perturbation vérifie
qu'aucune ne lit le jour cible.

## 3. Résultats sur les trois fenêtres

| Modèle | F1 | F2 | F3 | WAPE | Forecast Bias | MAE | Err. marge abs. | Err. marge signée | σ WAPE | Amplitude |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `lgbm_l1_mediane` | 0,5195 | 0,5230 | 0,5230 | **0,5218** | **−0,1814** | 1,3443 | 0,5214 | −0,1798 | 0,0020 | 0,0035 |
| `baseline_produit_mediane` | 0,5250 | 0,5279 | 0,5213 | 0,5247 | −0,1719 | 1,3517 | 0,5239 | −0,1731 | 0,0033 | 0,0066 |
| `lgbm_l1_calibre_fenetres_anterieures` | 0,5392 | 0,5503 | 0,5517 | 0,5470 | −0,0378 | 1,4095 | 0,5462 | −0,0367 | 0,0069 | 0,0126 |
| `lgbm_l1_calibre_bloc_anterieur` | 0,5392 | 0,5503 | 0,5565 | 0,5486 | −0,0304 | 1,4136 | 0,5477 | −0,0294 | 0,0088 | 0,0173 |
| **`lgbm_tweedie_moyenne`** | 0,5535 | 0,5581 | 0,5461 | **0,5526** | **+0,0013** | 1,4234 | 0,5532 | +0,0053 | 0,0061 | 0,0120 |
| `CatBoost_enriched` (publié) | 0,5689 | 0,5551 | — | 0,5569 | +0,0206 | — | — | — | 0,0113 | — |
| `baseline_produit_moyenne` | 0,5706 | 0,5679 | 0,5544 | 0,5643 | +0,0416 | 1,4535 | 0,5689 | +0,0600 | 0,0087 | 0,0162 |

Bootstrap apparié (ligne produit × jour × remise, 4 000 tirages, n = 23 087) :
`lgbm_l1_mediane` − `lgbm_tweedie_moyenne` = **−0,0305**, IC95
**[−0,0333 ; −0,0278]**, entièrement favorable, 3 fenêtres sur 3.

## 4. Le conflit WAPE / biais, et pourquoi il est structurel

La WAPE est une perte L1 : son optimum est la **médiane** conditionnelle. La
distribution de `quantite` sachant qu'une vente a eu lieu est asymétrique
(moyenne 2,645, médiane 2,0). Prédire la médiane améliore mécaniquement la WAPE
**et sous-estime le volume de 18 %**.

La calibration de biais, apprise **strictement sur le passé**, a été testée sous
deux formes :

| Source du facteur | WAPE | Biais |
|---|---:|---:|
| aucune (médiane brute) | 0,5218 | −0,1814 |
| bloc de 60 j antérieur au test, exclu du fit | 0,5486 | −0,0304 |
| moyenne des fenêtres d'évaluation antérieures | 0,5470 | −0,0378 |

Elle **réduit fortement le biais** (−18,1 % → −3,0 %) mais ne franchit pas la
tolérance de ±3 %, et à ce niveau la WAPE (0,5486) n'est plus meilleure que
celle du modèle de moyenne (0,5526) que de 0,7 %. La frontière complète, par
ré-échelle multiplicative :

| Facteur | WAPE | Biais |
|---|---:|---:|
| ×1,00 | 0,5218 | −0,1814 |
| ×1,10 | 0,5344 | −0,0996 |
| ×1,20 | 0,5519 | −0,0177 |
| ×1,22 | 0,5556 | −0,0014 |

**À biais nul, la meilleure WAPE honnête est 0,5526**, atteinte directement par
le modèle de moyenne.

## 5. Trois décisions séparées

### Décision 1 — meilleur prédicteur WAPE

`lgbm_l1_mediane`, WAPE **0,5218**, biais **−0,1814**.
`utilisable_comme_simulateur = false`. Ce modèle répond à la question
« quelle est la quantité **typique** ? », pas « quel est le volume **attendu** ? ».

### Décision 2 — meilleur modèle de volume à biais acceptable (|biais| ≤ 3 %)

`lgbm_tweedie_moyenne`, WAPE **0,5526**, biais **+0,0013**.
Gain contre le meilleur challenger honnête publié (0,5569) : **+0,77 %**.
Gate de promotion à 5 % : **non franchi**.

### Décision 3 — simulateur de marge

Alimenté par la **décision 2 uniquement**. Garde-fous inchangés et intégralement
en vigueur : prix ≥ coût, marge minimale 5 %, remises limitées au support
historique observé, validation humaine obligatoire, application automatique
interdite, aucun effet causal estimé.

Le modèle de la décision 1 ne peut pas alimenter le simulateur : une
sous-estimation de 18 % du volume fausserait toute projection de marge dans le
même sens.

## 6. Verdict

**Pricing non promouvable.** Le seul modèle qui améliore réellement la WAPE le
fait en changeant de cible statistique, au prix d'un biais rédhibitoire pour
l'usage métier. Sous contrainte de biais, le gain disponible est de 0,77 %.

Ce qui reste impossible avec ces données : toute revendication causale (prix
catalogue fixe sur les 300 produits, campagnes non randomisées), tout prix
optimal continu, et toute WAPE inférieure à ≈ 0,487 sans information
contemporaine.
