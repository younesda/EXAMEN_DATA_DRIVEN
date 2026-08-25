# 42 — Rapport de correction des fuites

> Série « correction » du 2026-08-18, numérotée 42 à 45 pour ne coexister
> avec aucun rapport historique. Elle supersède les rapports antérieurs sans
> les supprimer : chacun conserve son contenu d'origine et porte un bandeau
> d'invalidation. Voir [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md).

Branche : branche d'audit independant dediee. Aucun push, aucune fusion,
aucune écriture Supabase, aucun historique Git réécrit.

---

## 1. Trois fuites, trois mécanismes distincts

| # | Domaine | Mécanisme | Métrique gonflée | Statut |
|---|---|---|---|---|
| F1 | Pricing | `n_lignes` en feature : la cible en est la somme | WAPE 0,4164 | `invalidated_due_to_target_leakage` |
| F2 | Complément panier | catégorie de scoring dérivée de la **cible masquée** | Recall@10 0,437 / NDCG@10 0,213 | `invalidated_due_to_target_category_leakage` |
| F3 | Complément panier (héritage) | évaluation **in-sample**, sans découpe temporelle | Recall@10 0,1006 / NDCG@10 0,0485 | `invalidated_due_to_in_sample_evaluation_without_temporal_split` |

À ces trois fuites s'ajoute **un artefact d'évaluation** (A1) découvert pendant
la correction elle-même : le départage lexical des ex æquo, décrit en §4.

---

## 2. F1 — `n_lignes` dans le pricing

### Mécanisme

`src/pipelines/final_pricing.py`, avant correction :

```python
NUM = ['remise_pct', 'prix_base_xof', 'cout_xof', 'n_lignes']
```

`n_lignes` est le nombre de lignes de commande confirmées du produit-jour. La
cible `quantite` est **exactement la somme des quantités de ces mêmes lignes**.
Le ratio `quantite / n_lignes` est borné à `[1 ; 5]`, de moyenne 1,84 ;
corrélation avec la cible : **0,708**. La variable n'existe qu'une fois la
journée de ventes terminée.

### Preuve indépendante par borne oracle

Sur les mêmes trois fenêtres, un oracle qui connaîtrait la médiane
produit × remise **calculée dans le test lui-même** plafonne à
**0,4866 / 0,4838 / 0,4931**. Une WAPE de 0,4164 est donc *sous le plancher
d'un oracle honnête* : elle est mathématiquement inatteignable sans information
contemporaine de la cible.

### Mesure directe de l'effet

Le pipeline a été réexécuté à l'identique, `n_lignes` retiré et rien d'autre
changé :

| Modèle | Avec `n_lignes` | Sans `n_lignes` | Écart |
|---|---:|---:|---:|
| `LightGBM_calibre` | 0,41637 | **0,56254** | +0,1462 (+35,1 %) |
| `GLM_Tweedie` | 0,42069 | 0,56329 | +0,1426 |
| `GLM_Poisson` | 0,42211 | 0,56307 | +0,1410 |
| `panel_effets_fixes` | 0,42299 | 0,56138 | +0,1384 |
| `hierarchique_categorie` | 0,56272 | 0,56272 | 0 (n'utilisait pas la variable) |
| `baseline_moyenne_produit` | 0,56430 | 0,56430 | 0 |

Les seuls modèles inchangés sont ceux qui n'utilisaient pas la feature — ce qui
confirme que l'écart provient d'elle seule.

### Correction

- `n_lignes` retiré de `final_pricing.py`.
- Registre explicite créé : `src/pricing/feature_registry.py`, 81 variables
  classées, 70 autorisées, 11 interdites. Chaque entrée porte un **timestamp de
  disponibilité**, un statut et une justification.
- `validate_matrix()` est appelée sur la matrice d'entraînement **et**
  d'inférence, et refuse : les variables interdites, toute colonne contenant une
  racine interdite (`log_n_lignes`, `ca_xof_ratio`…), les doublons, et toute
  colonne absente du registre.
- Résultats historiques conservés dans `models/pricing/metadata.invalidated.json`.

---

## 3. F2 — catégorie de la cible masquée

### Mécanisme

`src/experiments/complement_end_to_end.py` et
`complement_candidate_pilot.py`, avant correction :

```python
cat = g.loc[g.produit_key.eq(target), 'categorie'].iloc[0]
...
for y, v in cats.get(cat, {}).items():   # popularite_categorie / reference / rrf
```

La catégorie servant au scoring était celle de **l'article masqué**. Les modèles
`popularite_categorie`, `reference` et `rrf` recevaient donc la catégorie de la
cible à deviner. Cette même catégorie alimentait l'union de candidats : le
Recall@50 candidat était lui aussi gonflé.

### Mesure appariée

`src/experiments/complement_leak_audit.py` rejoue le même périmètre en
comparant la variante fuitée et la variante honnête. La variante fuitée
**reproduit exactement** les chiffres publiés, ce qui identifie la fuite sans
ambiguïté.

| Fenêtre | Fuité (= publié) | Honnête (contexte seul) |
|---|---:|---:|
| F2 — Recall@10 / NDCG@10 | 0,43743 / 0,21264 | 0,06201 / 0,02946 |
| F3 | 0,36044 / 0,18018 | 0,05320 / 0,02493 |
| F4 | 0,33458 / 0,16297 | 0,04758 / 0,02209 |

Bootstrap apparié commande × fenêtre (2 000 tirages, n = 16 014) :
avantage de la fuite = **+0,15977 de NDCG@10**, IC95 **[0,15555 ; 0,16393]**.
Facteur d'inflation ≈ **7×**.

### Effondrement du vivier candidat

| Fenêtre | Recall@50 candidat avant | après |
|---|---:|---:|
| F1 | 0,0000 (non évaluable) | 0,0000 (non évaluable) |
| F2 | 0,8676 | **0,2964** |
| F3 | 0,8895 | **0,2486** |
| F4 | 0,9332 | **0,2241** |

Le gate candidat ≥ 0,50 n'est plus franchi. La couverture candidat annoncée
provenait donc presque entièrement de la catégorie fuitée.

### Correction

Un cœur de scoring unique a été créé : `src/recsys/complement.py`. Sa signature
rend la fuite **structurellement impossible** —

```python
def candidate_scores(context, context_categories, cooccurrence,
                     popularity, category_popularity):
```

aucun paramètre ne permet de transmettre la cible ni l'un de ses attributs
(catégorie, marque, prix). Les trois chemins d'évaluation
(`complement_end_to_end.py`, `complement_candidate_pilot.py`,
`complement_honest_baseline.py`) importent désormais ce module.

---

## 4. A1 — artefact de départage lexical

Découvert **pendant** la correction, en vérifiant un gain qui semblait
prometteur.

La cible du protocole est `sorted(items)[0]`, l'article alphabétiquement premier
du panier. Le classement départageait les ex æquo par ordre alphabétique de
référence produit. Les modèles dont la liste comportait des scores nuls
complétaient donc la fin du Top-20 par des produits à identifiant bas,
mécaniquement favorables : **74 « hits » supplémentaires sur la seule
fenêtre F2**.

Effet sur la conclusion : un premier calcul attribuait à la cooccurrence un gain
de **+18,2 %** de NDCG@10 avec IC95 entièrement positif. Après uniformisation du
départage (scores strictement positifs, complétion par la popularité, départage
par popularité puis permutation déterministe), le gain retombe à **+3,1 %** avec
un IC95 traversant zéro. **Le candidat est rejeté.**

Ce point illustre que l'artefact était plus discret que la fuite elle-même : il
n'aurait pas été détecté par une relecture de code, seulement par le test de
permutation des identifiants désormais en place.

---

## 5. F3 — évaluation in-sample héritée

`src/pipelines/final_recommendation.py` :

```python
orders = b.groupby('order_id').produit_key.apply(...)   # TOUTES les commandes
for oid, ps in orders.items():
    if len(ps) > 1:
        ctx = [pidx[x] for x in ps[:-1]]
        comp[oid] = top(sim[ctx].sum(axis=0), 10, set(ctx))
        ct[oid] = {pidx[ps[-1]]}
```

Trois défauts cumulés :

1. `sim` est la matrice de similarité de la **dernière fenêtre d'entraînement** ;
2. l'évaluation porte sur la **totalité** des commandes, y compris celles ayant
   servi à construire `sim` — aucune séparation temporelle ;
3. la cible masquée est `ps[-1]`, et non `sorted(items)[0]` : périmètre distinct
   du leave-one-item-out.

`Recall@10 0,1006 / NDCG@10 0,0485 / couverture 0,8933` est donc une mesure
in-sample, non comparable et non généralisable. Statut :
`invalidated_due_to_in_sample_evaluation_without_temporal_split`.

---

## 6. Rapports et artefacts supersédés

Voir [`SUPERSEDED_RESULTS.md`](../SUPERSEDED_RESULTS.md) à la racine pour la
liste exhaustive, la date et le motif d'invalidation de chaque élément.

Aucun fichier n'a été supprimé. Les artefacts issus des fuites ont été déplacés
dans `models/advanced/recommendation_ranking/invalidated/` (avec
`INVALIDATION.json` et son propre manifeste SHA-256) et
`models/pricing/metadata.invalidated.json`.

---

## 7. Garde-fous en place

Les tests ne documentent plus les fuites : ils empêchent leur réapparition.

| Fichier | Tests | Garantit |
|---|---:|---|
| `tests/test_pricing_leakage_guards.py` | 15 | registre, absence de `n_lignes` et de ses transformations, perturbation du jour cible, antériorité stricte du train, séparation des décisions |
| `tests/test_complement_leakage_guards.py` | 16 | six garanties : cible inaccessible, catégorie cible inaccessible, masqué absent du contexte, ex æquo neutres, invariance par permutation d'identifiants, aucune information post-cutoff |
| `tests/test_lead_independent_audit.py` | 9 | garde-fous transversaux, étiquetage des résultats invalidés, reproductibilité du forecasting |
| `tests/test_recommendation_ranker_pilot.py` | 11 | lectures bornées en mémoire, gate candidat non franchi, aucune promotion |

Deux tests méritent d'être signalés parce qu'ils sont **auto-vérifiants** :

- `test_perturbing_target_day_sales_leaves_every_feature_unchanged` perturbe les
  ventes du jour cible de +137 et exige que les features de ce jour soient
  identiques — tout en vérifiant que les jours **postérieurs**, eux, bougent.
  Sans ce second contrôle, le test passerait même si les features étaient
  constantes.
- `test_lexical_tiebreak_would_be_detected_by_the_permutation_test` rejoue la
  permutation avec un départage lexical et exige un écart **plus grand** que
  sous départage neutre. Sans lui, la garantie d'invariance serait vide.
