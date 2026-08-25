# 02 — Divergence bloquante : métriques de recommandation

> Point d'arrêt Phase 2. La consigne impose : « Si les fichiers officiels
> diffèrent de ces valeurs, arrête-toi et documente la divergence avant de
> modifier l'interface. » C'est le cas. **Aucune interface n'a été écrite.**

---

## 1. Ce que dit la consigne

> **Recommandation corrigée**
> - modèle général officiel : `popularite_globale`
> - Recall@10 : environ **0,0556**
> - NDCG@10 : environ **0,0240**
> - couverture catalogue : environ **4,2 %**

## 2. Ce que disent les fichiers officiels du dépôt

Ces trois valeurs existent bien — mais elles appartiennent au **complément
panier**, pas au modèle général.

### A. Recommandation générale (prochain achat)

Source : `models/advanced/recommendation/general_metadata.json`, clé `summary`,
4 fenêtres de 30 jours, évaluation end-to-end.

| Modèle | Recall@10 | NDCG@10 | Couverture |
|---|---:|---:|---:|
| **`popularite_globale`** (baseline officielle) | **0,06686** | **0,03771** | **6,08 %** |

C'est cette source que le bundle API expose déjà
(`models/api_bundle/metadata.json` → `recommendation.metrics` =
`recall 0.066858`, `ndcg 0.037712`).

### B. Complément panier (leave-one-item-out, F2–F4)

Source : `reports/advanced/complement_honest_baseline.json`, clé `summary`,
une cible masquée par commande, périmètre corrigé après la fuite.

| Modèle | Recall@10 | NDCG@10 | Couverture |
|---|---:|---:|---:|
| **`popularite_globale`** (baseline honnête) | **0,05558** | **0,02400** | **4,22 %** |

## 3. Diagnostic

Les valeurs `0,0556 / 0,0240 / 4,2 %` de la consigne sont **exactement** celles
de la ligne B. Elles ont été attribuées au modèle général, qui relève de la
ligne A.

**Ce sont deux tâches différentes, avec des cibles et des populations
différentes :**

| | Recommandation générale | Complément panier |
|---|---|---|
| Question posée | quels produits ce client achètera-t-il ensuite ? | quel article manque à ce panier ? |
| Population | clients évaluables sur la fenêtre | commandes multi-produits |
| Cible | achats confirmés futurs | un article masqué du panier |
| Fenêtres | 4 × 30 jours | F2–F4 |
| Statut du modèle | baseline officielle **validée** | baseline, **aucun modèle validé** |

Afficher 0,0240 sous le libellé « modèle général » reproduirait précisément
l'erreur que l'audit a corrigée : présenter une métrique sous un périmètre qui
n'est pas le sien. C'est la raison de ce point d'arrêt.

## 4. Vérification des deux autres domaines

Aucune divergence.

| Élément | Consigne | Fichier officiel | Verdict |
|---|---:|---:|---|
| Forecasting 30 j | `LightGBM_direct_per_horizon` | idem | ✅ |
| WAPE30 macro | 0,25831 | 0,25831 | ✅ |
| WAPE30 micro | 0,25743 | 0,25743 (commentaire `final_status.py`) | ✅ |
| Forecast Bias macro | −0,02589 | −0,02589 | ✅ |
| Quotidien | `CrostonOptimized` | idem | ✅ |
| Pricing volume | `lgbm_tweedie_moyenne` | idem | ✅ |
| Pricing WAPE | ≈ 0,5526 | 0,5526 | ✅ |
| Pricing biais | ≈ +0,0013 | 0,0013 | ✅ |
| Pricing statut | exploratoire non causal | `exploratory_non_causal` | ✅ |
| Complément panier | aucun modèle validé | `none_validated` | ✅ |
| RRF | challenger non promu | `exploratory_diversity_challenger` | ✅ |
| Sessionnel | non utilisable | `non_utilisable` | ✅ |

Seules les trois métriques de recommandation divergent, et uniquement par
attribution de périmètre.

## 5. Options d'arbitrage

**Option 1 — recommandée : afficher les deux, chacune sous son périmètre.**

L'interface montre une carte « Recommandation générale (prochain achat) » avec
0,06686 / 0,03771 / 6,08 %, et une carte « Complément panier » avec
0,05558 / 0,02400 / 4,22 % assortie du statut `none_validated`. Les deux valeurs
sont officielles, aucune n'est inventée, et le lecteur ne peut pas les
confondre. C'est cohérent avec la discipline de périmètre du projet.

**Option 2 — n'afficher que le modèle général.**
Carte unique avec 0,06686 / 0,03771 / 6,08 %. Plus simple, mais le complément
panier disparaît de la démonstration alors qu'il porte le résultat d'audit le
plus marquant.

**Option 3 — publier 0,0556 / 0,0240 / 4,2 % comme métriques du modèle général.**
**Déconseillée.** Ce serait une erreur de périmètre, du même type que celles que
l'audit a corrigées, et elle serait visible par un correcteur d'examen.

## 6. Ce qui est suspendu

- Phase 4 (interface web) et suivantes.
- Phase 3 pour la seule partie « endpoint `/metrics` », dont la charge utile
  dépend de l'arbitrage.

Le reste de la Phase 3 (fiabilisation backend : `/version`, `/models`, catalogue,
recherche, correction du `NaN`, format d'erreur, statut pricing par remise) est
indépendant de cette décision et peut démarrer immédiatement.
