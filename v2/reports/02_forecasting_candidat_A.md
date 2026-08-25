# 02 — Candidat A : combinaison AutoETS / WindowAverage28

_Généré le 2026-08-15T03:39:20.982604+00:00. Branche `feature/v2-model-improvements`._

**Statut : `experiment_not_retained` — raison : `insufficient_gain`**

## 1. Ce que fait le candidat

Combinaison convexe y = w*AutoETS + (1-w)*WindowAverage28. Poids choisi par fenêtre uniquement sur les fenêtres strictement antérieures, sur une grille fixée a priori. Aucun réentraînement : recombinaison des prédictions V1 figées.

Grille de poids fixée a priori : [0.0, 0.25, 0.5, 0.75, 1.0]. Poids retenus par fenêtre :

| Fenêtre | Poids AutoETS | Source du poids | Fenêtres utilisées |
|---:|---:|---|---|
| 1 | 0.50 | `defaut_aucune_fenetre_anterieure` | [] |
| 2 | 0.50 | `fenetres_anterieures` | [1] |
| 3 | 0.50 | `fenetres_anterieures` | [1, 2] |
| 4 | 0.50 | `fenetres_anterieures` | [1, 2, 3] |
| 5 | 0.75 | `fenetres_anterieures` | [1, 2, 3, 4] |
| 6 | 0.75 | `fenetres_anterieures` | [1, 2, 3, 4, 5] |

Les fenêtres 1 à 4 retiennent un poids équilibré (0,50), les fenêtres 5 et 6 basculent vers AutoETS (0,75) — cohérent avec le fait qu'AutoETS domine sur les fenêtres tardives.

## 2. Métriques principales — candidat vs V1

| Métrique | V1 | Candidat A | Gain absolu | Gain relatif |
|---|---:|---:|---:|---:|
| WAPE quotidienne | 1.094727 | 1.085510 | 0.009217 | +0.84% |
| WAPE cumulée 7 j | 0.461864 | 0.455601 | 0.006263 | +1.36% |
| WAPE cumulée 14 j | 0.350794 | 0.349073 | 0.001721 | +0.49% |
| WAPE cumulée 30 j | 0.277179 | 0.275308 | 0.001871 | +0.67% |

**Fenêtres améliorées à 30 jours : 2 sur 6.**

## 3. Résultats par fenêtre (grain cumulé 30 jours)

| Fenêtre | V1 | Candidat A | Gain | Améliorée ? |
|---:|---:|---:|---:|:---:|
| 1 | 0.333693 | 0.297664 | 0.036028 | oui |
| 2 | 0.296446 | 0.287619 | 0.008827 | oui |
| 3 | 0.258398 | 0.263781 | -0.005384 | non |
| 4 | 0.253232 | 0.270342 | -0.017109 | non |
| 5 | 0.262022 | 0.266546 | -0.004524 | non |
| 6 | 0.270052 | 0.270705 | -0.000653 | non |

## 4. Résultats par segment (grain cumulé 30 jours)

### Classe ABC

| Classe | V1 | Candidat A | Gain | n produits×fenêtres |
|---|---:|---:|---:|---:|
| A | 0.280092 | 0.275380 | 0.004712 | 376 |
| B | 0.271756 | 0.268989 | 0.002767 | 518 |
| C | 0.279291 | 0.279759 | -0.000468 | 768 |

### Profil de demande

| Profil | V1 | Candidat A | Gain | n produits×fenêtres |
|---|---:|---:|---:|---:|
| erratique | 0.271296 | 0.236536 | 0.034760 | 19 |
| grumeleux | 0.271903 | 0.270123 | 0.001780 | 865 |
| indetermine | 1.027401 | 0.894179 | 0.133223 | 7 |
| intermittent | 0.269503 | 0.272461 | -0.002958 | 747 |
| regulier | 0.407119 | 0.368241 | 0.038878 | 24 |

### Produits récents

- Définition : historique < 90 jours au cutoff
- V1 : 0.391484 · Candidat A : 0.354134 · n = 205

## 5. Biais et stabilité

| Indicateur | V1 | Candidat A |
|---|---:|---:|
| Biais normalisé (quotidien) | 0.067347 | 0.039917 |
| Biais normalisé (cumulé 30 j) | 0.067347 | 0.039917 |
| WAPE 30 j — écart-type inter-fenêtres | 0.030830 | 0.013439 |
| WAPE 30 j — min / max | 0.2532 / 0.3337 | 0.2638 / 0.2977 |

## 6. Sensibilité au poids (poids fixe sur toutes les fenêtres)

_Ces chiffres servent à comprendre la forme de la courbe, **pas** à choisir un poids : un poids choisi ainsi regarderait toutes les fenêtres, y compris celle évaluée._

| Poids AutoETS | WAPE quotidienne | WAPE 7 j | WAPE 30 j |
|---:|---:|---:|---:|
| 0.00 | 1.083385 | 0.472069 | 0.316128 |
| 0.25 | 1.083391 | 0.461442 | 0.293798 |
| 0.50 | 1.085277 | 0.456417 | 0.279118 |
| 0.75 | 1.089046 | 0.456556 | 0.273617 |
| 1.00 | 1.094727 | 0.461864 | 0.277179 |

## 7. Intervalles (niveau 80 %)

_Méthode : conforme empirique, calibration leave-one-window-out par bucket d'horizon (méthode V1, pour comparaison à l'identique)._

| Indicateur | V1 | Candidat A |
|---|---:|---:|
| Couverture globale | 0.7988 | 0.8002 |
| Couverture produits A | 0.7439 | 0.7488 |
| Largeur moyenne | 3.6042 | 3.6225 |

**La combinaison ne corrige pas la sous-couverture des produits A** — c'est précisément l'objet du candidat C (recalibration par segment).

## 8. Verdict — chaque seuil d'acceptation

| Critère | Valeur | Seuil | Règle | Satisfait ? |
|---|---:|---:|---|:---:|
| `wape_cumule_30j` | 0.275308 | 0.265000 | ≤ seuil absolu | ❌ |
| `wape_cumule_7j` | 0.455601 | 0.440000 | ≤ seuil absolu | ❌ |
| `wape_quotidien` | 1.085510 | 1.061885 | ≥3% d'amélioration vs V1 | ❌ |
| `wape_abc_a` | 0.275380 | 0.285694 | ≤2% de dégradation vs V1 (non évaluable = non satisfait) | ✅ |
| `n_fenetres_ameliorees_30j` | 2 | 4.000000 | ≥ 4 fenêtres sur 6 | ❌ |
| `couverture_80_globale` | 0.800201 | [0.78, 0.84] | dans [78 %, 84 %] | ✅ |
| `couverture_80_produits_a` | 0.748848 | [0.78, 0.84] | dans [78 %, 84 %] | ❌ |
| `aucune_valeur_non_finie` | 0 | 0.000000 | = 0 | ✅ |
| `aucune_valeur_negative` | 0 | 0.000000 | = 0 | ✅ |

**CANDIDAT REJETÉ — la V1 reste le modèle officiel**

Critères échoués : ['wape_cumule_30j', 'wape_cumule_7j', 'wape_quotidien', 'n_fenetres_ameliorees_30j', 'couverture_80_produits_a']

## 9. Lecture honnête du résultat

Le candidat A améliore réellement la WAPE cumulée à 30 jours (0.277179 → 0.275308, soit +0.67%) — **le gain est réel, mais très loin du seuil d'acceptation de 0,265**. Il faudrait environ 3.7% d'amélioration supplémentaire pour l'atteindre.

Un écart favorable de quelques millièmes ne suffit pas à déclarer une V2 : le protocole fixait les seuils **avant** l'expérience, précisément pour éviter de requalifier après coup un petit gain en succès.

### ⚠️ Le gain agrégé est un artefact d'une seule fenêtre

- **Fenêtre 1 seule : 0.036028** (amélioration)
- **Fenêtres 2 à 6 cumulées : -0.018843** (dégradation nette)

**Le gain global vient entièrement de la fenêtre 1, et les fenêtres 3 à 6 sont toutes dégradées.** Or la fenêtre 1 est précisément celle où le poids n'a pu être appris sur aucune donnée : c'est le poids par défaut (0,50), fixé a priori. Le « gain » du candidat A repose donc sur un coup de chance sur une fenêtre non informée, pas sur une capacité d'apprentissage du poids. Dès que le poids est réellement estimé sur l'historique (fenêtres 2 à 6), le mélange fait globalement **moins bien** que la V1.

C'est la raison de fond du rejet, bien plus que l'écart au seuil : le mécanisme ne généralise pas. Le critère « ≥4 fenêtres améliorées sur 6 » (2/6 obtenues) l'avait anticipé — il est là exactement pour détecter ce cas.

### Ce qui s'améliore réellement et mérite d'être retenu

- **Stabilité inter-fenêtres** : écart-type de la WAPE 30 j divisé par ~2,3 (0.0308 → 0.0134).
- **Biais** : nettement réduit (0.0673 → 0.0399) — la sur-prévision structurelle d'AutoETS est compensée par WindowAverage28.

Ces deux propriétés ne dépendent pas d'une fenêtre particulière : elles justifient de conserver le mélange comme **composant**, sans en faire une V2 à lui seul.

## 10. Réutilisation future

Le mélange reste un composant réutilisable : un futur candidat combiné pourrait associer le meilleur point forecast (A ou B) aux intervalles recalibrés du candidat C.

## 11. Coût de calcul

- Durée totale : **8.47 s** (dont candidat 1.02 s, intervalles 2.01 s)
- Mémoire résidente en fin d'exécution : 281.8 Mo
- Réentraînement : **non** — recombinaison de prédictions V1 figées

## 12. Garanties

- Poids déterminés uniquement sur les fenêtres strictement antérieures (tests de perturbation).
- Périmètre identique à la V1 : 1 662 couples (produit, fenêtre).
- Aucune valeur non finie (0), aucune valeur négative (0).
- Aucun artefact V1 modifié (verrou SHA-256 vérifié par test).
