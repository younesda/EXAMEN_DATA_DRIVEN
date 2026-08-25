# 04 — Candidat C : recalibration des intervalles

_Généré le 2026-08-15T03:45:27.216323+00:00. Branche `feature/v2-model-improvements`._

**Statut : `experiment_retained` — raison : `interval_calibration_improved`**

**Portée : intervalles uniquement — la prévision centrale est strictement celle de la V1.** Aucune métrique de prévision centrale (WAPE, biais) ne change — elles restent strictement celles de la V1.

## 1. Variantes comparées

| Variante | Calibration | Régime temporel |
|---|---|---|
| **C0** | Globale par bucket d'horizon | Leave-one-window-out (**méthode V1**) |
| **C1** | Globale par bucket d'horizon | Fenêtres antérieures uniquement |
| **C2** | Par classe ABC × bucket | Fenêtres antérieures uniquement |
| **C3** | Par ABC × profil de demande × bucket | Fenêtres antérieures uniquement |

Repli automatique si un groupe compte moins de 30 résidus : on retombe sur la calibration du bucket d'horizon seul, et si celle-ci est elle aussi trop pauvre, le point est marqué **non calibrable** plutôt que calibré au jugé.

**La fenêtre 1 est structurellement non calibrable en régime strict** (aucune fenêtre antérieure) : elle est exclue du calcul, jamais comblée par une calibration inventée. C'est ce qui explique la part non calibrable des variantes C1 à C3.

## 2. Niveau 80 % — résultat principal

| Variante | Couverture globale | Couverture produits A | Largeur moyenne | Part non calibrable | Intervalles excessivement larges |
|---|---:|---:|---:|---:|---:|
| C0 (référence V1) | 0.7988 | 0.7439 | 3.6042 | 0.0000 | 0.0000 |
| C1 global strict | 0.8175 | 0.7659 | 3.5993 | 0.1486 | 0.0000 |
| C2 par ABC | 0.8178 | 0.8027 | 3.5973 | 0.1486 | 0.0000 |
| C3 par ABC × profil | 0.8110 | 0.7903 | 3.5951 | 0.1486 | 0.0000 |

**Cible : couverture dans [78%, 84%], globalement ET sur les produits A.**

| Variante | Globale dans la cible ? | Produits A dans la cible ? |
|---|:---:|:---:|
| C0 (référence V1) | ✅ | ❌ |
| C1 global strict | ✅ | ❌ |
| C2 par ABC | ✅ | ✅ |
| C3 par ABC × profil | ✅ | ✅ |

## 3. Couverture par classe ABC (niveau 80 %)

| Variante | A | B | C |
|---|---:|---:|---:|
| C0 (référence V1) | 0.7439 | 0.8053 | 0.8213 |
| C1 global strict | 0.7659 | 0.8201 | 0.8409 |
| C2 par ABC | 0.8027 | 0.8091 | 0.8309 |
| C3 par ABC × profil | 0.7903 | 0.8038 | 0.8260 |

## 4. Largeur moyenne par classe ABC (niveau 80 %)

_Contrôle anti-triche : une couverture correcte obtenue en élargissant sans discernement n'est pas une amélioration._

| Variante | A | B | C |
|---|---:|---:|---:|
| C0 (référence V1) | 3.7657 | 3.6172 | 3.5163 |
| C1 global strict | 3.7653 | 3.6186 | 3.5053 |
| C2 par ABC | 3.8730 | 3.6417 | 3.4331 |
| C3 par ABC × profil | 3.8686 | 3.6116 | 3.4506 |

## 5. Stabilité entre fenêtres (couverture, niveau 80 %)

| Variante | F1 | F2 | F3 | F4 | F5 | F6 |
|---|---:|---:|---:|---:|---:|---:|
| C0 (référence V1) | 0.7528 | 0.8062 | 0.7943 | 0.8107 | 0.7961 | 0.8256 |
| C1 global strict | non calibrable | 0.8366 | 0.8084 | 0.8188 | 0.7991 | 0.8256 |
| C2 par ABC | non calibrable | 0.8364 | 0.8137 | 0.8185 | 0.7959 | 0.8258 |
| C3 par ABC × profil | non calibrable | 0.8279 | 0.7941 | 0.8101 | 0.7997 | 0.8236 |

## 6. Niveau 95 %

| Variante | Couverture globale | Couverture produits A | Largeur moyenne |
|---|---:|---:|---:|
| C0 (référence V1) | 0.9497 | 0.9305 | 6.0238 |
| C1 global strict | 0.9569 | 0.9414 | 5.9912 |
| C2 par ABC | 0.9564 | 0.9529 | 5.9611 |
| C3 par ABC × profil | 0.9507 | 0.9500 | 5.9235 |

## 7. Lecture du résultat

**La variante retenue est `C3 par ABC × profil`.** Elle corrige le défaut documenté de la V1 :

- Couverture des produits A : 0.7439 (V1) → 0.7903 (+0.0464), désormais dans la cible [78%, 84%].
- Couverture globale : 0.8110, également dans la cible.
- Coût en largeur d'intervalle : 3.6042 → 3.5951 (-0.3%).

Le gain n'est donc **pas** obtenu en élargissant aveuglément : la largeur reste comparable, seule sa répartition entre segments change (plus large là où l'incertitude est réellement plus forte, plus étroite ailleurs).

### C2 vs C3 : un choix serré, pas une victoire nette

Écart absolu au niveau nominal de 80 % (plus bas = mieux calibré) :

| Variante | Écart global | Écart produits A | Somme des écarts | Écart maximal | Largeur moyenne |
|---|---:|---:|---:|---:|---:|
| C0 (référence V1) | +0.12 pp | +5.61 pp | 5.73 pp | 5.61 pp | 3.6042 |
| C1 global strict | +1.75 pp | +3.41 pp | 5.15 pp | 3.41 pp | 3.5993 |
| C2 par ABC | +1.78 pp | +0.27 pp | 2.05 pp | 1.78 pp | 3.5973 |
| C3 par ABC × profil | +1.10 pp | +0.97 pp | 2.07 pp | 1.10 pp | 3.5951 |

**C2 et C3 sont pratiquement à égalité** (somme des écarts : 2,05 pp contre 2,07 pp). La règle de sélection fixée a priori — « parmi les variantes conformes, la largeur moyenne la plus faible » — retient **C3**, mais elle ne les départage que de 0,06 % de largeur, ce qui n'est pas un écart significatif.

Le vrai arbitrage est ailleurs, et il est explicite :

- **C2** est meilleur sur les produits A précisément (écart 0,27 pp contre 0,97 pp) — or c'est le défaut documenté que ce candidat visait à corriger.
- **C3** est meilleur en pire cas (écart maximal 1,10 pp contre 1,78 pp) et légèrement plus économe en largeur.

Les deux sont défendables. Ce rapport conserve C3 parce que c'est ce que désigne la règle fixée **avant** l'expérience — changer la règle après avoir vu les chiffres serait exactement le biais que le protocole cherche à éviter. **Mais le choix entre C2 et C3 mérite une décision explicite plutôt qu'un départage automatique à 0,06 %** ; si la priorité métier est la fiabilité des produits A, C2 est le meilleur choix.

**Point méthodologique important** : C1 à C3 utilisent le régime strict (fenêtres antérieures uniquement), plus exigeant que la méthode V1 (leave-one-window-out, qui utilise aussi les fenêtres futures). Une comparaison directe C0 vs C2 mélange donc deux effets — le changement de régime temporel et la calibration par segment. C1 est là précisément pour les séparer : **C1 vs C0** isole le coût du passage au régime strict, **C2 vs C1** isole le gain réel de la segmentation.

## 8. Coût de calcul

- Durée totale : **11.51 s** (2 niveaux × 4 variantes)
- Mémoire résidente : 222.3 Mo
- Réentraînement : **non** — recalibration sur les résidus des prédictions V1 figées

## 9. Garanties

- **Prévision centrale strictement inchangée** : aucune métrique WAPE/biais n'est affectée.
- Résidus de calibration issus **exclusivement** des fenêtres antérieures (variantes C1-C3).
- Fenêtre 1 marquée non calibrable, jamais comblée artificiellement.
- Bornes de quantité toujours ≥ 0.
- Aucun artefact V1 modifié.
