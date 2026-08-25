# 03 — Candidat B : sélection AutoETS / WindowAverage28 par segment

_Généré le 2026-08-15T03:42:12.081912+00:00. Branche `feature/v2-model-improvements`._

**Statut : `experiment_not_retained` — raison : `worse_than_v1_and_candidate_a`**

## 1. Les trois variantes testées

| Variante | Principe | Apprentissage |
|---|---|---|
| **B1** | Règle fixée a priori : WindowAverage28 si taux de jours sans vente > 60%, AutoETS sinon | Aucun |
| **B2** | Meilleur modèle par segment (classe ABC × profil de demande) | Fenêtres strictement antérieures |
| **B3** | Sélection par produit, autorisée seulement si ≥2 fenêtres passées ET gain ≥10% | Fenêtres strictement antérieures, fortement régularisée |

Tous les paramètres ci-dessus ont été fixés **avant** de regarder le moindre résultat. Les variables de segmentation (ABC, taux de zéros, ADI, ancienneté, longueur d'historique) sont recalculées par fenêtre **sur le train uniquement**.

## 2. Résultat principal

| Modèle | WAPE 30 j | WAPE 7 j | WAPE quotidienne | Fenêtres améliorées /6 |
|---|---:|---:|---:|---:|
| **V1 (référence)** | 0.277179 | 0.461864 | 1.094727 | — |
| Candidat A | 0.275308 | 0.455601 | 1.085510 | 2 |
| B1_regle_simple_preetablie | 0.283800 | 0.460380 | 1.092582 | 1 |
| B2_meilleur_par_segment_fenetres_anterieures | 0.283052 | 0.464283 | 1.093569 | 0 |
| B3_par_produit_regularise | 0.286635 | 0.465177 | 1.093202 | 0 |

**Aucune des trois variantes ne bat la V1** (meilleure : `B2_meilleur_par_segment_fenetres_anterieures` à 0.283052 contre 0.277179), ni le candidat A (0.275308).

## 3. Pourquoi la sélection par segment échoue

### Les décisions sont instables d'une fenêtre à l'autre

Part de produits basculés vers WindowAverage28, par fenêtre :

| Variante | F1 | F2 | F3 | F4 | F5 | F6 |
|---|---:|---:|---:|---:|---:|---:|
| B1_regle_simple_preetablie | 21.5% | 24.2% | 25.8% | 24.7% | 25.7% | 25.3% |
| B2_meilleur_par_segment_fenetres_anterieures | 0.0% | 46.4% | 21.8% | 11.7% | 0.0% | 0.0% |
| B3_par_produit_regularise | 0.0% | 0.0% | 33.5% | 31.1% | 21.6% | 21.0% |

**B2 est le cas le plus parlant** : la part de produits confiés à WindowAverage28 passe de 0 % (F1, aucune donnée) à 46,4 % (F2), puis retombe à 21,8 %, 11,7 %, puis 0 % sur les deux dernières fenêtres. Le « meilleur modèle par segment » change donc complètement d'une fenêtre à la suivante : ce n'est pas un signal stable, c'est du bruit d'échantillonnage. Une règle apprise sur ce bruit ne peut pas généraliser — et de fait, elle dégrade la performance.

**B3 (par produit)** est encore plus exposé : malgré une régularisation sévère (≥2 fenêtres et ≥10% de gain exigés), c'est la variante la moins bonne. Avec au plus 5 fenêtres d'historique par produit, estimer un choix de modèle produit par produit revient à ajuster sur très peu de points.

**B1 (règle fixe, sans apprentissage)** fait presque aussi bien que B2 — ce qui confirme que l'apprentissage de la règle n'apporte rien : toute la performance vient de la règle a priori, et celle-ci est déjà moins bonne que de garder AutoETS partout.

## 4. Détail des seuils d'acceptation (meilleure variante)

| Critère | Valeur | Seuil | Satisfait ? |
|---|---:|---:|:---:|
| `wape_cumule_30j` | 0.283052 | 0.265000 | ❌ |
| `wape_cumule_7j` | 0.464283 | 0.440000 | ❌ |
| `wape_quotidien` | 1.093569 | 1.061885 | ❌ |
| `wape_abc_a` | 0.296265 | 0.285694 | ❌ |
| `n_fenetres_ameliorees_30j` | 0 | 4.000000 | ❌ |
| `couverture_80_globale` | 0.799138 | [0.78, 0.84] | ✅ |
| `couverture_80_produits_a` | 0.748227 | [0.78, 0.84] | ❌ |
| `aucune_valeur_non_finie` | 0 | 0.000000 | ✅ |
| `aucune_valeur_negative` | 0 | 0.000000 | ✅ |

**CANDIDAT REJETÉ — la V1 reste le modèle officiel**

## 5. Décision

Conformément au protocole (« si le candidat B ne dépasse pas le candidat A et la V1 de façon stable, arrête-le et archive-le comme non retenu »), **le candidat B est arrêté et archivé comme non retenu**. Aucune variante supplémentaire ne sera essayée : le problème n'est pas le réglage, c'est que le signal de segmentation n'est pas stable dans le temps sur ce jeu de données.

## 6. Enseignement transférable

L'échec de B renforce le diagnostic du candidat A : **le choix entre AutoETS et WindowAverage28 ne se généralise ni globalement (A), ni par segment, ni par produit (B).** Cela oriente la suite vers ce qui reste réellement perfectible et mesurable : la calibration de l'incertitude (candidat C), où la V1 a un défaut documenté et chiffré (sous-couverture des produits A à ~74 % au lieu de 80 %).

## 7. Coût de calcul

- Durée totale : **16.51 s** pour les trois variantes
- Mémoire résidente : 270.6 Mo
- Réentraînement : **non** (sélection parmi les prédictions V1 figées)

## 8. Garanties

- Segmentation calculée par fenêtre sur le **train uniquement**.
- Règles apprises **exclusivement** sur les fenêtres strictement antérieures (F1 retombe sur AutoETS par défaut, sans apprentissage).
- Aucun artefact V1 modifié.
