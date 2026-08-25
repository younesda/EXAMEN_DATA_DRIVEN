# 11 — Clôture Recommandation V2

_Généré le 2026-08-15T13:46:01.610462+00:00. Branche `feature/v2-model-improvements`, non fusionnée._

## 1. Statut officiel

```
recommendation_primary_model: v1_popularite_globale
recommendation_v2_validated: false
R1_status: experiment_not_retained
R1_reason: no_improvement_over_v1
R2_status: exploratory_diversity_challenger
R2_primary_model_eligible: false
R2_reason: coverage_and_diversity_improved_but_relevance_loss_exceeds_threshold
R3_status: experiment_not_retained
R3_reason: relevance_not_improved
R4_status: not_launched
R4_reason: no_personalization_signal_in_R3
```

## 2. Tableau de décision

| Modèle | Recall@10 | NDCG@10 | Couverture | Diversité | Clients personnalisés | Statut |
|---|---:|---:|---:|---:|---:|---|
| V1 popularité globale | 0.0759 | 0.0441 | 0.0542 | 0.3333 | 0 | **Référence — modèle principal** |
| R1 popularité régularisée | 0.0750 | 0.0437 | 0.0508 | 0.3116 | 0 | `experiment_not_retained` |
| R2 reranking de diversité | 0.0720 | 0.0419 | 0.0892 | 0.4226 | 0 | `exploratory_diversity_challenger` |
| R3 personnalisation catégorie (pilote F1-F2) | 0.0656 | 0.0394 | 0.1483 | n/a | 99.9% | `experiment_not_retained` |

_R3 est mesuré sur le pilote (fenêtres 1-2) et n'est donc pas strictement comparable aux moyennes 4 fenêtres de V1/R1/R2 ; sa comparaison valide figure au rapport 10, contre une V1 recalculée sur les deux mêmes fenêtres._

## 3. Pourquoi R3 échoue — et pourquoi cela règle aussi le sort de R4

R3 échoue la porte sur la pertinence : NDCG@10 −1,29 % et Recall@10 −2,09 % face à une V1 recalculée sur les mêmes fenêtres. Mais le point décisif est ailleurs :

**99.9% des clients passent les seuils d'éligibilité.** Les seuils fixés a priori (≥3 achats, ≥2 catégories, ≥60 % dans les catégories dominantes) ne filtrent presque personne, parce que le client médian a environ 17 achats répartis sur 6 catégories. R3 revient donc à **personnaliser quasiment tout le monde** — et cela dégrade quand même la pertinence.

Sur le sous-groupe personnalisable lui-même — le test qui compte — R3 est également en retrait (−1,36 % et −1,22 % de NDCG@10 sur les deux fenêtres). **Il n'y a pas de signal de personnalisation à exploiter**, même là où les conditions sont les plus favorables.

**Conséquence directe pour R4** : R4 devait router les clients « à historique suffisant » vers un modèle personnalisé et les autres vers la popularité. Or il n'existe pas de tel clivage ici — 99.9% des clients sont éligibles, il n'y a pas de sous-groupe à router. Et sur ce quasi-tout, la personnalisation légère ne produit aucun gain. Lancer un collaboratif plus lourd sur la même population, avec la même sparsité (~0,96) et le même volume d'historique, reviendrait à traiter un problème de sophistication alors que le problème est l'absence de signal. **R4 : `not_launched`, `no_personalization_signal_in_R3`.**

## 4. Le seul acquis réel : la couverture

| Modèle | Couverture | vs V1 | Concentration top-10 produits |
|---|---:|---:|---:|
| V1 | 0.0542 | — | — |
| R2 | 0.0892 | +64,6 % | 0.5353 (contre 0.9250 pour R1) |
| R3 (pilote) | 0.1483 | +161,8 % | — |

Deux candidats indépendants montrent donc que **la concentration extrême de la V1 est corrigeable** : R2 fait passer la part des recommandations captée par les 10 produits les plus recommandés de 92,5 % à 53,5 %, et R3 triple la couverture catalogue. Dans les deux cas, le prix payé est une perte de pertinence — modérée, mais réelle, et supérieure aux tolérances fixées.

C'est un résultat exploitable pour le métier : il existe un levier de diversité, à condition d'accepter explicitement un arbitrage pertinence/découverte. **R2 est conservé à ce titre** comme scénario exploratoire pour un bloc « Découvrir d'autres produits », en complément — jamais en remplacement — de la liste principale.

## 5. Clôture honnête

- **Modèle principal inchangé** : popularité globale (V1).
- **Aucune personnalisation validée** : R1, R3 rejetés, R4 non lancé faute de signal.
- **R2 conservé comme scénario exploratoire de diversité**, non éligible comme moteur principal, et **sa pénalité n'a pas été réglée rétrospectivement** pour le faire passer.
- **Données supplémentaires nécessaires** pour espérer une personnalisation utile : `order_id` (paniers réels), `session_id` et `event_timestamp` (séquences), et davantage d'interactions par client.

Ce résultat est cohérent avec les trois modules du projet : sur ce jeu de données (300 produits, ~18 mois, forte intermittence, prix catalogue fixe), **le signal fin — individuel, séquentiel ou causal — n'est pas exploitable**. Les baselines simples restent les meilleures réponses honnêtes.

## 6. Garanties

- 4 fenêtres V1, mêmes clients évaluables, mêmes définitions de métriques (module V1 importé sans modification).
- Profils et règles appris **uniquement sur les fenêtres antérieures**.
- 21 tests dédiés R1/R2 ajoutés (le total passe de 180 à 201) — ils manquaient réellement.
- Aucun artefact V1 modifié, aucune fusion dans `main`, aucune écriture Supabase, aucun déploiement.
- **Pricing V2 non démarré.**
