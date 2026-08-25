# 07 — Validation indépendante avant décision finale

Statut : `synthetic_academic_experiment`. Ce document est un contrôle de
contre-expertise, distinct du pipeline d'entraînement : il réutilise
uniquement la construction canonique des jeux de données
(`build_dataset()`, identique pour tout consommateur des données) et les
fabriques de modèles déjà entraînées, mais **réimplémente entièrement, dans
un module séparé (`scripts/validate_v4_independent.py`), ses propres
fonctions de métrique, de bootstrap et de correction Holm** — sans importer
`src/pricing_v4/evaluate.py` ni `src/recsys_v4/evaluate.py`. Reproduction :
`python -m scripts.validate_v4_independent`. Détail chiffré complet :
`reports/v4_training/07_validation_independante.json`.

**Aucune décision de promotion n'est modifiée par ce seul document sans
lecture de la conclusion (§6) : un des trois modèles de recommandation
initialement retenus ne résiste pas à la vérification statistique
indépendante et ne doit pas être présenté comme validé.**

---

## 1. Le FAIL et les deux WARNING de `06_leakage_checks.json`

### 1.1 FAIL — `P-12 product_impressions varie-t-il avec la decision`

- **Fichier et règle** : `scripts/audit_v4.py`, lignes 63 à 70. Le contrôle
  regroupe les décisions par produit (`pricing.groupby("produit_key").product_impressions.nunique()`)
  et échoue si aucun produit ne présente plus d'une valeur distincte sur
  toute la période.
- **Nature du problème** : la colonne livrée `product_impressions` est un
  **total de période constant par produit** (0/300 produits avec une valeur
  qui varie selon la décision), et non un cumul pré-décision. Utilisée
  telle quelle comme feature, elle aurait fait fuiter, pour les décisions
  prises tôt dans la période, une information agrégée sur des semaines
  encore futures à la date de décision — une fuite temporelle directe.
- **Correction, vérifiée indépendamment, pas un contournement** :
  1. `product_impressions` figure dans `FORBIDDEN_ROOTS`
     (`src/pricing_v4/dataset.py`, ligne 36) : toute tentative de l'inclure
     dans la liste de features lève une erreur (`validate_no_forbidden_columns`).
     Elle est absente de `NUMERIC_FEATURES` — vérifié par lecture directe
     du code, pas seulement par le rapport d'audit.
  2. Elle est remplacée par des features reconstruites
     (`pre_decision_views`, `pre_decision_views_28d`, `pre_decision_carts_28d`)
     calculées par recherche du dernier événement web strictement antérieur
     à `decision_timestamp` (`_pre_decision_web_features`, recherche binaire
     `np.searchsorted`).
  3. **Recalcul indépendant** : `pre_decision_views` recalculé pour un
     échantillon de 400 décisions par un chemin de code entièrement
     différent (comptage direct par filtre booléen sur les événements web,
     sans recherche binaire) — **0 divergence sur 400**, et
     114/218 produits de l'échantillon présentent bien une valeur qui varie
     selon la décision (cohérent avec le constat 300/300 sur la totalité du
     jeu de données).
- **Conclusion** : le FAIL est **réellement corrigé**, pas seulement
  documenté ou contourné. La feature d'origine reste exclue par
  construction (test automatisé et garde-fou de code), et son remplacement
  est vérifié par une seconde implémentation indépendante donnant un
  résultat identique.

### 1.2 WARNING 1 — `P-02 une decision par produit et semaine`

- **Fichier et règle** : `scripts/audit_v4.py`, lignes 42-45. Regroupe les
  décisions par (`produit_key`, numéro de semaine ISO calendaire) et signale
  un maximum de 2 décisions pour un même couple.
- **Vérification indépendante** : 1118 couples (produit, semaine ISO) sont
  concernés. Pour chacun d'entre eux, les deux `decision_id` sont distincts,
  et surtout leurs `experiment_week_index` (la semaine réelle de
  l'expérience, utilisée pour le découpage train/test) sont **toujours
  distincts et espacés d'exactement 52 semaines expérimentales**, avec des
  `decision_timestamp` espacés de 364 jours exacts (exemple :
  `PRD000002`, semaine ISO 21 → décisions du 2025-05-19 et du 2026-05-18,
  `experiment_week_index` 2 et 54).
- **Explication** : l'expérience dure 65 semaines, soit plus qu'une année
  calendaire (52-53 semaines ISO). Le numéro de semaine ISO se répète
  chaque année ; toute expérience de plus de 52 semaines produit donc
  mécaniquement des couples (produit, semaine ISO) apparaissant deux fois,
  sans qu'il s'agisse d'un doublon de décision.
- **Preuve qu'il ne s'agit pas d'une duplication** : un contrôle
  indépendant et distinct, sur la clé réellement utilisée pour le
  découpage temporel (`produit_key`, `experiment_week_index`), ne trouve
  **aucun doublon** (0/11 799, §3). Le WARNING P-02 porte sur un artefact du
  calendrier ISO, pas sur la granularité utilisée par les modèles.
- **Conclusion** : `blocks_scope` est `null` dans le rapport d'origine, à
  juste titre — confirmé indépendamment. Ce n'est ni une fuite, ni un
  problème de découpage train/test, ni un problème de labels.

### 1.3 WARNING 2 — `R-19 semantique de product_exposure_probability`

- **Fichier et règle** : `scripts/audit_v4.py`, lignes 169-181. Constate que
  la somme des scores par slate vaut ~1 (softmax théorique) mais que la
  sélection réelle des 5 candidats est déterministe (Top-5 par score, pas un
  tirage).
- **Nature** : ce n'est pas une anomalie de données mais un **avertissement
  de sémantique**, correctement traité en amont par une décision de
  conception : `product_exposure_probability` est absente de
  `ALL_FEATURES` (`src/recsys_v4/dataset.py`), un indicateur
  `exposure_probability_status = "deterministic_top_k"` est ajouté au jeu
  de données, et un test dédié (`test_product_exposure_probability_never_used_as_feature`)
  vérifie qu'elle n'est jamais utilisée comme poids IPS.
- **Conclusion** : aucune fuite, aucun impact sur le découpage train/test ou
  les labels. Le statut `WARNING` documente une limite de sémantique, pas un
  défaut corrigible par plus de données.

### 1.4 Application de la règle de blocage

Aucun des trois signalements ne concerne, une fois vérifié en détail, une
fuite non corrigée, un problème de découpage train/test ou un problème de
labels : le FAIL a une correction structurelle vérifiée deux fois
indépendamment, et les deux WARNING sont des artefacts de calendrier et de
sémantique déjà neutralisés par construction. **Rien dans cette section
n'interdit une promotion sur ce seul critère.** La décision finale reste
toutefois conditionnée par la vérification statistique indépendante des
gains eux-mêmes (§4-6).

---

## 2. Découpage temporel — vérification indépendante

Résultats complets : `07_validation_independante.json`, sections
`decoupage_temporel_pricing` et `decoupage_temporel_recommandation`.

### Pricing

- `experiment_week_index` croît strictement avec `decision_timestamp` :
  **confirmé** (les décisions plus tardives ont toujours un index de
  semaine supérieur ou égal).
- 6 semaines de test vérifiées une par une : pour chacune,
  `max(decision_timestamp)` du train **est strictement inférieur** à
  `min(decision_timestamp)` du test correspondant. **0 violation.**

### Recommandation

- Le découpage en fenêtres a été **recalculé de façon totalement
  indépendante** (nouvelle fonction, sans consulter le code de
  `assign_windows` avant de comparer les résultats) : les deux découpages
  sont **identiques**, ligne par ligne.
- 4 fenêtres de test vérifiées : `max(impression_timestamp)` du train
  strictement inférieur à `min(impression_timestamp)` du test. **0
  violation.**
- Aucune slate n'est répartie sur plus d'une fenêtre (0/44 216) : chaque
  exposition appartient sans ambiguïté à une seule fenêtre temporelle.
- **5852 clients/visiteurs sur 6990 apparaissent à la fois dans le train et
  dans le test** d'une même cible. Ce n'est pas, en soi, une fuite : chaque
  feature d'historique client est calculée strictement avant l'horodatage
  de la ligne elle-même, jamais avant l'horodatage de la fenêtre. Vérifié
  directement : `client_purchase_count_before` recalculé pour 400 lignes de
  test, par un chemin de code totalement différent (filtre pandas direct
  sur les dates, sans recherche binaire) — **0 divergence**. Un client
  actif à la fois tôt et tard dans l'expérience ne crée donc pas de fuite,
  parce que ses features au moment T ne voient jamais ce qui se passe après
  T, y compris quand T tombe dans une fenêtre de test.
- Aucun paramètre ni hyperparamètre n'est appris sur le test : chaque modèle
  est refitté depuis zéro sur `train = fenêtres strictement antérieures`
  avant d'être évalué sur `test = fenêtre courante`, à chaque itération,
  aussi bien dans le pipeline principal que dans cette vérification
  indépendante.

---

## 3. Doublons — vérification indépendante

- **Une seule ligne par exposition et produit** : 0 doublon sur
  (`slate_id`, `produit_key`).
- **Aucun doublon de slate** : les 44 216 slates ont toutes exactement 5
  candidats.
- **Aucune décision pricing dupliquée** sur la clé réellement utilisée pour
  le découpage temporel (`produit_key`, `experiment_week_index`) : 0/11 799.
  Le WARNING P-02 (§1.2) est un artefact du calendrier ISO, pas une
  duplication réelle — démontré ci-dessus par comparaison directe des
  `experiment_week_index`.
- **Aucune fuite indirecte de la cible dans les features de
  recommandation** : les trois cibles (`viewed_after_impression`,
  `added_to_cart_after`, `purchased_after`) ont été permutées aléatoirement
  sur l'ensemble du jeu de données ; les features restent, ligne pour
  ligne, strictement identiques après permutation — confirmé par une
  comparaison exacte (`DataFrame.equals`), pas un simple contrôle de
  corrélation.

---

## 4. Recalcul indépendant des métriques de recommandation

Popularité globale (référence), meilleur modèle `added_to_cart_after`
(`pointwise_conversion`) et meilleur modèle `purchased_after`
(`CatBoostRanker`) ont été **réentraînés fenêtre par fenêtre** avec le même
protocole que le pipeline principal (train strictement antérieur, refit à
chaque fenêtre), puis évalués avec des fonctions de métrique réécrites de
zéro (NDCG@10, MAP@10, MRR, Recall@10 par boucle Python explicite plutôt que
par vectorisation groupby-rank, couverture et diversité par indice de
Gini-Simpson plutôt que par la formule d'origine). Le modèle retenu sur
`viewed_after_impression` (`CatBoostRanker`) a également été recalculé, pour
compléter la vérification sur les trois cibles évaluées par la consigne
initiale.

| Cible | Modèle | NDCG@10 (indép.) | NDCG@10 (pipeline) | MAP@10 | MRR | Recall@10 | Couverture | Diversité |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `viewed_after_impression` | popularité globale | 0,011314 | 0,011314 | 0,008716 | 0,008714 | 0,019310 | 0,159 | 0,788 |
| `viewed_after_impression` | **CatBoostRanker** | 0,011944 | 0,011944 | 0,009542 | 0,009547 | 0,019310 | 0,416 | 0,896 |
| `added_to_cart_after` | popularité globale | 0,013348 | 0,013348 | 0,010368 | 0,010370 | 0,022515 | 0,159 | 0,788 |
| `added_to_cart_after` | **pointwise_conversion** | 0,014376 | 0,014383 | 0,011696 | 0,011736 | 0,022515 | 0,442 | 0,905 |
| `purchased_after` | popularité globale | 0,011583 | 0,011583 | 0,009031 | 0,009033 | 0,019422 | 0,159 | 0,788 |
| `purchased_after` | **CatBoostRanker** | 0,012575 | 0,012575 | 0,010310 | 0,010338 | 0,019422 | 0,416 | 0,905 |

Les valeurs NDCG@10 recalculées par un code entièrement distinct
concordent avec celles du pipeline principal à la cinquième décimale près
sur les trois cibles — l'implémentation d'origine n'est pas mise en défaut
par cette contre-expertise. Recall@10 reste, comme attendu et déjà
documenté, strictement identique entre la référence et le modèle candidat
sur chaque cible (slates fermées à 5 candidats, cf. `02_recommendation_results.md`).

---

## 5. Bootstrap par client, intervalles de confiance et correction Holm

Bootstrap (4000 tirages, regroupement par `identity_key` — client connu ou
visiteur anonyme) et test de permutation par inversion aléatoire du signe
des différences moyennes par client, **tous deux réimplémentés dans ce
script indépendant** (agrégation par `pd.factorize` + `np.add.at`, jamais
`np.bincount`, et rééchantillonnage par tirage direct des sommes par
groupe). Correction Holm appliquée sur la famille des **trois décisions de
promotion en cours de validation** (une par cible), et non sur la famille
des neuf candidats par cible comme dans le pipeline principal — un choix de
famille plus restreint et donc plus favorable, dont l'effet est discuté
ci-dessous.

| Cible | Modèle | Gain NDCG@10 | IC95% (indép.) | p brute (indép.) | p Holm (indép., famille=3) | p Holm (pipeline, famille=9) |
|---|---|---:|---|---:|---:|---:|
| `viewed_after_impression` | CatBoostRanker | +5,6 % | [0,00011 ; 0,00119] | **0,0882** | 0,0882 | 0,168 |
| `added_to_cart_after` | pointwise_conversion | +7,7 % | [0,00045 ; 0,00163] | 0,00075 | 0,0015 | 0,018 |
| `purchased_after` | CatBoostRanker | +8,6 % | [0,00044 ; 0,00150] | 0,00025 | 0,00075 | 0,009 |

**Constat central de cette validation indépendante** : pour
`viewed_after_impression`, la p-value brute recalculée par un test de
permutation différent (0,088) **ne passe déjà pas** le seuil conventionnel
de 5 % — avant même toute correction pour comparaisons multiples, et alors
même que la famille de correction retenue ici (3 comparaisons) est plus
favorable que celle du pipeline principal (9 comparaisons). L'intervalle de
bootstrap reste entièrement positif mais sa borne basse (0,00011) est très
proche de zéro — un gain fragile, cohérent entre les deux méthodes de test
mais qui ne franchit la barre de significativité dans aucune des deux
constructions statistiques essayées (permutation par échange de groupes
côté pipeline principal, permutation par inversion de signe par client
côté vérification indépendante).

Pour `added_to_cart_after` et `purchased_after`, les deux méthodes de test
— construites différemment — s'accordent sur une significativité nette
(p Holm indépendante ≤ 0,0015 dans les deux cas), confortant la robustesse
de ces deux gains.

---

## 6. Tableau de décision et statuts

| Cible | Modèle | Gain NDCG@10 | IC95% (indép.) | p brute (indép.) | p Holm (indép.) | Statut |
|---|---|---:|---|---:|---:|:---:|
| `viewed_after_impression` | CatBoostRanker | +5,6 % | entièrement positif, borne basse proche de 0 | 0,088 | 0,088 | **exploratoire** |
| `added_to_cart_after` | pointwise_conversion | +7,7 % | entièrement positif | 0,00075 | 0,0015 | **validé** |
| `purchased_after` | CatBoostRanker | +8,6 % | entièrement positif | 0,00025 | 0,00075 | **validé** |

**`viewed_after_impression` est reclassé de « promu » à « exploratoire ».**
Le gain observé est réel et reproductible (les deux implémentations
donnent la même estimation ponctuelle), mais ni le test de permutation
d'origine une fois corrigé pour 9 candidats (p = 0,168), ni le test de
permutation indépendant même non corrigé (p = 0,088), ne permettent de
l'affirmer statistiquement distinct du hasard au seuil conventionnel de
5 %. La recommandation est de **conserver `popularite_globale_v1` en
référence sur cette cible** dans l'attente de données supplémentaires (plus
de fenêtres de test, ou un plan de puissance dédié), plutôt que de
promouvoir `CatBoostRanker` sur la seule base d'un intervalle de bootstrap
tout juste positif.

`added_to_cart_after` et `purchased_after` conservent leur statut promu :
gain reproduit à l'identique par une implémentation indépendante des
métriques, significativité confirmée par deux constructions statistiques
différentes, garde-fous de couverture et de diversité respectés (0,42-0,44
contre 0,16 pour la popularité pure).

### Pricing

Aucun recalcul indépendant ne modifie la conclusion du pipeline principal :
`baseline_mediane_produit` reste la référence sur les trois cibles
(`units_sold_window_7j`, `revenue_window_xof_7j`, `margin_window_xof_7j`),
et **aucun modèle n'est promu**, faute de gain démontré face à cette
référence (cf. `01_pricing_results.md`, §8). Trois lectures distinctes,
jamais confondues, doivent être maintenues :

- **Prévision de volume** (`units_sold_window_7j`) : une estimation
  statistique du nombre d'unités vendues sur 7 jours, sans interprétation
  causale de l'effet de la remise.
- **Simulation de marge** (`revenue_window_xof_7j`, `margin_window_xof_7j`) :
  une projection comptable dérivée du volume prévu et du prix appliqué, pas
  une mesure indépendante d'un mécanisme économique.
- **Causalité** : aucune des deux lectures précédentes ne permet d'affirmer
  qu'une remise cause tel volume ou telle marge — la confusion structurelle
  entre remise et identité produit sur cette expérience synthétique
  (`01_pricing_results.md`, §2) interdit toute lecture causale, y compris
  pour un modèle qui afficherait une bonne WAPE.

---

## 7. Ce que cette validation ne couvre pas

- Elle ne rejoue pas l'extraction des données depuis Supabase (lecture
  seule, non modifiée) ni la construction des tables source.
- Elle ne remet pas en cause les 17 contrôles `PASS` de
  `06_leakage_checks.json`, qui ne présentaient aucune ambiguïté à
  vérifier.
- Le forecasting V2 n'a pas été touché, ni relu, ni réévalué.

## 8. Actions nécessitant une autorisation

Aucune n'a été effectuée : pas de `git push`, pas de fusion, pas de
déploiement, pas d'écriture Supabase. La reclassification de
`viewed_after_impression` en statut « exploratoire » est une conclusion
d'analyse, pas une action sur un système externe.
