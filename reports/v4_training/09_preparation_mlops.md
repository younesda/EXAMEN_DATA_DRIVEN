# 09 — Preparation MLOps du produit V4

Statut : `synthetic_academic_experiment`. Ce document decrit ce qui est deja
en place pour l'exploitation du produit V4 et ce qui manquerait avant une
mise en production reelle. **Aucun element de ce document ne declenche un
deploiement, un push ou une ecriture Supabase** : il s'agit d'une
preparation et d'une documentation, pas d'une mise en service.

Le forecasting V2 n'est ni concerne, ni modifie par ce document : il
demeure `LightGBM_direct_per_horizon` (planification 30 jours) /
`CrostonOptimized` (quotidien), WAPE30 macro 0,25831, biais macro -0,02589,
verifie inchange par `tests/test_forecasting_unchanged.py`.

---

## 1. Versionnement et tracabilite

| Element | Mecanisme en place |
|---|---|
| Code | commit Git (`code_version_git_commit` dans chaque `metadata.json` et dans `models/v4/FINAL_STATUS.json`) |
| Modeles | `models/v4/{pricing,recommendation}/{cible}/model.joblib`, versionnes dans Git |
| Integrite des artefacts | `manifest.sha256.json` par repertoire, verifiable par `python -m scripts.validate_manifests` |
| Fiche de statut consolidee | `models/v4/FINAL_STATUS.json`, source unique consultee par l'API (`GET /metadata`) |
| Donnees source | `models/v4/manifests/raw_data_manifest.json` (empreinte SHA-256 des extractions) |

Toute divergence entre un artefact et son empreinte declaree est detectee
automatiquement (`validate_manifests.py`, et pour le forecasting
specifiquement, `tests/test_forecasting_unchanged.py`).

## 2. Registre de modeles

`models/v4/FINAL_STATUS.json` fait office de registre minimal : chaque
entree porte domaine, cible, nom du modele, version, metriques, fenetre
d'evaluation, limites, statut (`validated_academic` / `exploratory`),
modele de repli et empreinte SHA-256. L'API le charge une seule fois au
demarrage (`api_v4/registry.py`) et ne relit jamais Supabase.

Regenerer ce registre (sans reentrainer) apres tout changement d'artefact
deja entraine :

```bash
python -m src.pipelines.finalize_v4_product
```

## 3. Surveillance (monitoring)

- `GET /health` : etat de chargement de chaque modele, erreurs de
  chargement le cas echeant, disponibilite generale.
- `GET /metrics` : compteurs operationnels (requetes totales, repli
  declenche, erreurs), utilisables comme base pour une alerte simple (taux
  de repli anormalement eleve = signal de degradation d'un modele).
- Chaque reponse de recommandation indique `fallback_used` et
  `fallback_reason` : traçable telle quelle dans des journaux applicatifs.

Ce qui manquerait pour une vraie surveillance de production : export au
format Prometheus/OpenTelemetry, alerte automatisee, tableau de bord,
conservation longue duree des metriques (`/metrics` reinitialise a chaque
redemarrage du processus).

## 4. Declencheurs de reentrainement (a definir avant toute mise en
production, non actifs aujourd'hui)

Sur donnees reelles, les signaux suivants justifieraient un reentrainement
— aucun n'est implemente ni surveille automatiquement dans ce produit
academique :

- derive detectee entre la distribution des features servies et celle de
  l'entrainement ;
- degradation du taux de repli sur `popularite_globale_v1` (signe que le
  modele principal echoue ou est sollicite hors de son perimetre connu) ;
- peremption du catalogue produit (`api_v4/data/recommendation_catalog.json`
  et `pricing_catalog.json` sont des instantanes figes a la fin de la
  fenetre d'entrainement, jamais rafraichis automatiquement) ;
- nouvelle livraison de donnees experimentales (comme le passage de V2/V3 a
  V4 dans ce projet).

## 5. Procedure de retour arriere (rollback)

Chaque etat du produit correspond a un commit Git identifie
(`code_version_git_commit`). Revenir a la version precedente revient a
extraire les artefacts `models/v4/` et le code `api_v4/`/`src/pricing_v4`/
`src/recsys_v4` d'un commit anterieur (`git checkout <commit> -- models/v4 api_v4 src/pricing_v4 src/recsys_v4`)
puis a relancer `python -m src.pipelines.finalize_v4_product` si necessaire.
Aucune ecriture externe (Supabase, deploiement) n'est impliquee par ce
retour arriere tant qu'il reste local.

## 6. Reproductibilite de l'environnement

`requirements.txt` couvre les dependances de modelisation (pandas, numpy,
scikit-learn, lightgbm, catboost, **xgboost** — ajoute a cette etape, il
manquait alors que `src.recsys_v4.models` l'utilise deja depuis
l'entrainement V4) ; `requirements-api.lock` couvre fastapi/uvicorn/pydantic ;
`requirements-api-dev.lock` couvre httpx/pytest pour les tests. Installation
complete pour developper ou tester ce produit :

```bash
pip install -r requirements.txt -r requirements-api.lock -r requirements-api-dev.lock
```

## 7. Verification unique avant toute decision (point d'entree CI)

```bash
python -m scripts.run_v4_checks
```

Enchaine, dans l'ordre, et s'arrete au premier echec : garde-fou
d'immutabilite du forecasting, tests pricing V4, tests recommandation V4,
tests API, tests d'integration (lancement reel d'un serveur uvicorn), puis
validation de tous les manifestes SHA-256 du depot. Aucune etape ne
reentraine un modele, n'ecrit dans Supabase, ne pousse ni ne deploie quoi
que ce soit — ce script est concu pour etre appele par un futur pipeline
d'integration continue, mais n'est lui-meme ni planifie ni declenche
automatiquement.

## 8. Ecarts restants avant une mise en production reelle

- Pas d'authentification ni de limitation de debit sur l'API.
- Instantanes de catalogue figes, pas de connexion a une source de features
  vivante et gouvernee.
- Aucune surveillance de derive ni de reentrainement automatique.
- `/metrics` est en memoire (perdu au redemarrage), pas persiste ni exporte.
- Aucun test de charge ni de resilience (temps de reponse sous charge,
  comportement en cas de pic de trafic).
- Toutes les donnees restent synthetiques : une validation sur donnees
  reelles resterait necessaire avant toute revendication de performance
  commerciale.
