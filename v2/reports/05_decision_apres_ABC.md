# 05 — Décision après les candidats A, B et C

_Généré le 2026-08-15T03:46:50.469787+00:00. Branche `feature/v2-model-improvements`. Aucun candidat D ou E n'a été lancé._

## 1. Tableau de décision

| Candidat | WAPE 30 j | WAPE 7 j | WAPE quotidienne | Fenêtres gagnées | Couverture A 80 % | Statut |
|---|---:|---:|---:|---:|---:|---|
| V1 (référence) | 0.277179 | 0.461864 | 1.094727 | — | 0.7439 | Référence — modèle officiel |
| A — mélange AutoETS/WA28 | 0.275308 | 0.455601 | 1.085510 | 2/6 | 0.7488 | `experiment_not_retained` (insufficient_gain) |
| B — sélection par segment (B2) | 0.283052 | 0.464283 | 1.093569 | 0/6 | 0.7482 | `experiment_not_retained` (worse_than_v1_and_candidate_a) |
| C — recalibration intervalles (C3) | 0.277179 | 0.461864 | 1.094727 | sans objet | 0.7903 | `experiment_retained` (interval_calibration_improved) |

_Le candidat C ne modifie pas la prévision centrale : ses colonnes WAPE sont, par construction, identiques à celles de la V1. Seule la colonne « Couverture A 80 % » change._

## 2. Deux natures d'amélioration, à ne pas confondre

### a) Prévision centrale (candidats A et B) — **échec**

- **A** : 0.275308 contre 0.277179 en V1, soit +0.67%. Gain réel mais très inférieur au seuil (0,265), et surtout **concentré sur la seule fenêtre 1**, celle où le poids n'était pas appris (les fenêtres 3 à 6 sont toutes dégradées). 2 fenêtres améliorées sur 6, contre 4 exigées.
- **B** : meilleure variante à 0.283052 — **moins bonne que la V1 et que A**. Les décisions de segment sont instables d'une fenêtre à l'autre (la part de produits basculés vers WindowAverage28 varie de 0 % à 46 % selon la fenêtre) : le signal de segmentation est du bruit, pas une structure.

**Conclusion : sur ce jeu de données, le choix entre AutoETS et WindowAverage28 ne se généralise ni globalement, ni par segment, ni par produit.** Aucune recombinaison des deux modèles existants n'améliore durablement la prévision centrale.

### b) Incertitude (candidat C) — **succès**

- Couverture des produits A : **0.7439 (V1) → 0.7903** (variante retenue `C3_par_abc_profil`), désormais dans la cible [78 %, 84 %].
- Largeur moyenne : 3.6042 → 3.5951 (-0.25%) — **le gain n'est pas obtenu en élargissant les intervalles**, seulement en répartissant mieux la largeur entre segments.
- Variante alternative C2 (par ABC seul) : couverture A 0.8027, encore plus proche de la cible sur ce segment précis. Le choix C2/C3 est serré et documenté au rapport 04 §7.

**C corrige un défaut réel, documenté et chiffré de la V1** — sans toucher aux prévisions.

## 3. Système combiné envisageable

Puisque A et B échouent sur le point forecast et que C réussit sur l'incertitude, le système combiné pertinent est :

```
Prévision centrale : V1 inchangée (AutoETS + repli Naive)
Intervalles        : recalibrés par segment (C3_par_abc_profil)
```

Ce n'est **pas** « meilleur point forecast + C » comme envisagé initialement, puisqu'aucun candidat n'a produit de meilleur point forecast. Le mélange du candidat A reste néanmoins conservé comme composant : il améliore réellement la **stabilité inter-fenêtres** (écart-type 0.0308 → 0.0134) et le **biais** (0.0673 → 0.0399), deux propriétés qui pourraient compter si la priorité métier changeait.

## 4. Statut de la V2 forecasting à ce stade

| Volet | Statut |
|---|---|
| Prévision centrale | **La V1 reste le modèle officiel** — aucun candidat ne satisfait les seuils |
| Intervalles | **Amélioration retenue** (candidat C), prête à être proposée |
| Candidats D et E | **Non lancés** — décision en attente |

## 5. Faut-il lancer les candidats D et E ?

Les éléments objectifs pour trancher :

**Arguments pour poursuivre**

- D (hurdle recalibré) et E (variables métier) sont les seuls candidats qui introduisent une information nouvelle, là où A, B et C ne font que recombiner ou recalibrer l'existant.
- Le diagnostic de la V1 identifiait la forte intermittence (~50 % de jours à zéro) comme la cause principale de l'erreur quotidienne : c'est exactement ce que vise un modèle hurdle.

**Arguments pour s'arrêter**

- L'écart à combler reste important : il faudrait passer de 0.2772 à 0,265 sur la WAPE 30 j, soit environ 4.4% d'amélioration — alors que le meilleur candidat testé n'a obtenu que +0,67 %, et de façon non généralisable.
- Le hurdle LightGBM avait déjà été testé en V1 et rejeté (biais normalisé >0,10, discrimination faible du classifieur, ROC-AUC ≈0,62) : D repartirait d'une base déjà connue comme fragile sur ce jeu de données.
- D et E sont les seules expériences **lourdes** du protocole (45-65 min et 1-3 h estimées), contre quelques secondes pour A, B et C.

**Recommandation** : la décision revient au métier. Si l'objectif prioritaire est la fiabilité des intervalles, **C suffit et peut être proposé dès maintenant**. Si l'objectif est de réellement abaisser la WAPE 30 j sous 0,265, D et E méritent d'être tentés, mais avec une attente réaliste : les données actuelles (18 mois, forte intermittence, pas de variation de prix catalogue) limitent structurellement ce qu'un modèle peut extraire — c'est le même constat que celui posé en V1 pour les trois modules.

## 6. Garanties (valables pour A, B et C)

- Aucun artefact V1 modifié (verrou SHA-256 vérifié à chaque exécution de tests).
- Périmètre strictement identique à la V1 : 6 fenêtres, 1 662 couples (produit, fenêtre).
- Aucune information postérieure au cutoff utilisée (tests de perturbation pour A, régime strict pour C).
- Aucun réentraînement : A, B et C recombinent ou recalibrent des prédictions V1 figées.
- Aucune écriture Supabase, aucun déploiement.
