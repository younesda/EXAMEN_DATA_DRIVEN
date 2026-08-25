# 04 — Décision finale V4

Statut : `synthetic_academic_experiment`. Données synthétiques, projet
académique. Aucune performance commerciale réelle n'est revendiquée ; ces
résultats servent à l'évaluation académique et au benchmark de pipeline.

Branche : `v4/pricing-recommendation-training`.
Aucun push, aucune fusion, aucun déploiement, aucune écriture Supabase.
Le forecasting V2 n'a pas été touché : `LightGBM_direct_per_horizon` reste le
modèle de planification 30 jours validé, inchangé.

---

## 1. Décision — pricing

**Aucun modèle n'est promu.** Sur les trois cibles évaluées séparément
(`units_sold_window_7j`, `revenue_window_xof_7j`, `margin_window_xof_7j`), la
baseline `baseline_mediane_produit` obtient la meilleure WAPE et reste la
référence.

| Cible | Meilleur candidat non-baseline | WAPE macro candidat | WAPE macro baseline retenue | Gain |
|---|---|---:|---:|---:|
| `units_sold_window_7j` | `T_learner` | 0,1628 | 0,1342 | **négatif** (−21,3 %) |
| `revenue_window_xof_7j` | `T_learner` | 0,1385 | 0,1299 | **négatif** (−6,6 %) |
| `margin_window_xof_7j` | `T_learner` | 0,1406 | 0,1305 | **négatif** (−7,7 %) |

Raison structurelle, pas un défaut de méthode : la remise, la classe ABC et le
statut cold-start sont des attributs fixes par produit sur toute la durée de
l'expérience (aucune variation intra-produit). La quasi-totalité du signal
prévisible tient donc à l'identité du produit, qu'une baseline par produit
capture directement. Détail complet : `reports/v4_training/01_pricing_results.md`.

Garde-fous vérifiés sur les 11 799 décisions : 0 marge négative, 0 remise sous
le coût, biais absolu de la baseline retenue ≤ 1 % sur les trois cibles.

Trois lectures distinctes, jamais confondues : une **prévision de volume**
(`units_sold_window_7j`, estimation statistique sans interprétation
causale), une **simulation de marge** (`revenue_window_xof_7j`,
`margin_window_xof_7j`, projection comptable dérivée du volume prévu et du
prix appliqué) et l'absence de toute lecture **causale** — la confusion
structurelle entre remise et identité produit sur cette expérience
synthétique interdit d'attribuer un volume ou une marge prévus à un effet
causal de la remise, y compris pour un modèle qui afficherait une bonne
WAPE. Détail : `01_pricing_results.md`, §2 et §7.

## 2. Décision — recommandation

**Statut après validation indépendante** (`reports/v4_training/07_validation_independante.md`) :
un modèle est validé sur deux des trois cibles évaluées séparément contre
la baseline `popularite_globale_v1`. Le troisième est reclassé
« exploratoire » après contre-expertise statistique.

| Cible | Modèle | NDCG@10 | Gain relatif | Fenêtres gagnées (/4) | IC95 % bootstrap | p Holm (pipeline) | p Holm (indép.) | Statut |
|---|---|---:|---:|---:|---|---:|---:|:---:|
| `viewed_after_impression` | `CatBoostRanker` | 0,01194 | +5,57 % | 4 | entièrement positif, borne basse proche de 0 | 0,168 | 0,088 | **exploratoire** |
| `added_to_cart_after` | `pointwise_conversion` | 0,01438 | +7,70 % | 4 | entièrement positif | 0,018 | 0,0015 | **validé** |
| `purchased_after` | `CatBoostRanker` | 0,01258 | +8,57 % | 4 | entièrement positif | 0,009 | 0,00075 | **validé** |

Critères de promotion appliqués par le pipeline principal (tous requis) :
gain relatif NDCG@10 ≥ 5 %, perte de Recall@10 ≤ 2 %, intervalle de
bootstrap à 95 % entièrement positif, au moins 3 fenêtres gagnées sur 4,
couverture catalogue et diversité conservées (41–44 % pour les modèles
retenus, contre 14–26 % pour la pure popularité), stabilité
contrôle/traitement vérifiée sur la métrique servie (`as_served_metrics.csv`).
Les trois cibles franchissaient initialement ce seuil.

**Constat méthodologique transversal** : avec des slates fermées de 5
candidats, Recall@5/@10/@20 et HitRate@10 sont mathématiquement invariants
au reclassement (seuls NDCG@k et MRR/MAP@10 sont sensibles à l'ordre) —
vérifié par test dédié. Le critère de perte de Recall est donc satisfait
mécaniquement par tout modèle de reclassement dans ce protocole ; le NDCG@10
reste le seul discriminant réel.

**Validation indépendante et reclassification** : une contre-expertise
dédiée (`07_validation_independante.md`) a réentraîné les modèles retenus
avec le même protocole temporel, mais avec des fonctions de métrique, de
bootstrap et de correction Holm entièrement réécrites, indépendantes du
code d'évaluation du pipeline principal. Les estimations ponctuelles sont
confirmées à l'identique (NDCG@10 reproduit à la cinquième décimale près
sur les trois cibles). En revanche, un test de permutation construit
différemment (inversion de signe des différences moyennes par client)
donne, pour `viewed_after_impression`, une p-value brute de 0,088 — non
significative même avant toute correction, alors que le pipeline principal
affichait déjà une p-value corrigée Holm de 0,168 sur la même cible. Les
deux constructions statistiques, bien que différentes, s'accordent donc
pour dire que ce gain n'est pas démontré de façon robuste. **Ce modèle est
en conséquence reclassé « exploratoire »** et `popularite_globale_v1` reste
la référence retenue sur cette cible. `added_to_cart_after` et
`purchased_after` sont confirmés « validé » par les deux méthodes de test
(p Holm indépendante ≤ 0,0015 dans les deux cas). Détail complet, y compris
la liste intégrale des candidats et leur éligibilité par cible :
`reports/v4_training/02_recommendation_results.md` et
`reports/v4_training/07_validation_independante.md`.

## 3. Contrôles anti-fuite — synthèse

`reports/v4_training/06_leakage_checks.json` : 17 PASS, 2 WARNING, 1 FAIL.
Le seul échec (`product_impressions` constant par produit) est corrigé par
exclusion de la feature et reconstruction propre depuis les événements web
pré-décision — n'affecte pas le périmètre des modèles retenus. Correction
vérifiée une seconde fois, par un chemin de code totalement indépendant du
pipeline principal, avec 0 divergence sur un échantillon de 400 décisions
(`07_validation_independante.md`, §1.1).

Les deux `WARNING` (P-02, couples produit/semaine ISO ; R-19, sémantique de
`product_exposure_probability`) ont été vérifiés indépendamment et ne
concernent ni une fuite, ni le découpage train/test, ni les labels :
- P-02 est un artefact du calendrier ISO sur une expérience de 65 semaines
  (plus d'une année civile) — confirmé par l'absence totale de doublon sur
  la clé réellement utilisée pour le découpage temporel
  (`produit_key`, `experiment_week_index`), 0/11 799.
- R-19 est une décision de sémantique déjà neutralisée par construction
  (`product_exposure_probability` exclue des features, jamais utilisée
  comme poids IPS).

Décision de sémantique : `product_exposure_probability` est un softmax
théorique sur des slates réellement sélectionnées de façon déterministe
(Top-5 par score). `exposure_probability_status = "deterministic_top_k"` est
ajouté au jeu de données ; cette probabilité n'est jamais utilisée comme poids
IPS.

Découpage temporel et doublons vérifiés indépendamment (recommandation et
pricing) : 0 violation d'ordre temporel sur les 6 semaines de test pricing
et les 4 fenêtres de test recommandation, 0 slate répartie sur plusieurs
fenêtres, 0 doublon (slate, produit) ou (produit, semaine expérimentale),
features de recommandation prouvées invariantes à une permutation des
cibles. Détail : `07_validation_independante.md`, §2-3.

## 4. Artefacts

```
models/v4/manifests/raw_data_manifest.json
models/v4/pricing/{units_sold_window_7j,revenue_window_xof_7j,margin_window_xof_7j}/
models/v4/recommendation/{viewed_after_impression,added_to_cart_after,purchased_after}/
reports/v4_training/{00..07}*.{md,json,csv}
```

## 5. Échecs et limites assumés

- Contrôle `P-12` (product_impressions) : échec documenté, corrigé par
  reconstruction, sans impact sur le périmètre retenu — correction
  reconfirmée par une seconde implémentation indépendante.
- Aucun modèle pricing promu : conclusion honnête, pas un échec de pipeline —
  la confusion structurelle remise/produit rend la cible largement non
  différentiable des attributs statiques du produit sur cette expérience
  synthétique.
- CatBoost en perte Poisson dégénérait sur les cibles monétaires (WAPE=1,0) ;
  corrigé (perte MAE pour les cibles en XOF).
- Modèle de recommandation retenu sur `viewed_after_impression`
  (`CatBoostRanker`) reclassé « exploratoire » après validation indépendante :
  gain reproductible mais non significatif au seuil conventionnel de 5 %,
  quelle que soit la construction statistique retenue.

## 6. Actions nécessitant une autorisation

- Tout `git push` ou fusion vers une branche partagée.
- Toute écriture Supabase (la base reste strictement en lecture seule).
- Tout déploiement.
