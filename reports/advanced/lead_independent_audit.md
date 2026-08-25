# Audit indépendant et décision

> **Mise à jour du 2026-08-18 — corrections appliquées.** Ce document est le
> rapport d'audit initial. Les fuites qu'il identifie ont depuis été corrigées :
> pricing `invalidated_due_to_target_leakage`, complément panier
> `invalidated_due_to_target_category_leakage` et
> `invalidated_due_to_in_sample_evaluation_without_temporal_split`. Les chiffres
> 0,4164 et 0,437 / 0,213 cités ci-dessous le sont **en tant que valeurs
> invalidées**. Résultats en vigueur : [`SUPERSEDED_RESULTS.md`](../../SUPERSEDED_RESULTS.md)
> et la série [17](../42_leakage_correction_report.md)–[20](../45_final_corrected_decision.md).

Branche de travail : branche d'audit independant dediee, créée depuis
`experiment/recommendation-advanced-ranking` (`ff5c076`). Aucune fusion, aucun
push, aucune écriture Supabase. Les artefacts validés existants sont inchangés.

---

## 1. Réponse à la question posée

> Peux-tu améliorer significativement le forecasting, le pricing ou la
> recommandation avec les données actuelles, sans modifier le périmètre ni
> manipuler les métriques ?

**Non — aucun modèle n'est promouvable sur les trois domaines.** En revanche
l'audit a établi que **deux des trois références annoncées sont invalides** :
elles utilisent une information indisponible au moment de la décision. La
valeur produite ici n'est pas un gain de score, c'est la correction de la base
de comparaison et la quantification honnête de la marge réellement disponible.

| Domaine | Potentiel | Référence annoncée | Statut réel après audit |
|---|---|---|---|
| Forecasting 30 j | **faible** | WAPE30 0,25831 | **valide et reproduite à l'identique** ; marge résiduelle ≤ 5 % |
| Pricing | **faible** | WAPE 0,4164 | **invalide — fuite `n_lignes`** ; plancher honnête ≈ 0,52–0,55 |
| Recommandation complément panier | **faible** | Recall@10 0,437 / NDCG@10 0,213 | **invalide — fuite catégorie de la cible** ; valeurs honnêtes ≈ 7 × plus basses |
| Recommandation prochain achat | faible | popularité globale | valide, conclusion confirmée |

---

## 2. Reproduction indépendante de la référence forecasting

Recalcul intégral depuis `models/advanced/forecasting/direct_lightgbm_predictions.parquet`
(54 000 lignes = 300 produits × 30 horizons × 6 fenêtres, aucune population réduite) :

| Métrique | Valeur annoncée | Valeur recalculée |
|---|---:|---:|
| WAPE30 macro (moyenne des 6 fenêtres) | 0,25831 | **0,2583140754** |
| WAPE30 micro poolée | 0,25743 | **0,2574324397** |
| Forecast bias | −0,02593 | **−0,0258949** |
| WAPE quotidienne macro | 1,0870 | **1,0869756** |

Par fenêtre : 0,26794 / 0,28876 / 0,24894 / 0,25868 / 0,25282 / 0,23274.

**La référence forecasting est exacte.** L'audit de fuite du pipeline
(`src/experiments/advanced_forecasting.py`) est également négatif : le filtre
d'entraînement porte sur `target_ds <= test_start − 1 j`, le tuning utilise un
pseudo-cutoff à `test_start − 31 j`, et toutes les features dérivées sont
`shift`/`rolling`/`expanding` arrière. La seule information future est
`planned_discount` (remise du calendrier promotionnel à la date cible), qui est
une hypothèse métier explicite, documentée et déjà ablatée.

---

## 3. Forecasting — potentiel faible, borne quantifiée

### Justification fondée sur les données

Le modèle est déjà proche d'un **oracle de niveau** qui connaîtrait le futur :

| Estimateur | WAPE30 micro | Nature |
|---|---:|---|
| Oracle : moyenne par produit des 6 totaux réels | **0,24361** | utilise le futur |
| **Référence `LightGBM_direct_per_horizon`** | **0,25743** | honnête |
| Meilleur ré-étalonnage global oracle (×0,985) | 0,25713 | utilise le futur |
| Oracle : moyenne par produit hors fenêtre courante | 0,29233 | utilise le futur |

Le modèle est à **5,4 % relatif** d'un oracle qui connaîtrait le niveau moyen
de chaque produit sur toute la période de test. Le plancher de bruit est du même
ordre : les totaux produit×fenêtre valent en moyenne 33,1 unités, la
sur-dispersion journalière mesurée est `var/moyenne ≈ 2,77`, ce qui place le
plancher binomial-négatif autour de **0,22**. Le ré-étalonnage global optimal ne
rapporte que **0,1 %** : il n'existe pas de biais systématique exploitable.

L'écart 0,2574 → 0,22 n'est atteignable qu'en prédisant l'écart de chaque
fenêtre à son propre niveau produit, c'est-à-dire l'essentiel du bruit.
**Un objectif de WAPE 0,15 est hors d'atteinte** et cette conclusion, déjà posée
sur `experiment/wape15-stretch-goal`, est ici confirmée par une borne oracle
indépendante.

### Méthode réellement nouvelle testée

Le pilote antérieur (branche wape15) avait comparé quatre familles cumulatives
**sans remise future**, alors que la référence, elle, utilise `planned_discount`.
La comparaison était donc défavorable aux challengers. J'ai corrigé ce biais et
testé la piste non couverte : **l'alignement de la perte sur la métrique**.

`WAPE30 = Σ_produits |Σ_h pred − Σ_h y| / Σ y` est une perte L1 sur le **total**
30 jours ; son optimum est la médiane conditionnelle du total. Or la référence
entraîne 30 modèles journaliers sous perte Tweedie, c'est-à-dire des espérances
journalières. `src/experiments/cumulative_l1_forecasting.py` apprend directement
`y30 = Σ y[J+1..J+30]` sous perte L1, avec les mêmes features au cutoff plus les
agrégats de calendrier et de remise planifiée sur la fenêtre cible (même
hypothèse que la référence). Périmètre, fenêtres, population et grain identiques,
tuning sur pseudo-cutoff strictement antérieur.

| Candidat (pilote F1–F2) | F1 | F2 | Moyenne | Gate ≤ 0,26443 |
|---|---:|---:|---:|---|
| Référence `direct_per_horizon` | 0,26794 | 0,28876 | **0,27835** | — |
| Cumulatif L1 (nouveau) | 0,27861 | 0,29447 | 0,28654 | non |
| Cumulatif Tweedie | 0,28479 | 0,29836 | 0,29158 | non |
| Mélange 50/50 prédéfini | 0,27043 | 0,28958 | 0,28000 | non |

**Gate échoué, exécution six fenêtres non lancée.** La perte L1 bat bien la perte
Tweedie au grain cumulatif (−1,7 %), ce qui valide la direction théorique, mais
sans compenser la perte d'information de la décomposition par horizon. Le
cumulatif L1 est néanmoins le meilleur candidat cumulatif direct jamais obtenu
sur ce projet (0,28654 contre 0,29168 pour CatBoost).

- **Coût** : ≈ 80 s CPU, 12 modèles, pas de GPU.
- **Risque de fuite / surapprentissage** : faible ; contrôle de périmètre
  automatique (assertion sur l'appariement produit×fenêtre avec la référence).
- **Seuil de promotion** : WAPE30 < 0,24540 (−5 %), gain sur ≥ 4 fenêtres sur 6,
  |biais| ≤ 3 %, IC95 bootstrap apparié entièrement négatif.

**Décision : aucune promotion. `LightGBM_direct_per_horizon` reste la référence
30 jours et `CrostonOptimized` la décision quotidienne.**

---

## 4. Pricing — la référence 0,4164 est invalide

### Fuite démontrée

`src/pipelines/final_pricing.py` :

```python
NUM = ['remise_pct', 'prix_base_xof', 'cout_xof', 'n_lignes']
```

`n_lignes` est le nombre de lignes de commande confirmées du produit-jour ; la
cible `quantite` en est exactement la somme. C'est un composant de la cible,
connu seulement après la journée. Corrélation mesurée : **0,708**. Tous les
modèles de la table de référence (LightGBM_calibre 0,4164, GLM_Tweedie 0,4207,
GLM_Poisson 0,4221, panel FE 0,4230) partagent cette feature ; les seuls modèles
sans fuite de cette table sont à 0,564–0,566.

**Preuve indépendante par borne oracle.** Sur les mêmes trois fenêtres, un oracle
qui connaîtrait la médiane produit × remise **calculée dans le test lui-même**
n'atteint que 0,4866 / 0,4838 / 0,4931. Une WAPE de 0,4164 est donc **sous le
plancher d'un oracle honnête** : elle ne peut pas être produite sans information
contemporaine. **L'objectif « améliorer 0,4164 de 5 % » n'est pas atteignable et
ne doit plus servir de cible.**

### Ce qui est réellement atteignable

`src/experiments/pricing_median_objective.py`, mêmes 3 fenêtres, mêmes lignes
(7 151 / 7 757 / 8 179), mêmes 70 features honnêtes que l'expérience avancée,
mêmes hyperparamètres — seule la fonction de perte change.

| Modèle | F1 | F2 | F3 | WAPE moy. | Biais moy. | Écart-type |
|---|---:|---:|---:|---:|---:|---:|
| `lgbm_l1_mediane` | 0,5195 | 0,5230 | 0,5230 | **0,5218** | **−0,1814** | 0,0020 |
| `baseline_produit_mediane` | 0,5250 | 0,5279 | 0,5213 | 0,5247 | −0,1719 | 0,0033 |
| `lgbm_tweedie_moyenne` | 0,5535 | 0,5581 | 0,5461 | 0,5526 | **+0,0013** | 0,0061 |
| CatBoost enrichi (publié) | 0,5689 | 0,5551 | — | 0,5569 | +0,0206 | 0,0113 |
| `baseline_produit_moyenne` | 0,5706 | 0,5679 | 0,5544 | 0,5643 | +0,0416 | 0,0087 |

Bootstrap apparié (ligne produit×jour×remise, 4 000 tirages, n = 23 087) :
`lgbm_l1_mediane` − `lgbm_tweedie_moyenne` = **−0,0305**, IC95
**[−0,0333 ; −0,0278]**, entièrement favorable, 3 fenêtres sur 3 gagnées.

### Pourquoi ce gain n'est pas promouvable

La WAPE est une perte L1 : son optimum est la **médiane** conditionnelle. La
distribution de `quantite` sachant qu'une vente a eu lieu est asymétrique
(moyenne 2,645, médiane 2,0). Prédire la médiane améliore mécaniquement la WAPE
de 6,3 % **et sous-estime le volume de 18 %**. La frontière WAPE/biais est
explicite :

| Ré-échelle de `lgbm_l1_mediane` | WAPE | Biais |
|---|---:|---:|
| ×1,00 | 0,5218 | −0,1814 |
| ×1,10 | 0,5344 | −0,0996 |
| ×1,20 | 0,5519 | −0,0177 |
| ×1,22 | 0,5556 | −0,0014 |

**À biais nul, la meilleure WAPE honnête est 0,5526** (`lgbm_tweedie_moyenne`),
soit **+0,8 %** seulement contre le meilleur challenger publié (0,5569) — très
en dessous du gate de 5 %.

**Décision : aucune promotion.** Le simulateur de marge a besoin d'un volume
**non biaisé** : le modèle de médiane, bien que meilleur en WAPE, y est
inutilisable. La conclusion de fond est méthodologique : **la WAPE est une
métrique mal alignée sur l'usage pricing**, et « améliorer la WAPE » revient
essentiellement à basculer de la moyenne vers la médiane. Les garde-fous
existants (prix ≥ coût, marge ≥ 5 %, support historique, validation humaine,
aucune causalité) restent intégralement en vigueur.

---

## 5. Recommandation — fuite de la catégorie cible

### Fuite démontrée

`src/experiments/complement_end_to_end.py` et
`src/experiments/complement_candidate_pilot.py` :

```python
cat = g.loc[g.produit_key.eq(target), 'categorie'].iloc[0]
...
for y, v in cats.get(cat, {}).items():   # popularite_categorie / reference / rrf
```

La catégorie servant au scoring est **celle de l'article masqué**. Les modèles
`popularite_categorie`, `reference` et `rrf` reçoivent donc la catégorie de la
cible qu'ils doivent deviner — information par construction indisponible au
moment de la recommandation. C'est aussi cette catégorie qui alimente l'union de
candidats, donc le Recall@50 candidat (0,87–0,93) est lui aussi gonflé.

`src/experiments/complement_leak_audit.py` rejoue le **même périmètre** en
comparant la variante fuitée et la variante honnête (catégories du contexte
observé uniquement). La variante fuitée **reproduit exactement** les chiffres
publiés, ce qui identifie la fuite sans ambiguïté :

| Fenêtre | Modèle | Recall@10 | NDCG@10 |
|---|---|---:|---:|
| F2 | `popularite_categorie` **(fuité, = chiffre publié)** | 0,43743 | 0,21264 |
| F2 | même règle, catégories du contexte **(honnête)** | 0,06201 | 0,02946 |
| F3 | fuité | 0,36044 | 0,18018 |
| F3 | honnête | 0,05320 | 0,02493 |
| F4 | fuité | 0,33458 | 0,16297 |
| F4 | honnête | 0,04758 | 0,02209 |

Bootstrap apparié commande×fenêtre (2 000 tirages, n = 16 014) :
avantage de la fuite = **+0,15977 de NDCG@10**, IC95 **[0,15555 ; 0,16393]**.
Facteur d'inflation ≈ **7×**.

**Conséquences.** Les valeurs `Recall@10 0,437 / NDCG@10 0,213` et la couverture
associée sont invalides. Le statut métier
`basket_complement_model = ancienne_reference / popularite_categorie` **n'est pas
déployable** : en production, la catégorie de l'article que le client n'a pas
encore ajouté est inconnue. Les rejets de RRF et de LambdaRank ont par ailleurs
été prononcés contre une référence imbattable parce que fuitée.

### Pourquoi aucun modèle ne rattrape l'écart : il n'y a pas de signal

Test structurel indépendant sur les 21 352 commandes multi-produits :
`P(catégorie de la cible présente dans le contexte) = 0,2182`, contre **0,222**
attendus si les articles d'un panier étaient tirés indépendamment de la
distribution marginale des catégories. **Les paniers sont statistiquement des
tirages indépendants : il n'existe pas de complémentarité exploitable.**

### Nouvelle référence honnête

`src/experiments/complement_honest_baseline.py`, même périmètre (5 338 commandes
par fenêtre, F2–F4, une cible masquée par commande, catalogue 300), règle de
classement identique pour tous les modèles :

| Modèle | Recall@10 | NDCG@10 | Couverture | IC95 vs référence | Promu |
|---|---:|---:|---:|---|---|
| **`popularite_globale` (référence honnête)** | **0,0556** | **0,0240** | 0,042 | — | — |
| `popularite_categorie_contexte` | 0,0544 | 0,0253 | 0,319 | [−0,00075 ; 0,00339] | non |
| `cooccurrence_item_item` | 0,0551 | 0,0247 | 0,661 | [−0,00117 ; 0,00270] | non |
| `cooccurrence_plus_popularite` | 0,0544 | 0,0246 | 0,609 | [−0,00128 ; 0,00246] | non |
| `bm25_panier` | 0,0518 | 0,0231 | 0,764 | [−0,00306 ; 0,00121] | non |
| `association_lift` | 0,0366 | 0,0162 | 0,771 | [−0,00993 ; −0,00557] | non |

Aucun IC95 n'est entièrement positif. **Aucune promotion.**

### Artefact d'évaluation corrigé en cours de route

Une première version de ce pilote donnait à la cooccurrence un gain de +18,2 %
de NDCG@10 avec IC95 entièrement positif. Vérification faite, ce gain était
**faux** : la cible est `sorted(items)[0]`, l'article alphabétiquement premier du
panier, et le départage des ex æquo se faisait par ordre alphabétique de
référence produit. Les modèles dont la liste comportait des scores nuls
remplissaient donc la fin du Top-20 par des produits à identifiant bas,
mécaniquement favorables — 74 « hits » supplémentaires sur la seule fenêtre F2.
La règle de classement a été uniformisée (scores strictement positifs, complétion
par la popularité, départage par popularité puis permutation déterministe), et le
gain tombe à +3,1 % avec un IC95 qui traverse zéro. **Ce candidat est rejeté.**

### Prochain achat

Le pipeline `advanced_recommendation.py` a été audité séparément : entraînement
sur `date_commande < cutoff`, aucune feature dérivée de la cible. **Aucune fuite.**
Sa conclusion (popularité globale officielle, rankers personnalisés sans gain
crédible) est confirmée et cohérente avec l'absence de structure de co-achat.

---

## 6. Ce qui reste impossible avec les données actuelles

- **Toute revendication causale en pricing** : prix catalogue fixe pour les
  300 produits, campagnes non randomisées, seules les remises varient. Aucun prix
  optimal continu n'est estimable.
- **Une WAPE pricing < 0,487** sans information contemporaine : borne oracle.
- **Une WAPE forecasting 30 j < 0,22** : plancher de bruit binomial négatif.
- **Toute recommandation de complément panier fondée sur la complémentarité** :
  les paniers sont des tirages indépendants.
- **Un modèle sessionnel** : cible déjà vue dans 100 % des cas ; statut
  `non_utilisable` confirmé.
- **La demande réelle** : aucune donnée de rupture ni de demande perdue ;
  `quantite_vendue` du stock inclut tous les statuts sans réintégration des
  annulations et retours.

Les données qui débloqueraient réellement ces axes : historique plus long, date
de lancement commercial réelle, demande perdue et disponibilité intra-journalière,
variation effective des prix catalogue, expérimentation randomisée des remises, et
une structure de panier réellement corrélée.

---

## 7. Reproductibilité

```bash
python -m src.experiments.cumulative_l1_forecasting
python -m src.experiments.pricing_median_objective
python -m src.experiments.complement_leak_audit
python -m src.experiments.complement_honest_baseline
python -m pytest tests -q
```

Sorties : `reports/advanced/cumulative_l1_pilot.json`,
`reports/advanced/pricing_median_objective.json`,
`reports/advanced/complement_leak_audit.json`,
`reports/advanced/complement_honest_baseline.json`,
`models/advanced/complement_honest/` (unités, Top-K, modèle sérialisé,
`manifest.sha256.json`).

Graine unique 42, checkpoints par expérience, aucune écriture Supabase, aucune
modification des artefacts validés existants.

---

## 8. Actions nécessitant une autorisation explicite

1. **Corriger la fuite dans le code livré** — `complement_end_to_end.py` et
   `complement_candidate_pilot.py` produisent encore des métriques invalides à
   chaque exécution.
2. **Retirer `n_lignes`** des features de `src/pipelines/final_pricing.py` et
   requalifier `LightGBM_calibre` comme non décisionnel.
3. **Corriger les rapports publiés** qui citent 0,4164 comme référence pricing et
   0,437 / 0,213 comme référence complément panier, ainsi que le statut métier
   `basket_complement_model`.
4. **Tout `git push`** ou fusion vers `main`.
