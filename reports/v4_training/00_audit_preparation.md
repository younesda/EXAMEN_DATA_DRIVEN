# 00 — Préparation V4 : audit, volumétrie et décisions de sémantique

Ce document couvre l'étape 1 (préparation obligatoire) : vérification des
tables, contrôles automatiques, correction documentaire pricing et décision de
sémantique sur `product_exposure_probability`. Toutes les données concernées
sont **synthétiques, produites pour un usage académique** ; aucun résultat de
ce document ni des suivants ne doit être interprété comme une performance
commerciale réelle.

---

## 1. Identification des tables « V4 »

Les tables portant les noms `fact_experimentation_prix` et
`fact_exposition_reco` (sans suffixe de version dans le schéma Postgres) ont
été comparées à deux livraisons antérieures déjà auditées :

| Table | Livraison antérieure (1) | Livraison antérieure (2) | Livraison courante (« V4 ») |
|---|---:|---:|---:|
| pricing — lignes | 16 797 | 12 996 | **11 799** |
| pricing — colonnes | — | 17 | **21** |
| recommandation — lignes | 142 786 | 176 198 | **221 080** |
| recommandation — colonnes | — | 21 | **22** |

Le schéma courant introduit des colonnes absentes des livraisons précédentes
(`viewed_after_impression`, `added_to_cart_after`, `purchased_after`,
`product_exposure_probability`, `session_selection_probability`), ce qui
confirme qu'il s'agit d'une livraison distincte, désignée « V4 » dans ce
document conformément à la consigne reçue.

## 2. Volumétrie, schéma et SHA-256

Extraction en lecture seule vers une copie locale versionnée
(`data/raw/v4/`), jamais vers Supabase. Manifeste complet :
`models/v4/manifests/raw_data_manifest.json` (SHA-256, nombre de lignes,
colonnes, horodatage, commit).

| Table | Lignes | Statut |
|---|---:|---|
| `fact_experimentation_prix` | 11 799 | extraction fraîche |
| `fact_exposition_reco` | 221 080 | extraction fraîche |
| `dim_client`, `dim_date`, `dim_produit`, `dim_promotion`, `fact_evenements_web`, `fact_stock`, `fact_ventes` | 5 000 / 546 / 300 / 120 / 657 392 / 117 763 / 84 319 | réutilisées depuis le cache V2, volumétrie revérifiée identique à la base vivante |

Chaque table décisionnelle porte `statut_experience = "synthetic_academic_experiment"`
(pricing) ou est traitée comme telle par construction (recommandation) : ce
statut est repris tel quel dans tous les artefacts produits.

## 3. Contrôles automatiques V4

Exécutés par `scripts/audit_v4.py` sur l'instantané local (reproductible, sans
accès réseau). Résultat complet : `reports/v4_training/06_leakage_checks.json`.

**Bilan : 17 PASS, 2 WARNING, 1 FAIL.**

Le seul contrôle en échec (`P-12 product_impressions varie-t-il avec la
decision`) porte sur une colonne livrée, **constante par produit sur
l'ensemble de la période** (0/300 produits avec une valeur qui varie selon la
décision) : ce n'est pas un cumul pré-décision malgré son nom. Cet échec
**n'affecte pas le périmètre des modèles pricing**, parce que la colonne est
exclue des features et remplacée par une reconstruction propre
(`pre_decision_views`, `pre_decision_views_28d`), calculée à partir de
`fact_evenements_web` et vérifiée variable dans le temps pour chaque produit
(300/300 produits, test automatisé
`tests/test_v4_pricing.py::test_pre_decision_views_vary_with_decision_time`).

Tous les autres contrôles critiques passent, notamment :

- unicité des identifiants (décisions, recommandations) ;
- cohérence éligibilité/remise proposée/remise appliquée ;
- `stock_at_decision` égal au dernier stock strictement antérieur au jour de décision ;
- remise appliquée correctement reflétée dans le revenu observé (0 incohérence, contre 478 dans une livraison antérieure) ;
- aucun chevauchement décision/promotion (0, contre 986 dans une livraison antérieure) ;
- aucune exposition sur session bot, aucune impression hors des bornes réelles de session ;
- cohérence de séquence achat → panier (aucun achat sans passage par le panier) ;
- absence de sur-représentation évidente des sessions acheteuses parmi les sessions exposées (24,8 % du trafic web exposé à une slate).

## 4. Documentation pricing — entrée `fact_ventes`

La table `fact_ventes` est une entrée du contrôle de cohérence pricing : elle
sert à vérifier que la remise réellement appliquée (`discount_applied`) se
reflète dans le chiffre d'affaires observé, et à construire l'historique de
ventes confirmées antérieur à chaque décision (features `warmup_sales_*`).
Un export local versionné et horodaté est produit à cet effet :
`data/raw/v4/fact_ventes.csv` (empreinte SHA-256 dans
`models/v4/manifests/raw_data_manifest.json`).

## 5. Décision de sémantique — `product_exposure_probability`

Constat chiffré : la somme des `product_exposure_probability` par slate vaut
1,000 dans l'immense majorité des cas (softmax théorique sur les 5 candidats),
mais le score moyen décroît strictement avec le rang (rang 1 : 17 283 en
moyenne ; rang 5 : 17 267) — la sélection réelle des 5 candidats est donc
**déterministe** (Top-5 par score), pas un tirage selon ce softmax.

Conformément aux deux options proposées, la décision retenue est la seconde :
**les slates restent déterministes**, et le jeu de données analytique porte
explicitement `exposure_probability_status = "deterministic_top_k"`
(`src/recsys_v4/dataset.py`). `product_exposure_probability` est conservée
dans les artefacts à titre descriptif, mais **n'est jamais utilisée comme
poids IPS** ni dans aucune évaluation contrefactuelle — vérifié par test
(`tests/test_v4_recommendation.py::test_product_exposure_probability_never_used_as_feature`).

## 6. Commandes de reproduction

```bash
python -m scripts.extract_v4_data
python -m scripts.audit_v4
python -m src.pricing_v4.dataset
python -m src.recsys_v4.dataset
python -m src.pricing_v4.train
python -m src.recsys_v4.train
python -m pytest tests/test_v4_pricing.py tests/test_v4_recommendation.py -q
```
