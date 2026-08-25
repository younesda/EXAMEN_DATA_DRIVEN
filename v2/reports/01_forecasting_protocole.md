# 01 — Protocole Forecasting V2 (avant tout entraînement)

_Généré le 2026-08-15, branche `feature/v2-model-improvements`. Aucun entraînement lourd n'a encore été
lancé. Ce document fixe le protocole AVANT expérimentation, pour que les seuils ne puissent pas être
ajustés après coup en fonction des résultats._

---

## 1. Baseline immuable

**`AutoETS + repli Naive`** — le pipeline V1 officiel. La V2 doit le battre sur son propre terrain, à
périmètre strictement identique, ou la V1 reste retenue.

Les artefacts V1 des trois phases (22 fichiers) sont verrouillés par empreinte SHA-256 dans
`v2/config/v1_lock.json`. Le test `v2/tests/test_v1_artifacts_unchanged.py` échoue si l'un d'eux est
modifié ou supprimé.

---

## 2. Les six fenêtres temporelles (identiques à la V1)

Paramètres vérifiés par test automatique : `H = 30`, `N_WINDOWS = 6`, `SEASONALITY = 7`.

| Fenêtre | Train | Fin train | Test | Jours train | Produits test | Dont nouveaux | **Éligibles (périmètre principal)** |
|---:|---|---|---|---:|---:|---:|---:|
| 1 | 2025-02-01 → | 2026-02-01 | 2026-02-02 → 2026-03-03 | 366 | 265 | 18 | **247** |
| 2 | 2025-02-01 → | 2026-03-03 | 2026-03-04 → 2026-04-02 | 396 | 275 | 10 | **265** |
| 3 | 2025-02-01 → | 2026-04-02 | 2026-04-03 → 2026-05-02 | 426 | 283 | 8 | **275** |
| 4 | 2025-02-01 → | 2026-05-02 | 2026-05-03 → 2026-06-01 | 456 | 292 | 9 | **283** |
| 5 | 2025-02-01 → | 2026-06-01 | 2026-06-02 → 2026-07-01 | 486 | 300 | 8 | **292** |
| 6 | 2025-02-01 → | 2026-07-01 | 2026-07-02 → 2026-07-31 | 516 | 300 | 0 | **300** |

**Total : 1 662 couples (produit, fenêtre) éligibles** — exactement le dénominateur des métriques V1
publiées. Un test dédié échoue si ce nombre ou sa répartition par fenêtre change.

**Règles d'éligibilité (inchangées)** : périmètre principal = produits présents dans le train au cutoff
(`train_observations > 0`). Les produits cold-start (absents du train) sont exclus du classement
principal et traités séparément par `ColdStartZero`, exactement comme en V1.

---

## 3. Artefacts V1 utilisés comme référence

| Référence | Valeur | Source (chargée dynamiquement, jamais recopiée) |
|---|---:|---|
| WAPE cumulée 30 j | 0,277179 | `reports/forecast_final/v1_metrics_snapshot.json` |
| WAPE cumulée 14 j | 0,350794 | idem |
| WAPE cumulée 7 j | 0,461864 | idem |
| WAPE quotidienne | 1,094727 | idem |
| Couverture intervalle 80 % — produits A | 0,7436 | `reports/23_rapport_final_forecasting.md` §8 |
| Couverture intervalle 80 % — global (J+15-30) | 0,7990 | `reports/23_intervals_ae.csv` |

Ces valeurs sont chargées par `v2/config/v1_reference.py`. **Aucune n'est codée en dur** — un test
structurel (`test_aucune_valeur_de_reference_codee_en_dur_dans_le_module_v2`) échoue si une valeur V1
apparaît en littéral dans le module.

---

## 4. Objectifs d'acceptation (fixés avant expérimentation)

Une V2 n'est retenue que si **tous** les critères sont satisfaits **simultanément** :

| # | Critère | Seuil | Nature |
|---|---|---|---|
| 1 | WAPE cumulée 30 j | ≤ 0,265 | absolu |
| 2 | WAPE cumulée 7 j | ≤ 0,44 | absolu |
| 3 | WAPE quotidienne | ≤ 1,061885 (≥3 % mieux que V1) | dérivé de la V1 |
| 4 | WAPE produits ABC-A | ≤ V1 × 1,02 (≤2 % de dégradation) | dérivé de la V1 |
| 5 | Fenêtres améliorées à 30 j | ≥ 4 sur 6 | absolu |
| 6 | Couverture intervalle 80 % — globale | dans [0,78 ; 0,84] | absolu |
| 7 | Couverture intervalle 80 % — produits A | dans [0,78 ; 0,84] | absolu |
| 8 | Valeurs NaN / infinies | = 0 | absolu |
| 9 | Valeurs négatives | = 0 | absolu |
| 10 | Coût de calcul | raisonnable et reproductible | qualitatif, documenté |

Implémentés dans `v2/config/acceptance.py`. Un critère **non évaluable** (ex. WAPE ABC-A non fournie)
est traité comme **non satisfait** — jamais ignoré silencieusement.

**Règle par défaut : si aucun candidat ne satisfait tous les critères, la V1 reste officiellement le
modèle retenu.** C'est un résultat acceptable, pas un échec.

---

## 5. Candidats à tester (séquentiellement, du plus simple au plus complexe)

| Candidat | Description | Statut |
|---|---|---|
| **A** | Combinaison pondérée AutoETS / WindowAverage28 | **Préparé, non lancé** |
| B | Sélection par segment (ABC, intermittence, ancienneté, taux de zéros) | À faire |
| C | Recalibration des intervalles par segment (conforme) | À faire |
| D | Hurdle recalibré (P(vente>0) × quantité conditionnelle) | À faire |
| E | Variables métier connues à l'avance (ablations) | À faire |

Aucun candidat au-delà de A n'est préparé à ce stade, conformément au point d'arrêt demandé.

---

## 6. Risques de fuite identifiés et parades

| Risque | Parade | Test |
|---|---|---|
| Poids du mélange choisi en regardant la fenêtre évaluée | Poids déterminé uniquement sur les fenêtres 1..k-1 | `test_perturber_la_fenetre_courante_ne_change_pas_son_poids` |
| Information circulant à rebours (fenêtre future → passée) | Sélection strictement expansive | `test_perturber_une_fenetre_future_ne_change_aucun_poids_anterieur` |
| Train chevauchant le test | Fenêtres construites par `build_windows` V1 | `test_train_strictement_anterieur_au_test` |
| Segmentation calculée sur tout l'historique | Segmentation recalculée par fenêtre sur le train seul (règle V1 conservée) | à ajouter avec le candidat B |
| Promotions futures non connues au cutoff | Seules les promotions planifiées connues à la date de prévision | à ajouter avec le candidat E |
| Stock du jour / ventes du jour / `web_purchase` contemporain | **Interdits** — seul `stock_disponible_lag1` est autorisé | à ajouter avec le candidat E |
| Périmètre V2 différent du périmètre V1 | 1 662 couples vérifiés | `test_population_eligible_identique_a_la_v1` |
| Définition de métrique divergente | WAPE recalculée indépendamment et comparée au snapshot | `test_definition_wape_cumule_identique_a_la_v1` |
| V2 « améliorant » ses chiffres en modifiant la V1 | 22 artefacts verrouillés par SHA-256 | `test_aucun_artefact_v1_modifie` |

---

## 7. Budget de calcul

| Candidat | Coût mesuré / estimé | Justification |
|---|---|---|
| **A** | **~1,2 s au total** (0,86 s de chargement + 0,32 s d'exécution) — mesuré | Recombine les prédictions V1 déjà figées, **aucun réentraînement** |
| B | ~quelques secondes (estimé) | Même principe : sélection sur prédictions existantes |
| C | ~1-2 min (estimé) | Calibration conforme sur résidus, pas de réentraînement |
| D | ~45-65 min (estimé) | Réentraînement effectif de deux modèles × 6 fenêtres |
| E | ~1-3 h (estimé) | Ablations multiples, réentraînement par variante |

**Contrainte d'exécution** : une seule expérience lourde à la fois, checkpoints par (candidat, fenêtre),
journalisation durée + mémoire, reprise depuis checkpoint après incident — jamais de relance aveugle
après un `MemoryError` (cet environnement a montré des échecs mémoire transitoires réels).

---

## 8. Règle d'arrêt

1. Les candidats sont évalués **dans l'ordre A → E**, un à la fois.
2. Un candidat qui satisfait **tous** les critères du §4 est retenu comme V2 provisoire ; les candidats
   suivants doivent alors le battre lui, plus les seuils absolus.
3. Un candidat qui échoue est documenté avec ses chiffres réels et **ses raisons d'échec**, puis
   abandonné — on ne l'ajuste pas jusqu'à ce qu'il passe (ce serait de l'optimisation sur le test).
4. **Arrêt immédiat** si un test anti-fuite échoue : diagnostic avant toute poursuite.
5. Si, après les cinq candidats, aucun ne satisfait tous les critères : **la V1 reste le modèle officiel**
   et le rapport final le déclare explicitement.

---

## 9. Ce qui n'est pas fait à ce stade

- **Aucun entraînement lancé** (les chiffres du candidat A ci-dessus proviennent d'une recombinaison de
  prédictions V1 figées, pas d'un réentraînement).
- Aucun candidat B à E préparé.
- **Recommandation V2 et Pricing V2 non démarrées.**
- Aucun déploiement, aucune écriture dans Supabase.
