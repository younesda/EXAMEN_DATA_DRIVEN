# Rapport final du projet — prévision, tarification et recommandation

**Statut du projet : expérimentation académique sur données synthétiques.**
Aucun résultat de ce document ne constitue une performance commerciale
réelle, aucun effet causal n'est estimé, et aucune décision n'est appliquée
automatiquement. Ce rapport est le document de référence unique pour
l'équipe.

Date de rédaction : 22 août 2026.

---

## 1. Objet et périmètre

Le projet couvre trois domaines analytiques sur un jeu de données
e-commerce synthétique (300 produits, 5 000 clients, catalogue en francs
CFA) :

| Domaine | Question | Statut final |
|---|---|---|
| Prévision de la demande | Combien d'unités par produit sur 30 jours ? | Validé, en production académique |
| Tarification | Quelles conséquences comptables d'une remise ? | Simulation uniquement |
| Recommandation | Comment ordonner des produits candidats ? | Deux modèles validés, un exploratoire |

Les données sont **entièrement synthétiques** et portent le statut
`synthetic_academic_experiment`. Elles ne décrivent aucune activité
commerciale réelle.

---

## 2. Historique des versions

Les métriques d'une version ne sont jamais comparables à celles d'une autre :
les jeux de données, les périmètres et les protocoles diffèrent. Elles ne
doivent en aucun cas être mises côte à côte.

### V1 — premières bases de référence

**Objectif** : établir des points de comparaison simples et mesurer la
difficulté réelle du problème.

**Modèles testés** : moyenne mobile, saisonnier naïf, naïf, Croston,
LightGBM.

**Résultat** : la demande s'est révélée fortement intermittente, une large
part des produits ne se vendant pas tous les jours. Les erreurs relatives
mesurées ont été bien supérieures aux attentes initiales.

**Problème identifié** : une lecture optimiste des premières métriques
laissait croire à une précision élevée, alors que l'intermittence gonfle
mécaniquement l'erreur relative.

**Décision** : conserver les baselines comme références obligatoires, et
n'accepter aucun modèle qui ne les batte pas de façon démontrée.

### V2 — consolidation et correction de fuites

**Objectif** : fiabiliser les résultats et corriger les défauts
méthodologiques.

**Modèles testés** : LightGBM par horizon, ensembles, modèles de
tarification, classements de recommandation.

**Résultat** : le forecasting a été validé et promu. En revanche, un audit
indépendant a mis en évidence **deux fuites de cible** : une variable de
tarification qui était une composante directe de la cible, et un score de
recommandation qui accédait à la catégorie du produit masqué.

**Problème identifié** : les résultats de tarification et de recommandation
antérieurs étaient invalides.

**Décision** : les résultats concernés ont été explicitement marqués comme
invalidés, jamais supprimés, et republiés après correction. Le détail figure
dans le document de résultats supersédés du dépôt.

### V3 — enrichissement et contre-audit

**Objectif** : intégrer une livraison de données enrichie.

**Résultat** : les contrôles d'antériorité et de cohérence ont révélé des
anomalies suffisantes pour ne pas fonder de décision sur cette livraison.

**Décision** : version mise en attente, non promue. Aucun modèle V3 n'est
utilisé.

### V4 — expérimentation, validation indépendante et mise en service

**Objectif** : entraîner tarification et recommandation sur une livraison
expérimentale, avec un protocole anti-fuite strict.

**Modèles testés** : pour la tarification, baselines par produit, GLM
Poisson et Tweedie, LightGBM (Poisson, Tweedie, L1, contraint monotone),
CatBoost, modèle en deux parties, apprenants S et T, ensemble contraint.
Pour la recommandation, popularité globale, popularité récente, popularité
par catégorie, cooccurrence, fusion de rangs réciproques, hybride,
LightGBM LambdaRank, CatBoostRanker, XGBoost Ranker, modèle de conversion
ponctuel.

**Résultat** : aucun modèle de tarification n'a battu la baseline. Trois
modèles de recommandation franchissaient le seuil de promotion, mais une
**validation indépendante** en a reclassé un en exploratoire.

**Décision** : voir les sections 3 à 5, et la section 6 pour les audits
qui ont conditionné ces décisions.

---

## 3. Prévision de la demande

**Modèles retenus, inchangés depuis leur validation :**

| Usage | Modèle |
|---|---|
| Planification cumulée à 30 jours | `LightGBM_direct_per_horizon` |
| Prévision quotidienne | `CrostonOptimized` |

**Métriques finales :**

| Métrique | Valeur |
|---|---|
| WAPE30 macro | **0,25831** |
| WAPE30 micro | 0,25743 |
| Forecast Bias macro | **−0,02589** |

**Erreur par horizon d'agrégation** (modèle de planification) :

| Horizon | WAPE |
|---|---:|
| Quotidienne | 1,08698 |
| Cumul 7 jours | 0,45457 |
| Cumul 14 jours | *non calculée* |
| Cumul 30 jours | 0,25831 |

La WAPE à 14 jours n'a pas été évaluée lors du backtest. Elle est déclarée
absente partout où elle apparaît, et n'est jamais remplacée par une valeur
approchée.

**Modèle opérationnel quotidien** (`CrostonOptimized`) :

| Métrique | Valeur |
|---|---:|
| WAPE quotidienne | 1,09452 |
| WAPE cumul 30 jours | 0,36996 |
| Biais | −0,05959 |

**Protocole d'évaluation** : 6 fenêtres de test hors échantillon, 30 horizons
évalués. Le modèle de planification gagne **6 fenêtres sur 6** contre la
référence `LightGBM_Tweedie` ; le modèle quotidien en gagne **5 sur 6**.

| Fenêtre | Début | WAPE quotidienne | WAPE 7 j | WAPE 30 j | Biais |
|---:|---|---:|---:|---:|---:|
| 1 | 2026-02-02 | 1,09011 | 0,43817 | 0,26794 | +0,01667 |
| 2 | 2026-03-04 | 1,11513 | 0,47627 | 0,28876 | −0,05035 |
| 3 | 2026-04-03 | 1,08440 | 0,46897 | 0,24895 | −0,05805 |
| 4 | 2026-05-03 | 1,06114 | 0,45155 | 0,25868 | −0,06135 |
| 5 | 2026-06-02 | 1,07112 | 0,43348 | 0,25282 | −0,04841 |
| 6 | 2026-07-02 | 1,09996 | 0,45898 | 0,23274 | +0,04611 |

### Pourquoi la WAPE quotidienne dépasse 1

Une WAPE quotidienne de 1,087 signifie que l'erreur absolue moyenne dépasse
le niveau moyen de la demande d'un jour donné. Ce n'est pas une anomalie :
sur une demande très intermittente, où de nombreux produits enregistrent zéro
vente un jour donné, le dénominateur est faible et le rapport explose.

C'est précisément pourquoi la décision de promotion porte sur le **cumul à 30
jours** (WAPE 0,25831) et non sur la prévision quotidienne : à cet horizon,
l'agrégation lisse l'intermittence et l'erreur relative redevient
interprétable.

### Lecture correcte de ces chiffres

Une WAPE30 de 0,25831 **ne signifie pas une exactitude de 90 %**, ni de
74 %. La WAPE est une erreur relative pondérée : sur une demande fortement
intermittente, où de nombreux produits enregistrent zéro vente certains
jours, le dénominateur est faible et l'erreur relative est mécaniquement
élevée. Une WAPE de cet ordre est un résultat correct dans ce contexte, mais
elle ne se traduit pas en pourcentage de « bonnes prévisions ».

Le biais macro de −0,02589 indique une sous-estimation moyenne d'environ
2,6 %, ce qui est faible et acceptable.

### Pourquoi le forecasting n'a pas été relancé

Ces modèles étaient déjà validés avant les travaux V4. Les relancer aurait
introduit un risque de divergence sans bénéfice attendu. Le dépôt comporte
un garde-fou automatisé qui vérifie, à chaque exécution de la batterie de
tests :

- que les six artefacts de prévision ont des empreintes SHA-256 identiques
  à celles enregistrées avant le début des travaux V4 ;
- qu'aucun commit ne modifie ces artefacts ;
- que les valeurs de décision (modèles retenus, WAPE30, biais) sont
  identiques à celles du commit de référence.

---

## 4. Tarification

**Modèle retenu : `baseline_mediane_produit`** — la médiane historique des
ventes hebdomadaires par produit.

**Statut : simulation uniquement.** Aucun effet causal n'est estimé et aucun
prix optimal n'est calculé automatiquement.

### Métriques par cible

| Cible | WAPE macro | WAPE micro | Biais |
|---|---:|---:|---:|
| `units_sold_window_7j` | 0,1342 | 0,1334 | +0,0054 |
| `revenue_window_xof_7j` | 0,1299 | 0,1291 | +0,0020 |
| `margin_window_xof_7j` | 0,1305 | 0,1298 | +0,0004 |

### Modèles rejetés

Aucun modèle d'apprentissage n'a battu la baseline. Le meilleur candidat non
baseline, l'apprenant T, atteint une WAPE macro de 0,1628 sur les volumes,
soit une dégradation de 21 % par rapport à la médiane par produit.

**Cause structurelle, et non défaut de méthode** : le niveau de remise, la
classe ABC et le statut de démarrage à froid sont des attributs **fixes par
produit** sur toute la durée de l'expérience. La remise n'est donc jamais
observée à deux niveaux différents pour un même produit : elle est
entièrement confondue avec l'identité du produit. Un modèle qui mémorise
l'identité du produit peut sembler expliquer un effet de remise sans avoir
appris la moindre relation généralisable.

### Trois lectures à ne jamais confondre

1. **Prévision de volume** : une estimation statistique du nombre d'unités,
   sans interprétation causale.
2. **Simulation de marge** : une projection comptable dérivée du volume
   prévu et du prix simulé.
3. **Causalité** : hors de portée. La confusion structurelle décrite
   ci-dessus interdit toute affirmation du type « cette remise cause ce
   volume », quelle que soit la qualité apparente d'une métrique.

### Garde-fous vérifiés

Sur les 11 799 décisions de l'expérience : **zéro prix inférieur au coût**,
**zéro marge sous le plancher**. Le service refuse toute simulation dont le
prix tomberait sous le coût unitaire.

---

## 5. Recommandation

Les trois cibles sont évaluées séparément. Le modèle de repli général est
`popularite_globale_v1`.

| Cible | Modèle | Gain NDCG@10 | p-value Holm indépendante | Statut |
|---|---|---:|---:|---|
| `purchased_after` (achat) | `CatBoostRanker` | **+8,57 %** | 0,00075 | **validé** |
| `added_to_cart_after` (panier) | `pointwise_conversion` | **+7,70 %** | 0,0015 | **validé** |
| `viewed_after_impression` (consultation) | `CatBoostRanker` | +5,57 % | 0,08823 | **exploratoire** |

### Pourquoi la consultation n'est pas promue

Le modèle franchissait initialement le seuil de promotion. Une validation
indépendante, menée avec des fonctions de métrique, de bootstrap et de
correction de Holm entièrement réécrites, a reproduit les estimations
ponctuelles à l'identique mais obtenu une p-value brute de 0,088 — non
significative même **avant** correction pour comparaisons multiples.

Les deux méthodes de test, construites différemment, s'accordent donc pour
dire que ce gain n'est pas démontré de façon robuste. Le modèle est
consultable mais **n'est servi par défaut par aucun point d'entrée**.

### Précaution méthodologique importante

Les listes exposées comportent exactement cinq candidats. Avec des listes
fermées de cette taille, **Recall@5, Recall@10, Recall@20 et HitRate@10 sont
mathématiquement invariants au réordonnancement** : réordonner cinq
candidats ne change pas l'ensemble des cinq. Seuls NDCG@k, MRR et MAP@10
sont sensibles à l'ordre.

Le critère « ne pas perdre plus de 2 % de Recall » est donc satisfait
mécaniquement par tout modèle de réordonnancement dans ce protocole. Le
NDCG@10 est le seul discriminant réel, et c'est sur lui que reposent les
décisions ci-dessus.

### Limites

- Gains mesurés **hors ligne**, sur des données synthétiques.
- Le réordonnancement porte sur un ensemble de candidats déjà sélectionné :
  le service ne choisit pas les candidats.
- Le catalogue de recommandation couvre **208 produits sur 300** : 92
  produits n'ont jamais été exposés pendant l'expérience.
- Aucun test A/B commercial n'a été conduit.

---

## 6. Audits et contrôles de validité

Le projet a fait l'objet de quatre audits distincts. Ils sont la raison
principale pour laquelle plusieurs résultats intermédiaires ont été écartés,
et ils constituent la garantie de fond des conclusions retenues.

### 6.1 Audit indépendant de la V2 — deux fuites de cible détectées

**Objet** : vérifier que les résultats V2 étaient réellement exploitables.

**Constats** :

1. **Tarification** : une variable utilisée comme prédicteur était une
   composante directe de la cible. Le modèle prédisait donc partiellement
   une grandeur qu'il recevait déjà en entrée.
2. **Recommandation** : le score de complément de panier accédait à la
   catégorie du produit masqué, c'est-à-dire à une information dérivée de la
   réponse attendue.

**Conséquence** : les résultats de tarification et de recommandation
antérieurs étaient invalides.

**Traitement** : les résultats concernés ont été explicitement marqués comme
invalidés, **jamais supprimés**, avec un motif consigné dans leurs
métadonnées. Le noyau de scoring de recommandation a été refondu pour qu'il
soit **structurellement incapable** de voir la cible, et un registre de
disponibilité des variables a été introduit côté tarification. La prévision
n'était pas concernée et n'a pas été touchée.

### 6.2 Audit de la livraison V3 — version mise en attente

**Objet** : décider si la livraison enrichie pouvait fonder une modélisation.

**Constats chiffrés sur la table d'exposition** :

- 55,15 % des listes exposées contenaient un produit futur ;
- taux d'inclusion des sessions de 45,00 % contre 15,75 % selon l'achat, ce
  qui signale une sélection corrélée au résultat ;
- groupes contrôle et traitement sans effet réel sur les candidats, les
  scores ni l'ordre : le traitement était nul en pratique.

**Constats sur la table de tarification** :

- 12 995 valeurs d'impressions pré-décision incohérentes ;
- 986 chevauchements avec une promotion active ;
- 478 revenus enregistrés au mauvais prix.

**Verdict** : livraison utilisable pour tester une chaîne de traitement,
**non validée** pour une modélisation hors ligne, pour toute méthode causale
ou pour une décision de production.

**Décision** : V3 mise en attente. **Aucun modèle V3 n'est utilisé.**

### 6.3 Audit automatisé de la V4 — 20 contrôles

Exécuté sur l'instantané local, sans accès réseau, et rejouable.

**Bilan : 17 réussites, 2 avertissements, 1 échec.**

| Contrôle | Statut | Constat | Traitement |
|---|---|---|---|
| `P-12` impressions produit | **échec** | Valeur constante par produit sur toute la période : total de période, et non cumul antérieur à la décision | Variable **exclue** des prédicteurs et **reconstruite** depuis les événements web antérieurs à la décision |
| `P-02` décisions par produit et semaine | avertissement | Jusqu'à 2 décisions par couple produit / semaine calendaire | Artefact du calendrier sur une expérience de 65 semaines, soit plus d'une année civile. Aucun doublon sur la clé réellement utilisée pour le découpage temporel |
| `R-19` sémantique de la probabilité d'exposition | avertissement | Somme par liste proche de 1, mais sélection réellement déterministe | Statut explicite ajouté au jeu de données ; cette propension n'est **jamais** utilisée comme pondération |

Les 17 contrôles réussis couvrent notamment l'unicité des identifiants, la
cohérence entre éligibilité et remise appliquée, la conformité du stock à la
veille de la décision, l'absence de chevauchement avec une promotion,
l'absence d'exposition sur session automatisée et la cohérence de la
séquence achat après passage au panier.

**Point de méthode** : l'échec `P-12` a été traité par correction et
vérification, non par contournement. La reconstruction a été validée par un
second calcul, écrit indépendamment, qui a donné un résultat identique sur
un échantillon de 400 décisions.

### 6.4 Validation indépendante des gains de recommandation

**Objet** : vérifier les gains avant toute promotion, sans réutiliser le
code qui les avait produits.

**Méthode** : les métriques, le bootstrap et la correction de Holm ont été
**entièrement réécrits** dans un module séparé. Les modèles ont été
réentraînés fenêtre par fenêtre avec le même protocole temporel.

**Résultats** :

- les estimations ponctuelles ont été **reproduites à l'identique** — NDCG@10
  concordant à la cinquième décimale sur les trois cibles, ce qui confirme
  que l'implémentation d'origine n'était pas en défaut ;
- le découpage temporel a été revérifié : aucune violation d'ordre
  chronologique, aucune liste répartie sur plusieurs fenêtres ;
- l'absence de fuite a été confirmée : les variables restent strictement
  identiques après permutation aléatoire des cibles ;
- **mais** sur la cible de consultation, un test de permutation construit
  différemment a donné une p-value brute de 0,088, non significative même
  avant correction pour comparaisons multiples.

**Conséquence** : le modèle de consultation a été **reclassé de promu à
exploratoire**. Les deux autres cibles ont vu leur promotion confirmée par
les deux méthodes de test.

C'est le seul cas du projet où une contre-expertise a renversé une décision
déjà prise. Elle illustre l'intérêt de faire vérifier un résultat par un
chemin de code indépendant.

### 6.5 Contrôles permanents intégrés à la chaîne de tests

Quatre garde-fous s'exécutent à chaque validation :

1. **Immuabilité de la prévision** : empreintes SHA-256 des artefacts,
   absence de tout commit les modifiant, et comparaison des valeurs de
   décision au commit de référence.
2. **Intégrité des artefacts** : validation de tous les manifestes SHA-256
   du dépôt.
3. **Contexte de construction** : vérification que chaque fichier référencé
   par une image existe, est versionné et survit aux règles d'exclusion.
4. **Absence de fuite** : contrôles rejouables sur les jeux de données.

---

## 7. API et interface

Le service expose une API et une console web, toutes deux en français.

### Points d'entrée publics

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/` | Console web |
| GET | `/health` | État du service, modèles chargés, version déployée |
| GET | `/metadata` | Fiche consolidée des modèles |
| GET | `/metrics` | Scores des trois domaines et compteurs opérationnels |
| GET | `/docs` | Documentation interactive |
| GET | `/catalogue` | Listes de produits |
| GET | `/forecast` | Synthèse de la prévision 30 jours |
| GET | `/forecast/produits` | Produits couverts et écart cumulé |
| GET | `/forecast/{produit}` | Courbe réalisé contre prévu |
| POST | `/recommendations` | Recommandation d'achat |
| POST | `/recommendations/cart` | Recommandation d'ajout au panier |
| POST | `/pricing/simulation` | Simulation de remise |

### Console web

Quatre pages : recommandation, simulation de remise, prévision 30 jours,
scores et validation. Sans cadriciel ni ressource distante, testée sur poste
de bureau et sur mobile.

### Garanties du contrat de réponse

La recommandation distingue explicitement quatre champs, afin qu'un repli ne
puisse jamais être confondu avec un service nominal :

- `target_status` : statut du modèle **prévu** pour la cible ;
- `model_requested` : modèle qui aurait été utilisé sans incident ;
- `model_used` : modèle **réellement** utilisé ;
- `served_model_status` : statut du modèle réellement utilisé.

La tarification dérive le chiffre d'affaires et la marge du volume et du
prix simulé :

```
chiffre_affaires = volume x prix_simule
marge            = volume x (prix_simule - cout_unitaire)
```

Un échec de prédiction produit une **erreur explicite**, jamais un zéro. Un
zéro renvoyé est donc toujours une valeur réellement prédite.

### Point d'attention sur la prévision exposée

Les routes de prévision servent un **instantané de backtest hors
échantillon**, repris en lecture seule. Ce n'est **pas une prévision du
futur**, et aucun modèle de prévision n'est chargé ni réexécuté par le
service.

---

## 8. Reproductibilité et MLOps

### Ce qui est en place

| Élément | Mécanisme |
|---|---|
| Version du code | Commit enregistré dans chaque fichier de métadonnées |
| Modèles | Sérialisés et versionnés |
| Intégrité | Manifeste SHA-256 par répertoire, validé automatiquement |
| Registre | Fiche de statut consolidée, source unique de vérité |
| Données sources | Empreintes SHA-256 des extractions |
| Graine aléatoire | Fixée à 42 dans tous les modules |
| Surveillance | `/health` et `/metrics` |

### Procédure de reproduction

```bash
pip install -r requirements.txt
python -m src.pipelines.finalize_v4_product
python -m scripts.run_v4_checks
uvicorn api_v4.main:app --host 0.0.0.0 --port 8099
```

La console est alors accessible à la racine, et la documentation interactive
sur `/docs`.

### Déclencheurs de réentraînement

Aucun n'est actif aujourd'hui. Sur données réelles, il faudrait surveiller :
la dérive de distribution des variables, la hausse du taux de repli, la
péremption des instantanés de catalogue, et toute nouvelle livraison de
données.

### Retour arrière

Chaque état correspond à un commit identifié. Le retour arrière consiste à
extraire les artefacts et le code d'un commit antérieur ; aucune écriture
externe n'est impliquée.

---

## 9. Tests

La batterie unique s'exécute par :

```bash
python -m scripts.run_v4_checks
```

Elle enchaîne dix étapes et s'arrête à la première en échec :

1. garde-fou d'immuabilité de la prévision ;
2. tests unitaires de tarification ;
3. tests unitaires de recommandation ;
4. configuration de déploiement ;
5. contexte de construction de l'image ;
6. tests de l'API ;
7. simulation de tarification ;
8. scores et route des métriques ;
9. tests d'intégration, incluant le démarrage d'un serveur réel ;
10. validation de tous les manifestes SHA-256.

**Résultat : 147 tests réussis, 0 ignoré, 0 échec.**

---

## 10. Déploiement

Le service V4 est déployé comme **service distinct** du service V2, qui reste
en ligne et inchangé.

Le dépôt contient deux images :

| Fichier | Application | Service |
|---|---|---|
| `Dockerfile` | API V2 | service existant, non modifié |
| `Dockerfile.api_v4` | API V4 | service séparé |

Le fichier de configuration désigne explicitement l'image V4. Sans cette
désignation, la plateforme sélectionne automatiquement l'image à la racine
et déploie la V2 en croyant déployer la V4 — incident réellement survenu et
corrigé.

L'image V4 embarque uniquement le code du service, les modules nécessaires
au rechargement des modèles et les six modèles sérialisés, soit moins de
1 Mo. Les fichiers de reproductibilité (environ 104 Mo) en sont exclus.

**Identification de la version en ligne** : `/health` et `/metadata`
renvoient `service` et `deployed_commit`. Le critère fiable pour distinguer
les deux services est structurel : présence des routes V4 et absence des
routes V2.

---

## 11. Limites générales

### Limites des données

- Données **entièrement synthétiques** : aucune conclusion ne se transpose à
  une activité réelle sans nouvelle validation.
- Demande fortement intermittente : la moitié des produits ont une médiane
  hebdomadaire de ventes nulle.
- Aucune donnée concurrentielle, aucune élasticité prix observable
  indépendamment de l'identité produit.
- Aucune mesure de la demande perdue : les ruptures de stock ne sont pas
  distinguées d'une absence de demande.

### Limites du service

- Aucune authentification, aucune limitation de débit.
- Instantanés figés à la fin de la fenêtre d'entraînement, jamais
  rafraîchis automatiquement.
- Aucune surveillance de dérive.
- Aucun test de charge.

---

## 12. Statut de chaque composant

| Composant | Modèle | Statut |
|---|---|---|
| Prévision 30 jours | `LightGBM_direct_per_horizon` | validé, référence |
| Prévision quotidienne | `CrostonOptimized` | validé, référence |
| Tarification (3 cibles) | `baseline_mediane_produit` | validé, simulation uniquement |
| Recommandation achat | `CatBoostRanker` | validé académiquement |
| Recommandation panier | `pointwise_conversion` | validé académiquement |
| Recommandation consultation | `CatBoostRanker` | exploratoire, non servi |
| Repli général | `popularite_globale_v1` | validé, secours |

---

## 13. Prochaines étapes

**Avant tout usage réel**, dans l'ordre de priorité :

1. Rejouer l'ensemble du protocole sur des **données réelles**, avec une
   variation de remise indépendante de l'identité produit — condition sans
   laquelle aucune conclusion causale ne sera jamais possible.
2. Conduire un **test A/B** pour mesurer les gains de recommandation en
   ligne, les gains hors ligne n'étant pas transposables.
3. Ajouter authentification, limitation de débit et contrôle d'accès.
4. Mettre en place une source de variables vivante et gouvernée, en
   remplacement des instantanés figés.
5. Instrumenter la surveillance de dérive et définir des seuils de
   réentraînement.
6. Étendre la couverture du catalogue de recommandation au-delà des 208
   produits actuels.

**Point ouvert** : deux branches du dépôt et 29 messages de commit portent
des mentions liées à l'outillage de développement. Leur suppression exige
une réécriture de l'historique, opération destructive qui n'a pas été
engagée. Le détail figure dans la note de nettoyage accompagnant ce rapport.
