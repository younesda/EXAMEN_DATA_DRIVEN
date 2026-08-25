# 09 — Recommandation V2 : candidats R1 et R2

_Généré le 2026-08-15T13:14:39.059256+00:00. Branche `feature/v2-model-improvements`. R3 et R4 non préparés._

## 1. Résultats moyens (4 fenêtres, périmètre découverte = celui de la V1)

| Modèle | Recall@5 | Recall@10 | NDCG@5 | NDCG@10 | Couverture catalogue | Couverture utilisateurs | Diversité@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **V1 popularité globale** | 0.0403 | 0.0759 | 0.0300 | 0.0441 | 0.0542 | 1.0000 | 0.3333 |
| R1 — découverte (rachats exclus) | 0.0382 | 0.0750 | 0.0292 | 0.0437 | 0.0508 | 1.0000 | 0.3116 |
| R2 — découverte (rachats exclus) | 0.0383 | 0.0720 | 0.0286 | 0.0419 | 0.0892 | 1.0000 | 0.4226 |

**Seuils V2** : Recall@10 ≥ 0.08 · NDCG@10 ≥ 0.047 · couverture ≥ 0.1 · ≥3/4 fenêtres battues.

## 2. Résultats par fenêtre

| Modèle | Fenêtre | α | Recall@10 | NDCG@10 | Couverture | Concentration top-10 produits |
|---|---:|---:|---:|---:|---:|---:|
| R1_decouverte | 0 | 0.50 | 0.1095 | 0.0598 | 0.0433 | 0.9775 |
| R1_decouverte | 1 | 0.00 | 0.0670 | 0.0395 | 0.0533 | 0.9253 |
| R1_decouverte | 2 | 0.00 | 0.0625 | 0.0382 | 0.0500 | 0.9166 |
| R1_decouverte | 3 | 0.25 | 0.0609 | 0.0373 | 0.0567 | 0.8806 |
| R2_decouverte | 0 | 0.50 | 0.1090 | 0.0595 | 0.0767 | 0.5782 |
| R2_decouverte | 1 | 0.00 | 0.0615 | 0.0363 | 0.1000 | 0.5078 |
| R2_decouverte | 2 | 0.00 | 0.0615 | 0.0375 | 0.0867 | 0.5304 |
| R2_decouverte | 3 | 0.25 | 0.0559 | 0.0345 | 0.0933 | 0.5248 |

_Rappel V1 par fenêtre (NDCG@10)_ : F0 = 0.0599, F1 = 0.0392, F2 = 0.0406, F3 = 0.0366

## 3. Choix de α (fenêtres antérieures uniquement)

| Fenêtre | α retenu | Source | Fenêtres utilisées |
|---:|---:|---|---|
| 0 | 0.50 | `defaut_aucune_fenetre_anterieure` | [] |
| 1 | 0.00 | `fenetres_anterieures` | [0] |
| 2 | 0.00 | `fenetres_anterieures` | [0, 1] |
| 3 | 0.25 | `fenetres_anterieures` | [0, 1, 2] |

## 4. Périmètres publiés séparément

### a) End-to-end (toutes cibles) vs cibles éligibles seulement

| Modèle | Recall@10 end-to-end | Recall@10 cibles éligibles | NDCG@10 end-to-end | NDCG@10 éligibles |
|---|---:|---:|---:|---:|
| R1_decouverte | 0.0750 | 0.0832 | 0.0437 | 0.0474 |
| R2_decouverte | 0.0720 | 0.0796 | 0.0419 | 0.0454 |

### b) Par segment de client (NDCG@10 moyen)

| Modèle | Actifs | Peu actifs | Cold-start |
|---|---:|---:|---:|
| R1_decouverte | 0.0431 | 0.0444 | 0.0607 |
| R2_decouverte | 0.0410 | 0.0434 | 0.0578 |

### c) Découverte vs réapprovisionnement

| Modèle | Politique | Recall@10 | NDCG@10 | Couverture |
|---|---|---:|---:|---:|
| R1 | découverte | 0.0750 | 0.0437 | 0.0508 |
| R1 | réapprovisionnement | 0.0759 | 0.0441 | 0.0333 |
| R2 | découverte | 0.0720 | 0.0419 | 0.0892 |
| R2 | réapprovisionnement | 0.0734 | 0.0425 | 0.0850 |

## 5. Conformité aux seuils V2

| Critère | R1 | R2 |
|---|:---:|:---:|
| `recall_at_10` (0.0750 / 0.0720) | ❌ | ❌ |
| `ndcg_at_10` (0.0437 / 0.0419) | ❌ | ❌ |
| `couverture_catalogue` (0.0508 / 0.0892) | ❌ | ❌ |
| `n_fenetres_battues` (2 / 0) | ❌ | ❌ |
| `recul_clients_peu_actifs` (-0.0070 / 0.0162) | ✅ | ✅ |
| `aucun_doublon_top10` (0 / 0) | ✅ | ✅ |
| `aucun_produit_ineligible` (0 / 0) | ✅ | ✅ |
| `aucune_fuite_temporelle` (False / False) | ✅ | ✅ |

**Verdicts** :

- **R1_decouverte** : CANDIDAT REJETÉ — la V1 (popularité globale) reste la baseline officielle — critères échoués : ['recall_at_10', 'ndcg_at_10', 'couverture_catalogue', 'n_fenetres_battues']
- **R2_decouverte** : CANDIDAT REJETÉ — la V1 (popularité globale) reste la baseline officielle — critères échoués : ['recall_at_10', 'ndcg_at_10', 'couverture_catalogue', 'n_fenetres_battues']

## 6. Contrôles durs

| Contrôle | R1 | R2 |
|---|---:|---:|
| Doublons dans un Top-10 | 0 | 0 |
| Produits inéligibles recommandés | 0 | 0 |

- Durée totale : **78.44 s** · mémoire 306.3 Mo

## 7. Lecture des résultats

### R1 : la régularisation ne généralise pas (même schéma qu'en forecasting)

R1 fait **légèrement moins bien que la V1** sur toutes les métriques de pertinence (Recall@10 0.0750 contre 0.0759, soit −1,2 %). La cause est visible dans le tableau §3 : le choix de α sur les fenêtres antérieures retient α = 0,00 pour les fenêtres 1 et 2 — c'est-à-dire la **popularité récente pure** — alors que la popularité globale s'avère meilleure sur la fenêtre évaluée.

C'est exactement le schéma déjà rencontré en forecasting avec les candidats A et B : **apprendre un poids ou une règle sur les fenêtres passées ne généralise pas à la fenêtre suivante sur ce jeu de données.** Le constat est désormais cohérent sur les deux modules.

### R2 : un vrai gain de couverture, mais qui ne franchit aucune des deux barres

R2 produit l'effet recherché sur la diversité — et de façon nette :

| Indicateur | V1 | R2 | Écart |
|---|---:|---:|---:|
| Couverture catalogue | 0.0542 | 0.0892 | **+64,6 %** |
| Diversité@10 | 0.3333 | 0.4226 | +26,8 % |
| Concentration top-10 produits | non mesurée en V1 | 0.5353 | R1 : 0.9250 |
| NDCG@10 | 0.0441 | 0.0419 | −4,9 % |

La concentration est le chiffre le plus parlant : en V1/R1, **92,5 % des recommandations portent sur seulement 10 produits** ; R2 ramène cette part à **53,5 %**. C'est un changement de nature du système, pas un réglage marginal.

**Mais R2 échoue aux deux barres possibles, et il faut le dire clairement :**

1. **Barre absolue** : couverture 0.0892 < seuil 0,10 exigé (elle l'atteint sur la fenêtre 1, à 0,1000, mais pas en moyenne).
2. **Barre de compromis** : la règle tolère une perte de NDCG ≤ 2 % **à condition** que la couverture soit au moins doublée (≥ 0,1084). R2 perd **4,9 % de NDCG** (plus du double de la tolérance) et n'atteint que **82,3 % du seuil de doublement**. Les deux conditions échouent — il ne suffit pas que l'une soit proche.

R2 est donc rejeté, mais **c'est le candidat le plus intéressant des deux** : il attaque le bon défaut (la concentration extrême de la V1) et montre que ce défaut est corrigeable. Un réglage moins agressif de la pénalité viserait à conserver le gain de couverture en limitant la perte de NDCG — mais ce serait un ajustement **après** observation des résultats, ce que le protocole interdit. Cette piste doit être posée a priori dans une itération suivante, avec ses paramètres fixés à l'avance.

### Découverte vs réapprovisionnement

Autoriser les rachats **améliore la pertinence et dégrade la couverture**, pour R1 comme pour R2 (R1 : Recall@10 0.0750 → 0.0759, couverture 0.0508 → 0.0333). Cohérent avec le constat V1 : les rachats sont des cibles faciles à capter, mais ils concentrent encore davantage les recommandations sur un petit noyau de produits. Le choix reste un arbitrage métier, non tranché ici.

### Aucun candidat retenu

**La V1 (popularité globale) reste la baseline officielle.** Les quatre contrôles durs (doublons, produits inéligibles, fuite temporelle, recul sur les clients peu actifs) sont satisfaits par les deux candidats — l'échec porte uniquement sur les seuils de performance.

## 8. Ce qui n'a pas été fait

- **R3 et R4 non préparés** (point d'arrêt demandé).
- Signal web resté désactivé dans le modèle principal.
- Aucune modification de la V1, aucune écriture Supabase, aucun déploiement.
