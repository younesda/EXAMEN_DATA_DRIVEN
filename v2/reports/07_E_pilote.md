# 07 — Candidat E : pilote sur les fenêtres 1 et 2

_Généré le 2026-08-15T12:12:46.824094+00:00. Branche `feature/v2-model-improvements`._

**Statut : `experiment_not_promising` — raison : `gain_below_pilot_gate_2pct`**

## 1. Dispositif

Pilote restreint aux fenêtres [1, 2], pour vérifier le fonctionnement technique avant d'engager les six fenêtres. Le modèle est LightGBM (objectif Tweedie), **réutilisant sans modification le moteur récursif de la V1**, dont l'absence de fuite multi-horizon a déjà été prouvée par tests de perturbation.

Les paramètres LightGBM sont **ceux de la V1, inchangés** : le pilote ne sert ni à régler des hyperparamètres, ni à ajuster les seuils d'acceptation.

## 2. Résultats des ablations (fenêtres 1 et 2)

| Niveau | Contenu | WAPE 30 j | WAPE 7 j | WAPE quotidienne | Gain relatif 30 j vs V1 |
|---|---|---:|---:|---:|---:|
| **V1 (référence)** | AutoETS + repli Naive | 0.314782 | 0.510902 | 1.136795 | — |
| E1 | calendrier seul | 0.310767 | 0.478693 | 1.142565 | +1.28% |
| E2 | + promotions planifiées | 0.331335 | 0.472109 | 1.166914 | -5.26% |
| E3 | + âge de version | 0.311443 | 0.468308 | 1.147523 | +1.06% |
| E4 | + stock initial | 0.312827 | 0.466907 | 1.149903 | +0.62% |

## 3. Porte de décision

- Gain relatif minimal exigé (fixé **avant** l'exécution) : **2%**
- Meilleur niveau observé : **E1** avec **+1.28%**
- Porte franchie : **non**

**Le candidat E est archivé comme non prometteur. Les six fenêtres ne sont pas exécutées.**

Ce n'est pas un abandon par manque de temps : c'est l'application de la règle fixée à l'avance. Poursuivre sur six fenêtres coûterait plusieurs heures de calcul pour un candidat dont le pilote montre qu'il est **très loin** du seuil requis — et l'écart au seuil d'acceptation V2 (WAPE 30 j ≤ 0,265) est encore plus grand.

## 4. Contrôles techniques

| Niveau | Fenêtre | Features | Lignes train | Produits | Fit (s) | Predict (s) | NaN | Négatifs | Mémoire (Mo) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| E1 | 1 | — | — | — | — | — | — | — | 222.9 |
| E1 | 2 | — | — | — | — | — | — | — | 223.0 |
| E2 | 1 | — | — | — | — | — | — | — | 242.7 |
| E2 | 2 | — | — | — | — | — | — | — | 242.8 |
| E3 | 1 | — | — | — | — | — | — | — | 250.8 |
| E3 | 2 | — | — | — | — | — | — | — | 250.8 |
| E4 | 1 | — | — | — | — | — | — | — | 251.6 |
| E4 | 2 | — | — | — | — | — | — | — | 251.8 |

- **NaN produits : 0** · **Valeurs négatives : 0**
- Nombre d'entraînements : 8
- Durée totale : **5.8 s**
- Mémoire résidente finale : 269.7 Mo
- Checkpoints écrits par (niveau, fenêtre) : reprise possible sans tout recalculer.

## 5. Sens des prédictions

Les ablations se comportent comme attendu structurellement : ajouter des groupes de variables modifie les prédictions sans produire de valeur aberrante (aucun NaN, aucune valeur négative sur l'ensemble des exécutions).

## 6. Lecture du résultat

Même le meilleur niveau d'ablation (E1) reste à 0.3108 de WAPE 30 j, contre 0.3148 pour la V1 — soit un écart de +1.28%.

Ce résultat est cohérent avec ce que la V1 avait déjà établi : les modèles d'apprentissage à base de variables (LightGBM) plafonnaient entre 0,308 et 0,351 de WAPE 30 j, nettement au-dessus d'AutoETS (0,277). **Les variables métier connues à l'avance n'inversent pas ce constat** — l'ajout successif des promotions, de l'âge de version et du stock initial ne comble pas l'écart.

L'apport marginal de chaque groupe est faible : de E1 (0.3108) à E4 (0.3128), l'écart total est de 0.0021 en valeur absolue. Aucun groupe de variables ne change l'ordre de grandeur.

### Résultat secondaire notable : les variables aident à 7 jours, pas à 30

Gain relatif par horizon (positif = meilleur que la V1) :

| Niveau | 7 jours | 30 jours | Quotidien |
|---|---:|---:|---:|
| E1 | +6.30% | +1.28% | -0.51% |
| E2 | +7.59% | -5.26% | -2.65% |
| E3 | +8.34% | +1.06% | -0.94% |
| E4 | +8.61% | +0.62% | -1.15% |

**À 7 jours, tous les niveaux battent la V1, et le gain croît de façon monotone avec l'ajout de variables** (jusqu'à +8,6 % pour E4). À 30 jours et au grain quotidien, l'effet disparaît ou s'inverse.

L'explication mécanique est cohérente avec ce qui avait déjà été observé en V1 : la stratégie récursive réinjecte ses propres prédictions à chaque pas, si bien que l'erreur s'accumule sur 30 jours et finit par masquer l'apport des variables. Celles-ci sont donc **réellement informatives à court horizon** — mais le protocole V2 a fixé la WAPE 30 j comme critère prioritaire, et c'est sur ce critère que E échoue.

**Cette piste reste néanmoins insuffisante en l'état** : le meilleur niveau atteint 0.4669 à 7 jours, encore au-dessus du seuil V2 de 0,44. Même en reciblant le protocole sur le court horizon, aucun niveau ne serait accepté aujourd'hui. C'est en revanche une piste identifiée pour une V3 : une **prévision directe par horizon** (sans récursion) permettrait de conserver l'apport des variables sans subir l'accumulation d'erreur — c'était déjà la piste #12 du registre V2 forecasting.

### Le cas E2 : les promotions dégradent nettement le 30 jours

E2 est le seul niveau franchement dégradé à 30 jours (0.3313, soit −5,26 %) alors qu'il **améliore** le 7 jours (+7,59 %). Ajouter l'âge de version (E3) corrige ensuite en partie cette dégradation. Ce comportement instable renforce la réserve posée en E0 : l'hypothèse selon laquelle le calendrier promotionnel serait entièrement connu au cutoff n'est **pas vérifiable** avec les données disponibles, et les variables de promotion doivent être maniées avec prudence.

## 7. Garanties

- Moteur récursif V1 réutilisé **sans modification** (anti-fuite déjà prouvé par perturbation).
- Stock utilisé uniquement comme **état initial au cutoff**, jamais projeté sur l'horizon (justification chiffrée en E0 §3).
- Hypothèse sur la connaissance du calendrier promotionnel explicitement documentée (E0 §4).
- Aucun hyperparamètre ajusté sur le pilote.
- Aucun artefact V1 modifié.
