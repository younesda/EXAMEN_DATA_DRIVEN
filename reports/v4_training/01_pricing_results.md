# 01 — Résultats pricing V4

Statut : `synthetic_academic_experiment`. Données synthétiques, projet
académique. Aucune performance commerciale réelle n'est revendiquée ; ces
résultats servent à l'évaluation académique et au benchmark de pipeline.

Reproduction : `python -m src.pricing_v4.train`
Artefacts : `models/v4/pricing/{cible}/`

---

## 1. Périmètre

| Élément | Valeur |
|---|---|
| Grain | une décision de tarification hebdomadaire par produit |
| Lignes | 11 799 décisions, 300 produits, 65 cohortes hebdomadaires |
| Cibles (évaluées séparément) | `units_sold_window_7j`, `revenue_window_xof_7j`, `margin_window_xof_7j` |
| Prix utilisé | toujours `prix_applique_xof` ; jamais `discount_proposed` |
| Découpage temporel | 6 fenêtres externes (dernières cohortes hebdomadaires), entraînement recalculé sur tout l'historique antérieur à chaque fenêtre |
| Regroupement | produit (bootstrap, permutation, biais persistant par produit) |

## 2. Confusion structurelle — à lire avant les résultats

`treatment_group` (et donc `discount_proposed`), `classe_abc` et
`cold_start_warmup` sont des **attributs fixes par produit** sur toute la
durée de l'expérience (vérifié : 300/300 produits n'ont qu'une seule valeur de
chacun). La remise n'est donc jamais observée à deux niveaux différents pour
un même produit : elle est confondue avec l'identité du produit. Un modèle qui
mémoriserait fortement l'identité produit peut donc paraître expliquer un
effet de remise sans avoir appris de relation causale généralisable — c'est
précisément la mise en garde de la consigne sur l'élasticité synthétique de
1,8. Cette confusion, et non un défaut de modélisation, explique une bonne
part des résultats qui suivent.

## 3. Résultats — `units_sold_window_7j`

| Modèle | WAPE macro | WAPE micro poolée | Biais | σ (inter-fenêtres) |
|---|---:|---:|---:|---:|
| **`baseline_mediane_produit`** | **0,1342** | **0,1334** | **+0,0054** | 0,0135 |
| `baseline_moyenne_produit` | 0,1411 | 0,1402 | +0,0098 | 0,0106 |
| `T_learner` | 0,1628 | 0,1618 | +0,0277 | 0,0087 |
| `Ensemble_contraint` | 0,1701 | 0,1692 | +0,0439 | 0,0083 |
| `Hurdle_zero_positif` | 0,1731 | 0,1724 | +0,0521 | 0,0098 |
| `LightGBM_Monotone` | 0,1824 | 0,1819 | +0,0519 | 0,0070 |
| `S_learner` / `LightGBM_Tweedie` | 0,1837 | 0,1827 | +0,0522 | 0,0089 |
| `CatBoost_Poisson` | 0,1840 | 0,1838 | +0,0605 | 0,0084 |
| `LightGBM_Poisson` | 0,2019 | 0,2012 | +0,0575 | 0,0079 |
| `LightGBM_L1` | 0,2063 | 0,2053 | +0,0651 | 0,0150 |
| `GLM_Poisson` | 0,3396 | 0,3397 | +0,0817 | 0,0090 |
| `GLM_Tweedie` | 0,3453 | 0,3454 | +0,0787 | 0,0091 |

**Aucun modèle ne bat la médiane par produit.** Garde-fous : 0 prix sous le
coût, 0 marge sous le plancher de 5 %, sur l'ensemble des 11 799 décisions.

### Diagnostic — récupération de l'effet synthétique attendu

| | Pente réelle (log-unités par point de remise) | Équivalent sur 100 points |
|---|---:|---:|
| Données réelles | 0,0170 | 1,70 |
| Meilleur modèle par WAPE (`baseline_mediane_produit`) | 0,0118 | 1,18 |
| Référence du générateur | — | 1,80 |

La pente réelle (1,70) se rapproche de la référence du générateur (1,8), ce
qui confirme que l'effet de remise existe bel et bien dans les données. La
baseline retenue, qui ignore la remise à l'intérieur d'un même produit,
n'en récupère qu'une partie (1,18) — elle gagne sur la WAPE globale sans
pour autant mieux capter l'élasticité. **Ce diagnostic n'a pas servi à
sélectionner le modèle** : c'est une information complémentaire, jamais un
critère de promotion.

## 4. Résultats — `revenue_window_xof_7j`

| Modèle | WAPE macro | Biais |
|---|---:|---:|
| **`baseline_mediane_produit`** | **0,1299** | **+0,0020** |
| `baseline_moyenne_produit` | 0,1379 | +0,0074 |
| `T_learner` | 0,1385 | +0,0086 |
| `Ensemble_contraint` | 0,1439 | +0,0139 |
| `Hurdle_zero_positif` | 0,1479 | +0,0169 |
| `LightGBM_Monotone` / `S_learner` / `LightGBM_Tweedie` | 0,1493–0,1494 | +0,0162–0,0163 |
| `LightGBM_Poisson` | 0,1585 | +0,0166 |
| `LightGBM_L1` | 0,1596 | −0,0157 |
| `CatBoost_MAE` | 0,1868 | −0,0156 |
| `GLM_Poisson` / `GLM_Tweedie` | 0,2844 / 0,2940 | +0,0202 / +0,0181 |

Même conclusion : la médiane par produit domine toutes les alternatives.

## 5. Résultats — `margin_window_xof_7j`

| Modèle | WAPE macro | Biais |
|---|---:|---:|
| **`baseline_mediane_produit`** | **0,1305** | **+0,0004** |
| `baseline_moyenne_produit` | 0,1386 | +0,0044 |
| `T_learner` | 0,1406 | +0,0014 |
| `Ensemble_contraint` | 0,1469 | +0,0055 |
| `Hurdle_zero_positif` | 0,1510 | +0,0108 |
| `S_learner` / `LightGBM_Tweedie` / `LightGBM_Monotone` | 0,1542–0,1544 | +0,0044–0,0048 |
| `LightGBM_Poisson` | 0,1709 | +0,0133 |
| `LightGBM_L1` | 0,1955 | −0,0594 |
| `CatBoost_MAE` | 0,2557 | −0,0669 |
| `GLM_Poisson` / `GLM_Tweedie` | 0,3334 / 0,3495 | +0,0310 / +0,0329 |

## 6. Un bogue trouvé et corrigé pendant l'expérience — CatBoost

Le premier passage de `CatBoost` en perte Poisson sur `revenue_window_xof_7j`
et `margin_window_xof_7j` produisait une WAPE de 1,0000 et un biais proche de
−1 (prédictions quasiment nulles) : la perte Poisson de CatBoost n'est pas
adaptée à des cibles monétaires à cette échelle (jusqu'à plusieurs millions de
XOF) et y dégénère silencieusement. Correction : perte Poisson réservée à
`units_sold_window_7j` (cible entière, faible échelle), perte MAE pour les
deux cibles monétaires — d'où `CatBoost_Poisson` / `CatBoost_MAE` selon la
cible dans les tableaux ci-dessus. Après correction, CatBoost produit des
résultats du bon ordre de grandeur, bien qu'il ne batte pas les baselines.

## 7. Pourquoi la médiane par produit gagne — lecture honnête

Ce n'est pas un artefact de méthode : c'est la conséquence directe de la
confusion structurelle décrite en §2. Remise, classe ABC et statut cold-start
étant fixes par produit, la quasi-totalité du signal prévisible sur une
semaine donnée est déjà contenue dans « quel est ce produit » — une baseline
par produit le capture directement et sans bruit. Les modèles à apprentissage
automatique, en ajoutant des variables qui varient dans le temps (historique
de ventes, vues pré-décision, calendrier) sans qu'aucune de ces variables ne
porte de signal hebdomadaire réellement prévisible dans ce générateur
synthétique, n'apprennent que du bruit supplémentaire et dégradent la WAPE.

## 8. Décision finale et garde-fous

**Aucun modèle n'est promu, sur aucune des trois cibles.** La baseline
`baseline_mediane_produit` est conservée comme référence. Sur les trois
cibles : biais absolu ≤ 3 % (respecté par la baseline retenue), aucune marge
négative, aucune remise sous le coût, stabilité correcte entre fenêtres
(écart-type de la WAPE ≤ 0,02 pour la baseline retenue sur les trois cibles),
reproductible (graine fixe 42, mêmes hyperparamètres sur toutes les fenêtres).

Le détail complet (bootstrap produit, p-values brutes et corrigées Holm,
métriques par segment catégorie/classe ABC/groupe de traitement, temps
d'entraînement, mémoire) est dans
`models/v4/pricing/{cible}/metadata.json` et
`reports/v4_training/03_model_comparison_pricing.csv`.
