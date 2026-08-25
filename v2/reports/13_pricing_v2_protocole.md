# 13 — Pricing V2 : protocole et audit P0

_Branche `feature/v2-model-improvements`, non fusionnée. Aucun artefact V1 modifié, aucune écriture Supabase, aucun déploiement._

Ce document fixe le périmètre, les définitions et les seuils **avant** toute évaluation d'un candidat. Les mesures qui suivent proviennent de `v2/evaluation/pricing_v2_p0_audit.json`, produit par `v2/pricing/p0_audit.py`. Les seuils sont figés dans `v2/config/pricing_v2_thresholds.json`.

---

## 1. Ce que la V1 a réellement mesuré

Le Pricing V1 est archivé comme **prototype exploratoire**, explicitement pas comme moteur de prix optimal. Son chiffre de référence :

| Élément | Valeur |
|---|---|
| Méthode retenue | `challenger_ml_lightgbm` |
| WAPE quantité | **1,0713** |
| Biais quantité (unités/ligne, définition V1) | **+0,0100** |
| Biais quantité normalisé (recalculé) | **+0,0086** |
| Fenêtres | 3 × 60 jours |
| Grain | produit × jour |
| Effet causal estimé | non |
| Application automatique autorisée | non |

### 1.1 Le WAPE publié est une moyenne de fenêtres, pas un WAPE poolé

Vérification par recalcul :

| Fenêtre | WAPE quantité | Biais V1 (unités/ligne) | Biais normalisé | n_test | SUM\|y\| |
|---|---:|---:|---:|---:|---:|
| 1 | 1,094946 | +0,036089 | +0,029875 | 15 850 | 19 147 |
| 2 | 1,046194 | −0,019574 | −0,015204 | 16 986 | 21 869 |
| 3 | 1,072822 | +0,013501 | +0,011061 | 17 899 | 21 847 |

Moyenne simple = **1,0713207916807075**, contre 1,0713207916807077 publié : écart de 2,2 × 10⁻¹⁶, soit une reconstitution exacte à la précision machine.

**Ce n'est donc pas un WAPE poolé sur les 3 fenêtres.** À l'intérieur d'une fenêtre le WAPE est bien poolé (correct), mais l'agrégation inter-fenêtres pondère les trois fenêtres à égalité alors que leurs volumes diffèrent (19 147 / 21 869 / 21 847). Un WAPE poolé sur l'ensemble vaudrait **1,07030**, soit 0,00102 d'écart (0,10 % relatif).

L'écart est négligeable ici, mais la conséquence méthodologique ne l'est pas : **P1 sera comparé à la V1 avec la moyenne simple**, définition identique au chiffre figé, pour qu'aucune fraction du gain ne provienne d'un changement de formule.

### 1.2 Le « biais » publié n'est pas un biais normalisé

Le code V1 calcule `biais = (pred_qty - y).mean()` (`src/pipelines/pricing_prototype.py:276`). Le chiffre publié **+0,0100** est donc une **moyenne de résidus en unités par ligne produit-jour**, pas le rapport `SUM(yhat − y) / SUM(y)`.

La distinction compte : une moyenne de résidus **dépend du grain**. Les mêmes prévisions agrégées par semaine ou par produit donneraient une autre valeur. Le biais normalisé, lui, est invariant au grain — c'est la raison pour laquelle il avait été retenu côté forecasting, après l'écart constaté entre +2,51 et +0,067 sur des grains différents.

Recalcul du biais normalisé, à partir du biais unitaire, de `n_test` et de `SUM(y)` :

| Fenêtre | Biais unitaire | × n_test ÷ SUM(y) | Biais normalisé |
|---|---:|---|---:|
| 1 | +0,036089 | × 15 850 ÷ 19 147 | **+0,029875** |
| 2 | −0,019574 | × 16 986 ÷ 21 869 | **−0,015204** |
| 3 | +0,013501 | × 17 899 ÷ 21 847 | **+0,011061** |
| **Moyenne** | **+0,010005** | | **+0,008577** |

La moyenne des biais unitaires reproduit exactement le chiffre des métadonnées (0,010005090296477835 contre 0,0100050902964778 publié). La V1 est conforme au seuil de 0,10 sous **les deux** définitions — l'écart n'a donc aucune conséquence sur le verdict V1, et rien n'est corrigé rétroactivement.

En revanche, pour la V2, le critère C2 exige **les deux à la fois** : le biais unitaire (pour rester comparable au chiffre figé) et le biais normalisé (parce qu'il est le seul robuste au grain).

### 1.3 La méthode retenue n'est pas la meilleure en WAPE — et c'était justifié

| Méthode | WAPE F1 | WAPE F2 | WAPE F3 | Biais F1 | Biais F2 | Biais F3 |
|---|---:|---:|---:|---:|---:|---:|
| descriptif_intra_produit | 1,1520 | 1,0804 | 1,1029 | +0,197 | +0,064 | +0,092 |
| **panel_effets_fixes** | **1,0020** | **0,9696** | **0,9842** | **−0,394** | **−0,453** | **−0,448** |
| hierarchique_pooling_categorie | 1,1750 | 1,0969 | 1,1125 | +0,251 | +0,142 | +0,119 |
| **challenger_ml_lightgbm** (retenu) | 1,0949 | 1,0462 | 1,0728 | +0,036 | −0,020 | +0,014 |

`panel_effets_fixes` passe déjà sous 1,00 en WAPE — mais avec un biais de −39 % à −45 %, c'est-à-dire une sous-estimation systématique de près de la moitié du volume. Appliqué à une simulation de marge, ce modèle produirait des marges prévues massivement fausses. La règle de sélection V1 (`|biais| < 0,15, sinon min|biais|`) l'a écarté à juste titre.

**Conséquence pour la V2 : un WAPE plus bas obtenu au prix d'un biais massif ne compte pas comme une amélioration.** C'est la raison d'être du critère C2.

### 1.4 Les prédictions par ligne ne sont pas archivées

La V1 n'a conservé que les métriques agrégées par fenêtre, pas les prédictions ligne à ligne. **P1 doit donc régénérer les prédictions V1 avec le code figé et retrouver exactement les valeurs du tableau 1.1** avant d'appliquer la moindre calibration. Sans cette reproduction, aucun écart V1/P1 ne serait interprétable — il pourrait venir de la calibration comme d'une divergence d'environnement.

---

## 2. Périmètre gelé

### 2.1 Fenêtres — identiques à la V1

| Fenêtre | Fin du train | Test | Jours | Lignes test | Produits | Lignes en promotion |
|---|---|---|---:|---:|---:|---:|
| 1 | 2026-02-01 | 2026-02-02 → 2026-04-02 | 60 | 15 850 | 300 | — |
| 2 | 2026-04-02 | 2026-04-03 → 2026-06-01 | 60 | 16 986 | 300 | — |
| 3 | 2026-06-01 | 2026-06-02 → 2026-07-31 | 60 | 17 899 | 300 | — |

Le pricing utilise **3 fenêtres de 60 jours**, et non les 6 fenêtres de 30 jours du forecasting — écart déjà documenté en V1 (coût de calcul). La V2 conserve ce découpage : le modifier invaliderait toute comparaison.

### 2.2 Population éligible — identique à la V1

| Groupe | Produits | Lignes |
|---|---:|---:|
| `eligible_individuel` | 218 | 103 900 |
| `eligible_pooling_categorie` | 70 | 13 111 |
| `non_eligible` | 12 | 752 |
| **Total** | **300** | **117 763** |

Seuils d'éligibilité repris sans modification : ≥ 30 jours en promotion, ≥ 30 jours hors promotion, ≥ 2 niveaux réels, ≥ 50 unités de volume, ≥ 60 jours d'étalement, ≥ 2 mois couverts.

### 2.3 Niveaux de remise — identiques à la V1

Grille retenue : **5 %, 10 %, 15 %, 20 %, 25 %, 30 %**.

Le niveau **40 % reste exclu** : 11 lignes de support seulement, soit 0,07 % des lignes en promotion. Aucune extrapolation hors grille n'est autorisée.

### 2.4 Règles de marge — identiques à la V1, avec une ambiguïté à lever

Planchers testés : 0 %, 5 %, 10 %, 15 %. Plancher principal : **5 %**.

L'audit révèle une ambiguïté de définition qu'il faut trancher **avant** d'évaluer quoi que ce soit :

- le simulateur V1 applique `prix_simulé ≥ coût × (1 + plancher)` — c'est un **taux de marque sur le coût** ;
- la colonne `taux_marge` du projet est définie comme `marge_unitaire / prix_payé` — c'est un **taux de marge sur le prix**.

Sous la première définition, la V1 a **0 violation**. Sous la seconde, elle en a **5** :

| Produit | Coût | Prix catalogue | Remise retenue | Prix simulé | Marge sur prix |
|---|---:|---:|---:|---:|---:|
| PRD000238 | 4 999 | 6 190 | 15 % | 5 261,5 | 4,99 % |
| PRD000241 | 15 513 | 23 320 | 30 % | 16 324,0 | 4,97 % |
| PRD000266 | 52 622 | 79 080 | 30 % | 55 356,0 | 4,94 % |
| PRD000268 | 44 164 | 61 970 | 25 % | 46 477,5 | 4,98 % |
| PRD000272 | 168 904 | 221 980 | 20 % | 177 584,0 | 4,89 % |

Les écarts sont minimes (4,89 % à 4,99 % contre 5,00 %) et le code V1 est cohérent avec sa propre définition — ce n'est pas un bug, c'est une convention non explicitée. **La V2 exigera zéro violation sous les deux définitions**, ce qui la rend strictement plus sévère que la V1. Ce durcissement est déclaré ici, avant évaluation, et n'est pas une correction rétroactive de la V1 : les artefacts V1 restent inchangés.

---

## 3. Grain : ce qu'une ligne représente vraiment

| Mesure | Valeur |
|---|---:|
| Lignes du panel | 117 763 |
| Couples produit × jour distincts | 117 763 |
| Doublons | 0 |
| Produits | 300 |
| Jours couverts | 546 |
| Grille complète théorique (300 × 546) | 163 800 |
| Panel = grille complète ? | **non** (71,9 %) |
| Jours couverts par produit (min / médiane / max) | 35 / 464,5 / 546 |
| Lignes à quantité nulle | 59 786 (50,8 %) |

**Une ligne du panel n'est pas une ligne transactionnelle** : elle agrège toutes les ventes d'un produit sur une journée. Le WAPE V1 est donc un **WAPE produit-jour**, pas un WAPE par transaction ni un WAPE sur quantités cumulées.

C'est exactement le piège déjà rencontré en forecasting, où le WAPE quotidien vaut 1,09 et le WAPE en cumul 30 jours 0,277 — un facteur 4 pour les mêmes prévisions. **Aucun chiffre de pricing V2 ne sera comparé à un chiffre calculé sur un autre grain.**

Deux points à garder en tête pour l'interprétation :

- le panel n'est pas une grille complète : les 28,1 % manquants correspondent à des produits absents du catalogue sur une partie de la période, pas à des jours de vente nulle supprimés ;
- la moitié des lignes ont une quantité nulle. Sur une cible aussi intermittente, un WAPE supérieur à 1 n'a rien d'anormal — mais il signifie aussi qu'une prédiction constante à zéro ferait aussi bien, ce qui justifie que le seuil C1 soit fixé à 1,00 et pas plus haut.

---

## 4. Connaissance des promotions au cutoff — hypothèse non vérifiable

Le simulateur et les modèles utilisent `remise_planifiee_pct` comme variable connue à l'avance. Cela suppose que le calendrier promotionnel — dates et taux — est décidé avant le cutoff de chaque fenêtre.

**Cette hypothèse ne peut pas être vérifiée.** La table `dim_promotion` (120 lignes) expose exactement sept colonnes :

`promo_key`, `promotion_id`, `portee`, `cible`, `remise_pct`, `date_debut`, `date_fin`.

Il n'existe **aucune date de création, d'annonce ou de validation**. Rien ne permet donc de prouver qu'une promotion démarrant après le cutoff était déjà décidée à ce cutoff.

**Conséquence assumée** : l'hypothèse est retenue par continuité avec la V1, mais si elle est fausse, toutes les performances mesurées — V1 comme V2 — sont optimistes. Aucune conclusion de la V2 ne devra reposer sur cette seule hypothèse. La donnée à demander au métier est explicite : **la date de création ou d'annonce des promotions**.

---

## 5. Support réel : où le modèle a vraiment de quoi apprendre

### 5.1 Volumétrie

| Mesure | Valeur |
|---|---:|
| Lignes en promotion | 15 524 (13,2 %) |
| Lignes hors promotion | 102 239 (86,8 %) |
| Produits sans aucune promotion | 12 |
| Produits sans aucune observation hors promotion | **0** |

Le contraste est net : hors promotion, le support est confortable (médiane de 404,5 jours par produit, minimum 24). En promotion, il est mince (médiane 45 jours, minimum 6).

### 5.2 Par produit et par niveau

| Mesure | Valeur |
|---|---:|
| Produits avec ≥ 2 niveaux de remise observés | **263** |
| Produits avec 1 seul niveau | 25 |
| Nombre médian de niveaux par produit | 3,5 |
| Cellules produit × niveau observées | 1 012 sur 1 800 (**56,2 %**) |
| Cellules à moins de 10 observations | 299 (29,5 % des cellules observées) |

> **Réconciliation reprise de la V1** : le chiffre de référence est bien **263 produits** avec au moins 2 niveaux de remise, et non 288. L'écart venait du rapport 11, qui comptait le niveau 0 % comme un niveau de remise.

Près de la moitié des combinaisons produit × niveau n'ont jamais été observées, et près d'un tiers de celles qui existent reposent sur moins de 10 observations. C'est la contrainte structurelle centrale du pricing sur ce jeu de données.

### 5.3 Support des simulations V1

Sur les sorties du simulateur au plancher principal de 5 % :

| Mesure | Valeur |
|---|---:|
| Lignes (300 produits × 4 objectifs, moins non éligibles) | 1 152 |
| Remise recommandée non nulle | 688 |
| dont **sans support individuel** (repli pooling catégorie) | **216 (31,4 %)** |
| Remise hors grille observée | 0 |
| Prix sous le coût | 0 |
| Niveau de confiance « haute » | 0 (structurellement inatteignable, WAPE 1,07 > 0,5) |

Ces 31,4 % constituent la référence du critère C6.

---

## 6. Déséquilibre du plan d'expérience

### 6.1 Répartition des niveaux

| Niveau | Part des lignes en promotion |
|---|---:|
| 5 % | 24,5 % |
| 10 % | 22,6 % |
| 15 % | 23,0 % |
| 20 % | 13,0 % |
| 25 % | 9,1 % |
| 30 % | 7,8 % |
| 40 % | 0,07 % (exclu) |

### 6.2 Répartition dans le temps

La part de lignes en promotion varie de **4,2 % à 28,8 % selon le mois** — un facteur 7.

> **Réconciliation reprise de la V1** : le dénombrement de référence des campagnes est celui de `dim_promotion`, soit **120 campagnes réelles**. Le chiffre de 1 518 apparu en cours de V1 comptait des séquences promotionnelles consécutives au niveau produit, pas des campagnes.

**Conséquence** : les niveaux de remise ne sont ni également représentés, ni uniformément répartis dans le temps. Toute comparaison brute entre niveaux confond donc effet prix et effet calendrier. C'est le fondement du critère C8.

---

## 7. Stabilité temporelle de l'uplift observé

Uplift descriptif = quantité moyenne à un niveau de remise ÷ quantité moyenne hors promotion, par semestre. **Ce n'est pas un effet causal** : c'est une différence de moyennes sur un plan déséquilibré, mesurée uniquement pour juger de sa fiabilité.

| Niveau | P1 (02/2025 → 10/2025) | P2 (11/2025 → 07/2026) | Écart relatif |
|---|---:|---:|---:|
| 5 % | 1,065 | **0,827** | 22,3 % |
| 10 % | 1,146 | **1,553** | 35,5 % |
| 15 % | 1,231 | 1,042 | 15,4 % |
| 20 % | 1,216 | 1,229 | 1,1 % |
| 25 % | **1,788** | **1,747** | 2,3 % |
| 30 % | 1,285 | 1,338 | 4,2 % |

Écart relatif médian : **9,8 %**. Maximum : **35,5 %**.

Deux constats qui pèsent lourd :

1. **L'uplift n'est pas monotone en la remise.** 25 % produit le plus fort uplift observé (≈ 1,77), plus élevé que 30 % (≈ 1,31). Une relation prix-quantité réelle ne se comporte pas ainsi ; ce classement reflète le calendrier des campagnes, pas une élasticité.
2. **Le niveau 5 % passe sous 1 en seconde période (0,827)** : sur ce semestre, les jours à 5 % de remise se vendent *moins* que les jours hors promotion. Une lecture causale naïve conclurait qu'une petite remise fait baisser les ventes — ce qui n'est évidemment pas ce que mesure ce chiffre.

Les niveaux les plus stables (20 %, 25 %, 30 %) sont aussi les moins représentés (13,0 %, 9,1 %, 7,8 %) : leur stabilité n'est pas un gage de fiabilité, elle vient d'un support étroit et concentré sur quelques campagnes.

**Un uplift instable et non monotone ne peut pas fonder une recommandation de prix.** C'est la limite que la V2 doit garder en vue, indépendamment de tout gain de WAPE.

---

## 8. Seuils d'acceptation — figés avant évaluation

Fichier : `v2/config/pricing_v2_thresholds.json`. Règle transverse : **un critère non évaluable compte comme ÉCHOUÉ**, jamais comme neutre.

| Critère | Exigence | Référence V1 |
|---|---|---|
| **C1 — Précision** | WAPE quantité < 1,00 (moyenne simple des 3 fenêtres) | 1,0713 → échoue |
| **C2 — Biais** | \|biais unitaire\| ≤ 0,10 **et** \|biais normalisé\| ≤ 0,10 | +0,0100 / +0,0086 → conforme |
| **C3 — Robustesse** | amélioration stricte du WAPE sur ≥ 2 fenêtres sur 3 | — |
| **C4 — Garde-fou marge** | 0 violation, sous les **deux** définitions du plancher | 0 sur coût / 5 sur prix |
| **C5 — Aucune extrapolation** | 0 remise hors {0, 5, 10, 15, 20, 25, 30} % | 0 |
| **C6 — Hors support** | ≤ 28,3 % des simulations à remise non nulle | 31,4 % |
| **C7 — Stabilité des remises** | non dégradée face à la V1, mesurée identiquement | à mesurer dans P1 |
| **C8 — Aucune revendication causale** | booléen, aucune tolérance | respecté |
| **C9 — Application automatique** | reste interdite quel que soit le résultat | interdite |

### Règle de décision

- **Validation complète** : C1 à C7 satisfaits, C8 et C9 respectés → le candidat devient le moteur de simulation principal.
- **Challenger documenté** : C2 à C7 satisfaits mais C1 échoué → amélioration réelle, mais le pricing reste exploratoire.
- **Rejet** : tout autre cas.

**Aucun seuil ne sera modifié après observation des résultats.** C'est la règle appliquée en Forecasting V2 (C3 conservé alors que C2 s'est révélé marginalement meilleur sur la classe A) et en Recommandation V2 (pénalité de R2 non réajustée).

Deux critères ne peuvent structurellement pas être levés par un meilleur modèle :

- **C9** ne dépend pas de la précision. Les remises simulées n'ont jamais été appliquées ; aucune évaluation off-policy n'est possible. Un WAPE de 0,5 ne rendrait pas l'application automatique acceptable.
- **C8** dépend du plan d'expérience, pas du modèle. Tant que les campagnes ne sont pas randomisées ou instrumentées, aucune méthode ne produira d'effet causal à partir de ces données.

---

## 9. Candidat P1 — périmètre autorisé

**Un seul candidat est autorisé à ce stade.** P2 et P3 ne sont pas lancés.

P1 = **recalibration des prédictions V1**, sans changer de modèle :

1. régénérer les prédictions V1 avec le code figé et **vérifier la reproduction exacte** des WAPE et biais par fenêtre du §1.1 ;
2. estimer un facteur de calibration **sur les seules fenêtres strictement antérieures** ;
3. tester une calibration **globale** ;
4. tester une calibration **par catégorie**, uniquement là où le support est suffisant ;
5. **régulariser vers le facteur global** quand le support par catégorie est faible.

**Contrainte absolue de conception** : la fenêtre évaluée ne contribue jamais à son propre facteur de calibration. La fenêtre 1 n'a aucune fenêtre antérieure — elle utilisera donc un facteur neutre (1,0), et cette absence d'information sera comptée telle quelle, pas masquée.

C'est précisément le point qui a fait échouer le candidat A du forecasting : son gain apparent venait entièrement du poids par défaut appliqué à la fenêtre 1, faute de fenêtre antérieure. Le même piège est explicitement surveillé ici.

---

## 10. Garanties

- Fenêtres, population éligible, grille de remise et règles de marge **identiques à la V1**.
- Définitions de WAPE et de biais **reprises telles quelles**, y compris l'agrégation par moyenne simple, et reconstituées par recalcul.
- Seuils figés **avant** toute évaluation, dans un fichier versionné.
- Hypothèse de connaissance des promotions au cutoff **déclarée non vérifiable**.
- Aucun artefact V1 modifié, aucune écriture Supabase, aucun déploiement, aucune fusion dans `main`.
- **P2 et P3 non démarrés.**
