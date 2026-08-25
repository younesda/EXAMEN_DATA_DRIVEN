# 08 — Protocole Recommandation V2 (avant toute expérimentation)

_Créé le 2026-08-15, branche `feature/v2-model-improvements`. Ce document fixe le protocole AVANT
l'évaluation des candidats, pour que les seuils ne puissent pas être ajustés après coup._

---

## 1. Baseline immuable

**`popularite_globale`** — la baseline officielle de la Recommandation V1. Tout candidat V2 doit la
battre sur son propre terrain, à périmètre strictement identique, ou la V1 reste retenue.

**Rappel du positionnement V1**, à ne jamais perdre de vue : il s'agit d'une **liste de popularité
générique**, pas d'un moteur personnalisé (`personalization_validated: false`). Les mêmes produits sont
recommandés à tous les clients d'un même segment de repli.

---

## 2. Références V1 (chargées depuis les artefacts, jamais codées en dur)

| Référence | Valeur exacte | Valeur publiée |
|---|---:|---:|
| Recall@10 | 0,075868 | 0,0759 |
| NDCG@10 | 0,044114 | 0,0441 |
| Recall@5 | 0,040273 | — |
| NDCG@5 | 0,029962 | — |
| Couverture catalogue | 0,054167 | 0,0542 |
| Couverture utilisateurs | 1,000000 | — |
| Diversité@10 | 0,333328 | — |
| Personnalisation validée | `false` | `false` |

Chargées par `v2/recommendation/v1_recsys_reference.py` depuis
`reports/recsys_final/baselines_summaries.csv` et `reports/recsys_final/metadata.json`.

---

## 3. Seuils d'acceptation V2 (figés dans `v2/config/recsys_v2_thresholds.json`)

| # | Critère | Seuil |
|---|---|---|
| 1 | Recall@10 | ≥ 0,080 |
| 2 | NDCG@10 | ≥ 0,047 |
| 3 | Couverture catalogue | ≥ 0,10 |
| 4 | Fenêtres battues | ≥ 3 sur 4 |
| 5 | Perte de NDCG tolérée si couverture au moins doublée | ≤ 2 % |
| 6 | Recul sur les clients peu actifs | ≤ 5 % |
| 7 | Fuite temporelle | aucune |
| 8 | Produits inéligibles recommandés | aucun |
| 9 | Doublons dans un Top-10 | aucun |

**Point d'attention sur le critère 5** : « couverture au moins doublée » signifie ≥ 0,1084
(2 × 0,0542), un seuil **plus exigeant** que le seuil absolu de couverture (0,10). Les deux se lisent
séparément — la règle de compromis n'assouplit que le NDCG, jamais la couverture.

Un critère **non évaluable** compte comme **non satisfait**, jamais ignoré.

---

## 4. Périmètre (identique à la V1)

**Quatre fenêtres**, reprises telles quelles :

| Fenêtre | Rôle | Fin train | Test | Clients évaluables |
|---:|---|---|---|---:|
| 0 | cold-start dédiée | 2025-05-01 | 2025-05-02 → 2025-06-30 | 3 781 |
| 1 | principale | 2026-02-01 | 2026-02-02 → 2026-04-02 | 4 396 |
| 2 | principale | 2026-04-02 | 2026-04-03 → 2026-06-01 | 4 531 |
| 3 | principale | 2026-06-01 | 2026-06-02 → 2026-07-31 | 4 538 |

Mêmes clients évaluables, mêmes règles de candidats (stock connu à J−1, politique de rachat), mêmes
définitions de métriques — le module V1 `src/recsys/metrics.py` est **importé sans modification**.

---

## 5. Sept périmètres publiés séparément

Jamais agrégés entre eux :

1. End-to-end, toutes cibles
2. Cibles éligibles seulement
3. Clients actifs
4. Clients peu actifs
5. Cold-start
6. Découverte (rachats exclus)
7. Réapprovisionnement (rachats autorisés)

---

## 6. Candidats

| Candidat | Principe | Statut |
|---|---|---|
| **R1** | Popularité régularisée : `score = α × globale + (1−α) × récente` | **Évalué** |
| **R2** | Reranking de diversité à partir de R1 | **Évalué** |
| R3 | Popularité par catégorie avec repli R1 | Non préparé (point d'arrêt) |
| R4 | Personnalisation légère au-delà d'un seuil d'interactions | Non préparé (point d'arrêt) |

### R1 — paramètres fixés a priori

- Grille : α ∈ {0,00 ; 0,25 ; 0,50 ; 0,75 ; 1,00}
- Fenêtre « récente » : 60 jours
- α par défaut (fenêtre 0, sans historique) : 0,50
- Choix de α pour la fenêtre *k* : **uniquement sur les fenêtres antérieures 0..k−1**

### R2 — paramètres fixés a priori

- Plafond de concentration : ≤ 3 produits d'une même catégorie dans le Top-10
- Diversité minimale : ≥ 4 catégories distinctes dans le Top-10
- Pénalité d'omniprésence : 0,5, appliquée au-delà de 30 % d'exposition clients

L'exposition est calculée **au fil de l'eau** dans la fenêtre courante, jamais depuis le futur.

---

## 7. Signal web

**Désactivé dans le modèle principal**, conformément au constat V1 : il **dégradait** le recall
cold-start (0,0846 avec, contre 0,1110 sans). Il reste testable en ablation uniquement, et doit rester
exclu s'il dégrade le cold-start.

---

## 8. Risques de fuite et parades

| Risque | Parade |
|---|---|
| α choisi en regardant la fenêtre évaluée | Sélection expansive : fenêtres 0..k−1 uniquement |
| Popularité calculée sur tout l'historique | Popularités recalculées sur le train de chaque fenêtre |
| Exposition R2 calculée depuis le futur | Accumulée au fil de l'eau dans la fenêtre courante |
| Produit recommandé alors qu'indisponible | Filtre stock à J−1, vérifié par compteur `n_ineligibles` |
| Rachat recommandé en mode découverte | Exclusion vérifiée par le même compteur |
| Doublons dans un Top-10 | Compteur `n_doublons` sur toutes les listes |

---

## 9. Règle d'arrêt

1. R1 puis R2 sont évalués ; R3 et R4 ne sont **pas** préparés à ce stade.
2. Un candidat qui échoue est documenté avec ses chiffres réels et ses raisons, puis abandonné — il
   n'est pas réajusté jusqu'à ce qu'il passe.
3. Si aucun candidat ne satisfait tous les critères, **la V1 (popularité globale) reste la baseline
   officielle**.

---

## 10. Ce qui n'est pas fait

- **Pricing V2 non démarré.**
- Aucune modification de la V1 (verrou SHA-256 actif).
- Aucune écriture Supabase, aucun déploiement, aucune fusion dans `main`.
