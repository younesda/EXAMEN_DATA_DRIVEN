# 06 — E0 : audit de disponibilité des variables métier

_Généré le 2026-08-15T11:56:58.711042+00:00. Aucune variable n'entre dans un modèle E sans un statut prouvé ici._

## 1. Statut de chaque variable

| Variable | Statut | Utilisable en E ? | Groupe |
|---|---|:---:|---|
| jour_semaine / est_weekend | `connue_sur_tout_horizon` | ✅ | E1_calendrier |
| mois / trimestre / semaine | `connue_sur_tout_horizon` | ✅ | E1_calendrier |
| fin d'année (est_noel, avant_noel, apres_noel, est_nouvel_an…) | `connue_sur_tout_horizon` | ✅ | E1_calendrier |
| fêtes religieuses (Korité, Tabaski, Magal, Maouloud, Tamxarit, Ramadan) | `connue_sur_tout_horizon` | ✅ | E1_calendrier |
| en_promotion / remise_pct / n_promotions / portee_promo | `connue_sur_tout_horizon` | ✅ | E2_promotions |
| age_version_produit_jours | `connue_sur_tout_horizon` | ✅ | E3_age_version |
| stock_disponible_lag1 (état initial au cutoff) | `connue_a_j_moins_1_seulement` | ✅ | E4_stock_initial |
| stock du jour (stock_fin_jour) | `interdite_pour_fuite` | ❌ | — |
| ventes du jour (y) et dérivés contemporains | `interdite_pour_fuite` | ❌ | — |
| web_purchase contemporain | `interdite_pour_fuite` | ❌ | — |
| prix payé réel / remise appliquée réelle | `indisponible_dans_le_futur` | ❌ | — |

## 2. Justifications et réserves

### jour_semaine / est_weekend

- **Statut** : `connue_sur_tout_horizon`
- Déterministe : dérivée du calendrier civil, calculable pour n'importe quelle date future.

### mois / trimestre / semaine

- **Statut** : `connue_sur_tout_horizon`
- Déterministe, même raison.

### fin d'année (est_noel, avant_noel, apres_noel, est_nouvel_an…)

- **Statut** : `connue_sur_tout_horizon`
- Dates fixes du calendrier, connues des années à l'avance.
- **Réserve** : Aucune fenêtre de backtest ne couvre décembre — l'effet fin d'année ne peut donc pas être validé empiriquement ici (limite déjà documentée en V1).

### fêtes religieuses (Korité, Tabaski, Magal, Maouloud, Tamxarit, Ramadan)

- **Statut** : `connue_sur_tout_horizon`
- Reconstruites par `src/features/calendar.py` ; dates connues à l'avance.

### en_promotion / remise_pct / n_promotions / portee_promo

- **Statut** : `connue_sur_tout_horizon`
- `dim_promotion` fournit `date_debut` et `date_fin` pour 120 campagnes : la période de validité couvre bien l'horizon futur.
- ⚠️ AUCUNE colonne de date de création/décision n'existe dans `dim_promotion` (colonnes réelles : ['promo_key', 'promotion_id', 'portee', 'cible', 'remise_pct', 'date_debut', 'date_fin']). On ne peut donc PAS prouver qu'une promotion active en J+15 était déjà décidée au cutoff. HYPOTHÈSE ASSUMÉE : le calendrier promotionnel est un plan arrêté à l'avance, donc connu au moment de la prévision. Si cette hypothèse est fausse en production, `en_promotion` et `remise_pct` devront être neutralisés sur l'horizon.

### age_version_produit_jours

- **Statut** : `connue_sur_tout_horizon`
- Calculée comme (date cible − `date_debut_validite`) : la date de début de validité est connue au cutoff et la date cible est déterministe.
- **Réserve** : Nommée `age_version_produit_jours` et NON « ancienneté commerciale » : `date_debut_validite` est la date de début de validité de la ligne SCD, dont la sémantique métier exacte n'a jamais pu être prouvée (cf. audit V1).

### stock_disponible_lag1 (état initial au cutoff)

- **Statut** : `connue_a_j_moins_1_seulement`
- Le stock de la veille du cutoff est connu. Mais il n'est PAS projetable sur J+1..J+30 : mesuré sur les données, le rapport stock(J+30)/stock(J-1) a une médiane de 0.823, un p10 de 0.529 et un p90 de 3.360 ; 59.3% des cas varient de plus de 20 %. Le tenir constant sur 30 jours serait une hypothèse fausse et non documentée.
- **Restriction d'usage** : Utilisable UNIQUEMENT pour caractériser l'état initial (une valeur par produit×fenêtre, constante sur l'horizon en tant que *caractéristique du cutoff*, jamais présentée comme le stock réel du jour J+k).

### stock du jour (stock_fin_jour)

- **Statut** : `interdite_pour_fuite`
- Contemporaine de la cible : inconnue au moment de la prévision.

### ventes du jour (y) et dérivés contemporains

- **Statut** : `interdite_pour_fuite`
- C'est la cible elle-même.

### web_purchase contemporain

- **Statut** : `interdite_pour_fuite`
- Un événement web `purchase` du jour J peut être le miroir direct de la vente du jour J (déjà écarté en V1 pour cette raison).

### prix payé réel / remise appliquée réelle

- **Statut** : `indisponible_dans_le_futur`
- Observés a posteriori seulement (calculés depuis le montant net encaissé). Le prix catalogue, lui, est connu — et fixe pour 300/300 produits.

## 3. Preuve chiffrée : le stock J−1 n'est pas projetable sur 30 jours

Le protocole demandait explicitement de ne pas rendre le stock « artificiellement constant sur tout l'horizon sans justification ». Mesure directe sur les données :

| Indicateur | Valeur |
|---|---:|
| Paires (stock J−1, stock J+30) comparées | 108,463 |
| Ratio médian stock(J+30) / stock(J−1) | 0.823 |
| Ratio p10 | 0.529 |
| Ratio p90 | 3.360 |
| **Part des cas variant de plus de 20 %** | **59.3%** |

**Conclusion : dans 59.3% des cas le stock a bougé de plus de 20 % en 30 jours** (et le p90 atteint 3.36, soit plus du triple). Le maintenir constant sur l'horizon serait une hypothèse manifestement fausse. En E4, il n'est donc utilisé que comme **caractéristique de l'état initial au cutoff**, jamais comme une estimation du stock au jour J+k.

## 4. Promotions : hypothèse à assumer explicitement

`dim_promotion` contient 120 campagnes, avec les colonnes : `promo_key, promotion_id, portee, cible, remise_pct, date_debut, date_fin`.

**Aucune colonne de date de création ou de décision n'existe** (recherche effectuée : aucune correspondance). On dispose donc de la période de validité d'une promotion, mais pas du moment où elle a été décidée.

**Hypothèse assumée pour E2** : le calendrier promotionnel est un plan arrêté à l'avance, donc connu au cutoff. C'est la même hypothèse que celle déjà documentée en V1. Elle est **non vérifiable avec les données actuelles** — si elle s'avérait fausse en production, les variables de promotion devraient être neutralisées sur l'horizon, et les résultats de E2 à E4 seraient invalidés.

## 5. Groupes d'ablation retenus

| Étape | Contenu |
|---|---|
| `E1_calendrier` | features calendaires déterministes |
| `E2_promotions` | E1 + promotions planifiées (sous hypothèse explicite) |
| `E3_age_version` | E2 + age_version_produit_jours |
| `E4_stock_initial` | E3 + état de stock au cutoff (jamais projeté) |

Le groupe calendaire compte 49 variables déterministes déjà implémentées et testées en V1 (`src/features/calendar.py`), incluant les fêtes sénégalaises et la fenêtre du Ramadan.

## 6. Variables exclues

Trois variables sont **interdites pour fuite** (stock du jour, ventes du jour, `web_purchase` contemporain) et une est **indisponible dans le futur** (prix payé réel). Aucune n'entrera dans un modèle E, quelle que soit son pouvoir prédictif apparent.
