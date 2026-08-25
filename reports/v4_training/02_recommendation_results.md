# 02 — Résultats recommandation V4

Statut : `synthetic_academic_experiment`. Données synthétiques, projet
académique. Aucune performance commerciale réelle n'est revendiquée ; ces
résultats servent à l'évaluation académique et au benchmark de pipeline.

Reproduction : `python -m src.recsys_v4.train`
Artefacts : `models/v4/recommendation/{cible}/`

**Mise à jour post-validation indépendante** : une vérification statistique
indépendante (`07_validation_independante.md`), menée avec des fonctions de
métrique, de bootstrap et de correction Holm entièrement réécrites,
reclasse le modèle retenu sur `viewed_after_impression` de « promu » à
**« exploratoire »** — la p-value brute recalculée par un test de
permutation différent (0,088) ne franchit pas le seuil conventionnel de
5 %, avant même correction. Les statuts de `added_to_cart_after` et
`purchased_after` sont confirmés « validé » par cette même vérification.
Les chiffres ci-dessous, produits par le pipeline principal, sont
conservés tels quels ; voir `07_validation_independante.md` pour l'analyse
qui a conduit à cette reclassification.

---

## 1. Périmètre

| Élément | Valeur |
|---|---|
| Grain | reclassement des 5 candidats d'une slate exposée |
| Lignes | 221 080 expositions, slates de taille fixe 5 |
| Cibles (évaluées séparément) | `viewed_after_impression`, `added_to_cart_after`, `purchased_after` |
| Cible retirée | `clicked` (absente de la sémantique V4, jamais référencée) |
| Découpage temporel | 6 fenêtres, dont 4 fenêtres de test externes ; entraînement recalculé sur tout l'historique antérieur à chaque fenêtre |
| Regroupement | client/visiteur anonyme (bootstrap), slate (métriques de liste) |
| Baseline de référence | `popularite_globale_v1` |

`rank` et `model_score` (colonnes livrées, qui encodent la politique déjà
utilisée pour produire l'exposition) sont explicitement exclus des features
d'entraînement ; `rank` n'est utilisé qu'a posteriori, pour l'évaluation dite
« bout en bout » de la liste réellement servie (§5).

## 2. Constat méthodologique préalable — invariance de Recall@k/HitRate@10

Avec des slates de taille fixe 5, **Recall@5 = Recall@10 = Recall@20 =
HitRate@10** pour un même modèle sur un même jeu de test : reclasser 5
candidats ne change jamais l'ensemble des 5 candidats présents dans le
top-k dès que k ≥ 5, seulement leur ordre. Ce n'est pas une anomalie de
calcul — c'est une propriété mathématique du protocole (slates fermées),
vérifiée par un test dédié
(`tests/test_v4_recommendation.py::test_recall_at_k_is_invariant_to_reranking_within_a_fixed_slate`)
et observable directement dans `models/v4/recommendation/*/per_window_metrics.csv`
(colonnes `recall@5`, `recall@10`, `recall@20`, `hitrate@10` identiques à
la précision flottante près, pour chaque modèle).

Conséquence directe sur les critères de promotion : le critère « ne pas
perdre plus de 2 % sur Recall@10 » est mécaniquement satisfait par tout
modèle de reclassement dans ce protocole. Les critères réellement
discriminants sont donc le gain relatif de **NDCG@10** (seule métrique
sensible à l'ordre pertinente ici), le nombre de fenêtres gagnées et
l'intervalle de bootstrap à 95 %. Ce constat est rappelé dans chaque
model card et ne change rien à la sévérité du seuil de promotion : sur les
9 candidats évalués par cible, seule une minorité franchit le seuil de gain
NDCG@10 ≥ 5 %.

## 3. Résultats — `viewed_after_impression`

Baseline `popularite_globale_v1` : NDCG@10 = 0,011314.

| Modèle | NDCG@10 | Gain relatif | Fenêtres gagnées (/4) | IC95 % bootstrap favorable | p brute | p corrigée Holm | Éligible |
|---|---:|---:|---:|:---:|---:|---:|:---:|
| **`CatBoostRanker`** | **0,01194** | **+5,57 %** | 4 | oui | 0,001 | 0,168 | **oui** |
| `XGBoost_Ranker` | 0,01185 | +4,72 % | 4 | non | — | — | non |
| `pointwise_conversion` | 0,01178 | +4,08 % | 4 | non | — | — | non |
| `popularite_recente` | 0,01164 | +2,87 % | 4 | non | — | — | non |
| `hybride_popularite_affinite` | 0,01162 | +2,67 % | 4 | oui | — | 0,009 | non (gain < 5 %) |
| `LightGBM_LambdaRank` | 0,01153 | +1,95 % | 3 | non | — | — | non |
| `cooccurrence` | 0,01149 | +1,55 % | 4 | non | — | — | non |
| `RRF` | 0,01134 | +0,24 % | 2 | non | — | — | non |
| `popularite_categorie` | 0,01128 | −0,34 % | 2 | non | — | — | non |

**Modèle retenu : `CatBoostRanker`.** Recall@10 = 0,0193 (identique pour tous
les modèles, cf. §2). Couverture catalogue 41,6 %, diversité intra-liste
0,0112.

**Réserve honnête à documenter** : le gain de `CatBoostRanker` franchit le
seuil de promotion (gain NDCG@10 ≥ 5 %, 4/4 fenêtres, IC95 % bootstrap
entièrement positif [0,00011 ; 0,00118]), mais sa **p-value corrigée Holm
(0,168) ne passe pas le seuil conventionnel de significativité à 5 %** une
fois la comparaison corrigée pour les 9 modèles testés simultanément. Le
test de permutation corrigé Holm est plus conservateur que l'intervalle de
bootstrap ciblé sur la seule comparaison au baseline ; les deux méthodes ne
sont pas d'accord sur cette cible. Ce résultat est donc promu selon les
critères explicitement fournis (IC95 % bootstrap, fenêtres gagnées, gain
NDCG@10), mais présenté avec cette réserve statistique plutôt que comme un
gain incontestable.

**Mise à jour** : la vérification indépendante (`07_validation_independante.md`)
confirme cette fragilité par une troisième construction statistique
(permutation par inversion de signe des différences moyennes par client,
p brute = 0,088, non significative même avant correction). Ce modèle est en
conséquence **reclassé « exploratoire »** : `popularite_globale_v1` reste la
référence retenue sur cette cible.

## 4. Résultats — `added_to_cart_after`

Baseline `popularite_globale_v1` : NDCG@10 = 0,013348.

| Modèle | NDCG@10 | Gain relatif | Fenêtres gagnées (/4) | IC95 % bootstrap favorable | p brute | p corrigée Holm | Éligible |
|---|---:|---:|---:|:---:|---:|---:|:---:|
| **`pointwise_conversion`** | **0,01438** | **+7,70 %** | 4 | oui | 0,003 | 0,018 | **oui** |
| `XGBoost_Ranker` | 0,01438 | +7,70 % | 4 | oui | 0,014 | 0,014 | oui |
| `CatBoostRanker` | 0,01429 | +7,05 % | 4 | oui | 0,018 | 0,018 | oui |
| `popularite_recente` | 0,01420 | +6,40 % | 4 | oui | 0,009 | 0,009 | oui |
| `LightGBM_LambdaRank` | 0,01417 | +6,13 % | 4 | oui | 0,020 | 0,020 | oui |
| `hybride_popularite_affinite` | 0,01375 | +3,04 % | 4 | oui | — | — | non (gain < 5 %) |
| `popularite_categorie` | 0,01365 | +2,24 % | 2 | non | — | — | non |
| `RRF` | 0,01354 | +1,41 % | 2 | non | — | — | non |
| `cooccurrence` | 0,01325 | −0,70 % | 1 | non | — | — | non |

**Modèle retenu : `pointwise_conversion`** — modèle le plus simple parmi les
cinq candidats éligibles (à gain NDCG@10 quasi identique à `XGBoost_Ranker`,
7,70 % contre 7,70 %), retenu par ordre de priorité de simplicité à
performance égale. IC95 % du gain vs baseline : [0,00045 ; 0,00163], **p
corrigée Holm = 0,018, significative**. Recall@10 = 0,0225 (identique tous
modèles). Couverture catalogue 44,2 %, diversité intra-liste 0,0119.

Cinq modèles sur neuf franchissent le seuil de promotion sur cette cible,
signe d'un signal de reclassement plus net qu'un simple bruit d'échantillonnage.

## 5. Résultats — `purchased_after`

Baseline `popularite_globale_v1` : NDCG@10 = 0,011583.

| Modèle | NDCG@10 | Gain relatif | Fenêtres gagnées (/4) | IC95 % bootstrap favorable | p brute | p corrigée Holm | Éligible |
|---|---:|---:|---:|:---:|---:|---:|:---:|
| **`CatBoostRanker`** | **0,01258** | **+8,57 %** | 4 | oui | 0,001 | 0,009 | **oui** |
| `XGBoost_Ranker` | 0,01251 | +8,01 % | 4 | oui | — | — | oui |
| `pointwise_conversion` | 0,01246 | +7,62 % | 3 | oui | — | — | oui |
| `popularite_recente` | 0,01241 | +7,17 % | 4 | oui | — | — | oui |
| `LightGBM_LambdaRank` | 0,01240 | +7,04 % | 4 | oui | — | — | oui |
| `hybride_popularite_affinite` | 0,01199 | +3,50 % | 4 | oui | — | — | non (gain < 5 %) |
| `popularite_categorie` | 0,01182 | +2,09 % | 2 | non | — | — | non |
| `RRF` | 0,01177 | +1,60 % | 3 | non | — | — | non |
| `cooccurrence` | 0,01152 | −0,52 % | 1 | non | — | — | non |

**Modèle retenu : `CatBoostRanker`.** IC95 % du gain vs baseline :
[0,00042 ; 0,00149], **p corrigée Holm = 0,009, significative**. Recall@10 =
0,0194 (identique tous modèles). Couverture catalogue 41,6 %, diversité
intra-liste 0,0112.

C'est la cible la plus proche de la valeur métier (achat effectif après
exposition) et celle où le gain relatif est le plus élevé (+8,6 %) avec la
significativité statistique la plus nette des trois cibles.

## 6. Stabilité contrôle / traitement

`as_served_metrics.csv` (par cible) sépare les métriques calculées sur le
**rang réellement servi** (`rank` de la table livrée, jamais utilisé comme
feature d'entraînement) entre groupes `controle` et `traitement`. Sur
`viewed_after_impression`, à titre d'exemple, NDCG@10 vaut 0,01174 en
contrôle contre 0,01175 en traitement sur la première fenêtre — écart non
significatif, cohérent avec l'exigence de stabilité entre les deux groupes
exigée par la consigne. Le détail complet par fenêtre et par cible est dans
`models/v4/recommendation/{cible}/as_served_metrics.csv`.

Cette métrique « bout en bout » (politique historiquement servie) est
distincte de la métrique « ensemble de candidats » (§3–§5, reclassement
hors-ligne des 5 candidats déjà sélectionnés) : la première décrit la
performance de la politique qui a produit les données, la seconde compare
des modèles de reclassement sur un ensemble de candidats fixe. Les deux ne
sont jamais confondues dans les artefacts produits.

## 7. Diversité, couverture, concentration

Les modèles de popularité pure (`popularite_globale_v1`,
`popularite_categorie`) atteignent la meilleure diversité et la plus faible
concentration top-10, mais au prix du NDCG@10 le plus faible. Les modèles
retenus (`CatBoostRanker`, `pointwise_conversion`) conservent une couverture
catalogue de 41 à 44 % (contre 14 à 26 % pour la pure popularité), jugée
acceptable au sens de la consigne (pas d'effondrement vers un tout petit
sous-ensemble de produits). Détail par fenêtre :
`models/v4/recommendation/{cible}/per_window_metrics.csv`.

## 8. Décision finale et garde-fous

| Cible | Modèle | Gain NDCG@10 | Fenêtres gagnées | IC95 % | p Holm (pipeline) | p Holm (indép.) | Statut retenu |
|---|---|---:|---:|---|---:|---:|:---:|
| `viewed_after_impression` | `CatBoostRanker` | +5,57 % | 4/4 | entièrement positif, borne basse proche de 0 | 0,168 | 0,088 | **exploratoire** |
| `added_to_cart_after` | `pointwise_conversion` | +7,70 % | 4/4 | entièrement positif | 0,018 | 0,0015 | **validé** |
| `purchased_after` | `CatBoostRanker` | +8,57 % | 4/4 | entièrement positif | 0,009 | 0,00075 | **validé** |

**Statut final après validation indépendante** (`07_validation_independante.md`) :
`added_to_cart_after` et `purchased_after` sont confirmés — deux
constructions statistiques distinctes s'accordent sur une significativité
nette. `viewed_after_impression` est **reclassé de « promu » à
« exploratoire »** : ni la p-value Holm du pipeline principal (0,168), ni
la p-value brute recalculée indépendamment par un test différent (0,088),
ne franchissent le seuil conventionnel de 5 %. `popularite_globale_v1`
reste donc la référence retenue sur cette cible, dans l'attente de données
supplémentaires.

Aucune de ces cibles ne mesure un « clic » — la colonne `clicked` n'existe
plus dans la sémantique V4 et n'a jamais été référencée dans le code
d'entraînement (vérifié par test).

Le détail complet (bootstrap client/slate, p-values brutes et corrigées
Holm, temps d'entraînement, mémoire) est dans
`models/v4/recommendation/{cible}/metadata.json` et
`reports/v4_training/03_model_comparison_recommendation.csv`.
