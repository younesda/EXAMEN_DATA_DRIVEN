# 08 — Documentation du premier produit V4

Statut : `synthetic_academic_experiment`. Ce document decrit le service
applicatif construit au-dessus des modeles V4 entraines et valides
(`reports/v4_training/01` a `07`). **Il s'agit d'un resultat academique sur
donnees synthetiques : aucune performance commerciale reelle n'est
revendiquee, aucun resultat n'est presente comme causal, et ce service n'est
pas concu pour un usage de production** (pas d'authentification, pas de
connexion a une base de donnees en direct, pas de gestion de charge).

---

## 1. Architecture

```
api_v4/
├── main.py                 point d'entree FastAPI, cablage des routes
├── config.py                chemins et constantes
├── registry.py               chargement unique des modeles et catalogues
├── schemas.py                schemas de requete/reponse (pydantic)
├── services/
│   ├── recommendation.py     construction des features, scoring, repli
│   └── pricing.py            simulation pricing, garde-fous
├── data/
│   ├── recommendation_catalog.json   instantane produit (grain produit)
│   ├── pricing_catalog.json          instantane produit pour le pricing
│   ├── categorical_mappings.json     tables valeur -> code (appareil/source/canal)
│   └── manifest.sha256.json
└── tests/
    └── test_api.py
```

Le service est entierement **local et hors-ligne au moment de la requete** :
aucun appel a Supabase, aucun entrainement declenche par une requete. Les
modeles entraines (`models/v4/{pricing,recommendation}/{cible}/model.joblib`)
et les instantanes de catalogue produit (`api_v4/data/*.json`) sont charges
une seule fois au demarrage par `api_v4/registry.py`. Le chargement de
chaque modele est isole : l'echec d'un seul n'empeche pas les autres de
fonctionner et declenche automatiquement le repli sur la popularite
globale pour ce modele-la uniquement.

`src/pipelines/finalize_v4_product.py` produit ces instantanes et
`models/v4/FINAL_STATUS.json` a partir des artefacts d'entrainement deja
existants — il ne reentraine rien.

### Pourquoi un contexte fourni par l'appelant, pas une lecture directe des clients

L'API de recommandation ne consulte aucune base client en direct : elle
applique le modele au contexte transmis dans la requete (identifiant client
optionnel, historique d'achat optionnel, appareil/source/canal optionnels).
Ce choix evite toute dependance a des donnees individuelles versionnees
(coherent avec la regle deja appliquee aux artefacts V1 : aucune donnee au
grain client n'est publiee) et rend le service entierement testable sans
acces reseau. Les features produit (categorie, marque, popularite figee a
la fin de la fenetre d'entrainement) proviennent, elles, de l'instantane de
catalogue.

**Consequence assumee** : le catalogue de recommandation ne couvre que les
208 produits ayant ete exposes au moins une fois pendant l'experience — 92
produits du catalogue global (300 produits) n'ont jamais ete proposes en
recommandation et sont traites comme indisponibles s'ils sont demandes.

---

## 2. Modeles retenus et statuts

| Role | Cible | Modele | Statut | Repli |
|---|---|---|:---:|---|
| Recommandation achat | `purchased_after` | `CatBoostRanker` | **validated_academic** | `popularite_globale_v1` |
| Recommandation ajout panier | `added_to_cart_after` | `pointwise_conversion` | **validated_academic** | `popularite_globale_v1` |
| Recommandation consultation | `viewed_after_impression` | `CatBoostRanker` | **exploratory** — non utilise par defaut | `popularite_globale_v1` |
| Secours general | toutes cibles | `popularite_globale_v1` | validated_academic | — |
| Pricing (3 cibles) | volume, CA, marge sur 7j | `baseline_mediane_produit` | validated_academic | — (reference elle-meme) |

Le statut `exploratory` de `viewed_after_impression` vient de la validation
independante (`07_validation_independante.md`) : le gain observe (+5,6 % de
NDCG@10) n'est pas demontre de facon statistiquement robuste (p brute
recalculee = 0,088, non significative meme avant correction). **Aucun
endpoint de l'API ne sert ce modele par defaut** ; il est neanmoins charge
et documente dans `/metadata` par transparence.

Le forecasting V2 (`LightGBM_direct_per_horizon`) n'a pas ete touche et
n'est expose par aucun endpoint de ce produit.

---

## 3. Metriques (rappel, detail complet dans `01_pricing_results.md` et `02_recommendation_results.md`)

### Recommandation (NDCG@10, gain relatif vs `popularite_globale_v1`, IC95 % de la validation independante)

| Cible | NDCG@10 | Gain | IC95 % (indep.) | p Holm (indep.) |
|---|---:|---:|---|---:|
| `purchased_after` | 0,01258 | +8,57 % | entierement positif | 0,00075 |
| `added_to_cart_after` | 0,01438 | +7,70 % | entierement positif | 0,0015 |
| `viewed_after_impression` | 0,01194 | +5,57 % | entierement positif, borne basse proche de 0 | 0,088 (non significatif) |

### Pricing (WAPE macro de la baseline retenue)

| Cible | WAPE macro | Biais |
|---|---:|---:|
| `units_sold_window_7j` | 0,1342 | +0,0054 |
| `revenue_window_xof_7j` | 0,1299 | +0,0020 |
| `margin_window_xof_7j` | 0,1305 | +0,0004 |

Garde-fous verifies sur 11 799 decisions : 0 marge negative, 0 remise sous
le cout.

---

## 4. Limites

- **Aucune revendication causale.** La confusion structurelle entre remise
  et identite produit (documentee dans `01_pricing_results.md`) signifie
  que les predictions de volume/CA/marge du pricing **ne varient pas** avec
  la remise proposee a l'appel de l'API : elles restent des medianes
  historiques par produit, quelle que soit la remise simulee. Seul le
  prix simule lui-meme et le controle de garde-fou (prix >= cout) reagissent
  a la remise fournie. Ce point est repete explicitement dans chaque reponse
  de `/pricing/simulation`.
- **`viewed_after_impression` n'est pas utilise par defaut** : gain non
  confirme par la validation independante.
- **Aucune application automatique.** Le pricing n'est qu'une simulation ;
  aucun prix n'est ecrit ou modifie nulle part. La recommandation renvoie un
  classement, jamais une action executee.
- **Instantane fige, pas un flux temps reel.** Les features produit
  (popularite, prix catalogue) sont figees a la fin de la fenetre
  d'entrainement ; elles ne se mettent pas a jour avec de nouvelles ventes.
- **Disponibilite = appartenance au catalogue connu.** Aucun signal de stock
  en temps reel n'est utilise par la recommandation (a la difference du
  pricing, qui dispose de `stock_at_decision` a l'entrainement mais pas au
  moment de la simulation).
- **Pas un service de production** : pas d'authentification, pas de
  limitation de debit, pas de connexion a une base de donnees en direct,
  donnees entierement synthetiques.

---

## 5. Exemples de requetes et reponses

### `GET /health`

```json
{
  "status": "ok",
  "product": "v4_pricing_recommendation",
  "data_status": "synthetic_academic_experiment",
  "models_loaded": {
    "recommendation": ["added_to_cart_after", "purchased_after", "viewed_after_impression"],
    "pricing": ["margin_window_xof_7j", "revenue_window_xof_7j", "units_sold_window_7j"]
  },
  "load_errors": {},
  "uptime_seconds": 13.16
}
```

### `POST /recommendations`

Requete :

```json
{
  "candidate_products": ["PRD000002", "PRD000003", "PRD000004", "PRD000005", "PRD000006"]
}
```

Reponse :

```json
{
  "target": "purchased_after",
  "target_status": "validated_academic",
  "model_requested": "CatBoostRanker",
  "model_used": "CatBoostRanker",
  "served_model_status": "validated_academic",
  "fallback_used": false,
  "fallback_reason": null,
  "status": "validated_academic",
  "version": "c5cb7d9e26c193502d3549c7e75dcc6b316ee6a9",
  "dropped_products": [],
  "results": [
    {"product_id": "PRD000002", "score": 0.367766, "rank": 1},
    {"product_id": "PRD000005", "score": -0.530592, "rank": 2},
    {"product_id": "PRD000006", "score": -0.975398, "rank": 3},
    {"product_id": "PRD000004", "score": -1.012823, "rank": 4},
    {"product_id": "PRD000003", "score": -1.287971, "rank": 5}
  ],
  "avertissement": "Resultat academique sur donnees synthetiques : ne constitue ni une revendication de performance commerciale reelle, ni un effet causal."
}
```

Meme requete sur `POST /recommendations/cart` : `target` devient
`added_to_cart_after`, `model_requested` et `model_used` deviennent
`pointwise_conversion`.

#### Champs de statut : quoi lire, et quand

Trois champs distincts evitent toute ambiguite lorsqu'un repli survient :

| Champ | Signification |
|---|---|
| `target_status` | statut du modele **prevu** pour la cible demandee |
| `model_requested` | modele qui aurait ete utilise sans incident |
| `model_used` | modele **reellement** utilise pour ce classement |
| `served_model_status` | statut du modele reellement utilise — **c'est ce champ qui qualifie le resultat renvoye** |

`status` est conserve pour compatibilite ascendante et vaut toujours
`target_status` ; les consommateurs doivent lui preferer
`served_model_status`. Exemple de reponse en repli (modele principal
indisponible), ou les deux modeles different :

```json
{
  "target": "purchased_after",
  "target_status": "validated_academic",
  "model_requested": "CatBoostRanker",
  "model_used": "popularite_globale_v1",
  "served_model_status": "validated_academic",
  "fallback_used": true,
  "fallback_reason": "modele_indisponible"
}
```

### `POST /pricing/simulation`

Requete :

```json
{"produit_key": "PRD000002", "discount_proposed": 15}
```

Reponse :

```json
{
  "produit_key": "PRD000002",
  "categorie": "Telephonie & Accessoires",
  "classe_abc": "A",
  "prix_catalogue_xof": 226420.0,
  "cout_xof": 153995.0,
  "remise_proposee_pct": 15.0,
  "prix_simule_xof": 192457.0,
  "volume_estime_unites_7j": 10.5,
  "chiffre_affaires_estime_xof": 2258539.5,
  "marge_estimee_xof": 641592.0,
  "modele": "baseline_mediane_produit",
  "version": "c5cb7d9e26c193502d3549c7e75dcc6b316ee6a9",
  "garde_fous": {"prix_sous_cout": false, "marge_negative": false},
  "avertissement": "Simulation academique sur donnees synthetiques : aucune revendication causale, aucune application automatique du prix simule. Volume, chiffre d'affaires et marge estimes sont des medianes historiques par produit (baseline_mediane_produit) : ils ne varient PAS avec la remise proposee ci-dessus [...]"
}
```

### Cas d'erreur

| Scenario | Requete | Reponse |
|---|---|---|
| Remise faisant tomber le prix sous le cout | `discount_proposed: 95` sur `PRD000002` | `422 {"detail": "prix simule (11321.00 XOF) inferieur au cout produit (153995.00 XOF)"}` |
| Produit pricing inconnu | `produit_key: "PRD_INEXISTANT"` | `404 {"detail": "produit inconnu du catalogue pricing : PRD_INEXISTANT"}` |
| Doublons dans la liste de candidats | `["PRD000002", "PRD000002"]` | `422`, erreur de validation `candidate_products contient des doublons` |
| Tous les candidats inconnus | `["PRD_X1", "PRD_X2"]` | `422 {"detail": "aucun des produits candidats n'appartient au catalogue connu : ..."}` |
| Un modele indisponible (fichier absent/corrompu) | requete normale | `200`, `fallback_used: true`, `fallback_reason: "modele_indisponible"`, `model_used: "popularite_globale_v1"` |

---

## 6. Procedure de lancement

```bash
python -m uvicorn api_v4.main:app --host 127.0.0.1 --port 8099
```

Puis : `http://127.0.0.1:8099/docs` pour la documentation interactive
(Swagger, generee automatiquement par FastAPI), ou directement les
endpoints listes ci-dessus.

Prealable, une seule fois (ou apres tout reentrainement) : regenerer les
instantanes de catalogue et la fiche de statut consolidee —

```bash
python -m src.pipelines.finalize_v4_product
```

### Deploiement en service distant

Le depot contient deux images distinctes, qui ne doivent pas etre confondues :

| Fichier | Application servie | Service |
|---|---|---|
| `Dockerfile` | `api.main:app` | API V2, service existant, a ne pas modifier |
| `Dockerfile.api_v4` | `api_v4.main:app` | API V4, service separe |

Le `Dockerfile` a la racine construit l'API V2 : il copie `api/` et
`models/api_bundle/` et sonde `/ready`. Une plateforme qui detecte
automatiquement ce fichier deploie donc la V2 en croyant deployer la V4 —
c'est precisement l'incident observe lors du premier deploiement. Le fichier
`render.yaml` designe explicitement `dockerfilePath: ./Dockerfile.api_v4`
pour lever cette ambiguite.

L'image V4 embarque uniquement `api_v4/`, les modules `src/` necessaires au
rechargement des modeles, et les six fichiers `model.joblib` (environ 0,7 Mo
au total). Les CSV de reproductibilite (environ 104 Mo) restent hors de
l'image : ils servent l'audit, jamais le service.

**Identifier la version reellement en ligne.** `/health` et `/metadata`
exposent deux champs dedies :

```json
{"service": "api_v4", "deployed_commit": "<sha du commit deploye>"}
```

Le critere fiable pour distinguer les deux services n'est pas `/health`
(present dans les deux) mais la presence des routes V4 (`/metadata`,
`/recommendations/cart`, `/pricing/simulation`) et l'absence des routes V2
(`/api/v1/...`, `/ready`).

---

## 7. Procedure de test

```bash
python -m pytest tests/test_v4_pricing.py tests/test_v4_recommendation.py api_v4/tests/test_api.py -q
python -m scripts.validate_manifests
```

Couverture des tests API (`api_v4/tests/test_api.py`) : reponses valides de
chaque endpoint, entrees invalides (champ manquant, liste vide, remise hors
bornes), modele absent (simule par retrait temporaire du registre), repli
(modele absent et exception de scoring), doublons, produits inconnus
(partiels et total), prix simule sous le cout, rechargement des modeles
depuis le disque avec verification d'identite des scores, determinisme des
reponses (meme requete deux fois, resultat strictement identique).

---

## 8. Distinction resultat academique / usage production

Ce produit est un **benchmark de pipeline reproductible sur donnees
synthetiques**, pas un systeme destine a servir de vrais clients :

- aucune connexion a Supabase ou a toute base de production au moment de la
  requete (tout est charge depuis des artefacts locaux deja versionnes) ;
- aucune authentification, aucune limitation de debit, aucune isolation
  multi-tenant ;
- les instantanes de catalogue sont figes a la fin de la fenetre
  d'entrainement, jamais rafraichis automatiquement ;
- toutes les donnees utilisees sont synthetiques
  (`statut_experience = synthetic_academic_experiment`) ;
- aucun resultat (pricing ou recommandation) ne doit etre interprete comme
  une mesure causale ou une performance commerciale reelle, quelle que soit
  la qualite apparente d'une metrique.

Une mise en production reelle necessiterait, au minimum : une source de
features vivante et gouvernee, une politique de secours testee en charge,
une authentification et un controle d'acces, un suivi de derive du modele
dans le temps, et une nouvelle validation sur donnees reelles.
