# 12 — Clôture formelle Recommandation V2

_Généré le 2026-08-15T17:23:35.779398+00:00. Branche `feature/v2-model-improvements`, non fusionnée dans `main`._

## 1. Statut officiel

```
primary_model: v1_popularite_globale
recommendation_v2_validated: false
personalization_validated: false
diversity_challenger: R2
diversity_challenger_automatic_use: false
R4_status: not_launched
R4_reason: no_personalization_gain_under_predefined_routing_protocol
```

## 2. Conclusion corrigée sur R4

Les critères d'éligibilité prédéfinis classent presque tous les clients comme personnalisables (99,9 %) et R3 ne démontre aucun gain sur cette population. R4 n'est donc pas justifié dans ce protocole. **Cela ne prouve pas qu'aucun sous-groupe pertinent ne puisse exister** avec d'autres données ou d'autres critères validés ultérieurement.

Cette nuance est importante : le protocole a testé **un** jeu de critères de routage, fixé a priori (≥3 achats, ≥2 catégories, ≥60 % dans les catégories dominantes). Ces critères se sont révélés non discriminants sur ces données (99.9% des clients éligibles). Un autre jeu de critères, ou des données plus riches, pourrait faire apparaître un sous-groupe où la personnalisation apporte réellement quelque chose. **Ce qui est établi ici, c'est l'absence de gain dans ce protocole — pas une impossibilité générale.**

## 3. Résultats consolidés

| Modèle | Recall@10 | NDCG@10 | Couverture | Statut |
|---|---:|---:|---:|---|
| **V1 popularité globale** | 0.0759 | 0.0441 | 0.0542 | **Modèle principal** |
| R1 | 0.0750 | 0.0437 | 0.0508 | `experiment_not_retained` |
| R2 | 0.0720 | 0.0419 | 0.0892 | `exploratory_diversity_challenger` |
| R3 (pilote F1-F2) | 0.0656 | 0.0394 | 0.1483 | `experiment_not_retained` |

## 4. Usage autorisé de R2

Scénario métier expérimental « Découvrir d'autres produits » uniquement, avec test A/B OBLIGATOIRE avant toute utilisation réelle. Jamais en usage automatique, jamais en remplacement du moteur principal.

R2 réduit la concentration des recommandations sur les 10 produits les plus recommandés de **0.9250 à 0.5353** et augmente la couverture catalogue de +64,6 %. C'est un levier de diversité démontré — mais au prix d'une perte de pertinence supérieure aux tolérances fixées, d'où l'exigence d'un test A/B avant tout usage réel.

## 5. Contrôles de clôture

| Contrôle | Résultat |
|---|:---:|
| V1 intacte (22 artefacts verrouillés) | ✅ |
| Statuts R1-R4 conformes | ✅ |
| Aucun doublon ni produit inéligible | ✅ |
| Aucun candidat accepté (V1 reste principale) | ✅ |
| R2 non éligible à un usage automatique | ✅ |
| Manifeste SHA-256 complet | ✅ |
| Aucun secret | ✅ |
| Suite de tests | ✅ |

**TOUS LES CONTROLES PASSENT** — 201 passed in 30.21s (dont 21 tests R1/R2 ajoutés après constat d'un manque réel).

## 6. Données supplémentaires nécessaires

Pour espérer une personnalisation utile : `order_id`, `session_id`, `event_timestamp`, `davantage d'interactions par client`.

## 7. Livrables

- `v2/reports/12_recsys_v2_cloture.md` (ce document)
- `v2/models/recsys_v2_metadata.json`
- `v2/models/recsys_v2_manifest.json`
- `v2/evaluation/recsys_v2_final_checks.json`

Aucune écriture Supabase, aucun déploiement, aucune fusion dans `main`. Aucune expérience de recommandation supplémentaire n'a été relancée.
