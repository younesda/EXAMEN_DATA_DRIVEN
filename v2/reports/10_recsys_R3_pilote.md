# 10 — Candidat R3 : personnalisation par catégorie (pilote fenêtres 1-2)

_Généré le 2026-08-15T13:35:05.133400+00:00._

**Statut : `experiment_not_retained` — raison : `relevance_not_improved`**

## 1. Seuils d'éligibilité (fixés avant l'évaluation)

- Minimum 3 achats historiques
- Minimum 2 catégories observées
- Au moins 60% des achats dans les catégories dominantes

Tout client ne remplissant pas ces conditions reçoit **automatiquement la liste V1**.

## 2. Population personnalisable

| Fenêtre | Clients évaluables | Personnalisés | Part | Achats moyens (éligibles) | Catégories moyennes | Sparsité |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,396 | 4,388 | 99.8% | 10.2 | 5.5 | 0.9670 |
| 2 | 4,531 | 4,529 | 100.0% | 12.3 | 6.0 | 0.9603 |

Raisons de non-éligibilité :

- Fenêtre 1 : {'moins_de_3_achats': 8, 'moins_de_2_categories': 1}
- Fenêtre 2 : {'moins_de_3_achats': 2}

## 3. Résultats du pilote

| Métrique | V1 (recalculée sur F1-F2) | R3 | Écart |
|---|---:|---:|---:|
| Recall@10 | 0.0670 | 0.0656 | -2.09% |
| NDCG@10 | 0.0399 | 0.0394 | -1.29% |
| Recall@5 | 0.0361 | 0.0361 | +0.00% |
| NDCG@5 | 0.0272 | 0.0272 | +0.00% |
| Couverture catalogue | 0.0567 | 0.1483 | +161.76% |

## 4. Porte stricte

| Critère | V1 | R3 | Satisfait ? |
|---|---:|---:|:---:|
| `ndcg_at_10_au_moins_egal_v1` | 0.0399 | 0.0394 | ❌ |
| `recall_at_10_au_moins_egal_v1` | 0.0670 | 0.0656 | ❌ |
| `couverture_superieure_v1` | 0.0567 | 0.1483 | ✅ |
| `recul_peu_actifs_max_5pct` | seuil 0.0500 | -0.0000 | ✅ |

**Porte franchie : non**

## 5. Le test qui compte vraiment : le sous-groupe personnalisable

Comparer R3 à la V1 sur l'ensemble des clients dilue l'effet, puisque la majorité reçoit de toute façon la liste V1. La question utile est : **là où la personnalisation s'applique réellement, fait-elle mieux ?**

| Fenêtre | Clients personnalisés | NDCG@10 V1 | NDCG@10 R3 | Écart |
|---:|---:|---:|---:|---:|
| 1 | 4,388 | 0.0393 | 0.0388 | -1.36% |
| 2 | 4,529 | 0.0407 | 0.0402 | -1.22% |

**Signal de personnalisation sur le sous-groupe : NON**

## 6. Mix retenu par fenêtre (choisi sur les fenêtres antérieures)

| Fenêtre | Mix | Source | Fenêtres utilisées |
|---:|---|---|---|
| 1 | `MIX_7_3` | `defaut_aucune_fenetre_anterieure` | [] |
| 2 | `MIX_7_3` | `fenetres_anterieures` | [1] |

## 7. Contrôles durs

| Fenêtre | Doublons Top-10 | Produits inéligibles |
|---:|---:|---:|
| 1 | 0 | 0 |
| 2 | 0 | 0 |

## 8. Décision sur R4

**R4 : `not_launched` — raison : `no_personalization_signal_in_R3`**

R4 était un routage « clients avec historique suffisant → modèle personnalisé, autres → popularité globale ». Or R3 vient de tester exactement ce routage, avec une personnalisation légère — et il **n'apporte pas de signal** sur le sous-groupe qu'il cible. Lancer un collaboratif plus lourd sur la même population, avec la même sparsité et le même volume d'historique, n'a pas de fondement : le problème n'est pas la sophistication du modèle, c'est l'absence de signal exploitable dans les données disponibles.

- Durée : **21.28 s** · mémoire 298.4 Mo

## 9. Garanties

- Profils clients calculés **sur le train de chaque fenêtre uniquement**.
- Mix choisi **uniquement sur les fenêtres antérieures** (F1 utilise le mix par défaut).
- Repli V1 automatique pour tout client non éligible et pour le cold-start.
- Aucun artefact V1 modifié.
