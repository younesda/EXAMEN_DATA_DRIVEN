# 01 — Audit fonctionnel initial de l'API

Photographie de l'état **avant toute correction**, conformément à la Phase 1.
Aucun modèle réentraîné, aucune métrique modifiée, aucune écriture Supabase,
aucun déploiement.

- Branche de travail : `product/v2-web-interface`
- Base : `feature/dockerized-model-api` (`c77a04f`), descendant vérifié du squash
  corrigé `40bdfae`
- Matrice brute : [`api_test_matrix_before.json`](api_test_matrix_before.json)

---

## 1. Quelle branche sert le déploiement Render ?

La branche distante `feature/dockerized-model-api` est à `c77a04f`
(« feat(api): add interactive web console »). **Le déploiement Render ne
correspond pas à ce commit.**

Preuve : le commit `c77a04f` ajoute les routes `/` et `/ui` (voir `api/ui.py` et
`api/main.py`). En local, `GET /` renvoie **200**. Sur Render, `GET /` et
`GET /ui` renvoient **404**. Le service déployé est donc antérieur à `c77a04f`,
soit `8c92669` soit `a9b5dc2`.

L'OpenAPI publié par Render confirme le périmètre déployé :

```
GET   /health
GET   /ready
GET   /api/v1/models/status
POST  /api/v1/pricing/simulate
POST  /api/v1/recommendations/general
POST  /api/v1/recommendations/basket
POST  /api/v1/recommendations/session
```

`/ready` répond `{"status":"ready","checks":{"models_loaded":true,
"metadata_present":true,"sha256_valid":true,"versions_consistent":true}}` : les
artefacts sont bien chargés et vérifiés côté Render. **Le déploiement n'est pas
cassé ; il est seulement en retard d'un commit et verrouillé par une clé API.**

## 2. Cold start Render

| Appel | Durée |
|---|---:|
| Premier `GET /health` | 0,49 s |
| Second `GET /health` | 0,10 s |

Le service était **déjà chaud** au moment du test : aucun réveil à froid n'a été
observé. L'écart de 0,39 s correspond à l'établissement TLS, pas à un démarrage
de conteneur. Un cold start réel sur le plan gratuit Render se traduit
typiquement par 30 à 60 s ; l'interface devra malgré tout le gérer, car le
service se met en veille après inactivité.

## 3. Endpoints inventoriés

| Endpoint | Local | Render | Commentaire |
|---|---|---|---|
| `GET /health` | 200 | 200 | conforme |
| `GET /ready` | 200 | 200 | conforme, artefacts vérifiés |
| `GET /` et `/ui` | 200 | **404** | console web non déployée |
| `GET /docs` | 200 | 200 | Swagger disponible |
| `GET /openapi.json` | 200 | 200 | conforme |
| `GET /api/v1/models/status` | 200 | **401** | protégé par clé API |
| `POST /api/v1/recommendations/general` | 200 | **401** | protégé |
| `POST /api/v1/recommendations/basket` | 200 | **401** | protégé |
| `POST /api/v1/recommendations/session` | 501 | **401** | protégé, non utilisable par conception |
| `POST /api/v1/pricing/simulate` | 200 | **401** | protégé |
| `GET /version` | **404** | **404** | **absent** |
| `GET /metrics` | **404** | **404** | **absent** |
| `GET /models` | **404** | **404** | **absent** |
| catalogue produit | **404** | **404** | **absent** |
| recherche / autocomplétion | **404** | **404** | **absent** |
| forecasting | **404** | **404** | **non exposé** (`forecasting.exposed = false`) |

## 4. Résultat de la matrice de tests

38 scénarios : requête valide, corps vide, champs manquants, mauvais types,
produit inexistant, client inexistant, horizon invalide, remise invalide, JSON
malformé, feature interdite, NaN, infini.

| Cible | Scénarios | Conformes | Non conformes | **HTTP 500** |
|---|---:|---:|---:|---:|
| Render | 38 | 8 | 30 | **0** |
| Local | 38 | 32 | 6 | **0** |

**Aucune erreur 500 nulle part.** C'est le point fort de la base existante : le
backend est déjà solide sur la gestion d'erreurs.

Les 30 écarts côté Render s'expliquent presque entièrement par deux causes, non
par des bugs applicatifs :

1. **`API_KEY` est défini sur Render** → 24 scénarios renvoient 401 sans jamais
   atteindre la logique métier ;
2. **6 endpoints n'existent pas encore** (`/version`, `/metrics`, `/models`,
   catalogue, recherche, forecasting).

## 5. Défauts réels identifiés

### D1 — L'API publiée est inutilisable sans clé (bloquant démo)

Tous les endpoints fonctionnels renvoient 401. Un visiteur de
`https://examen-data-driven.onrender.com` n'obtient rien d'exploitable, et `/`
renvoie 404. **Pour une démonstration d'examen, le produit publié est
actuellement une page d'erreur.**

Classification : *variable d'environnement* + *routage*, pas un bug de code.

### D2 — `NaN` accepté silencieusement dans les features pricing (correctness)

```
POST /api/v1/pricing/simulate
features = {"stock_at_cutoff": NaN}
→ 200, predicted_quantity = 2.3879
```

Le contrôle de bornes est `if value < minimum or value > maximum`. Toute
comparaison avec `NaN` est fausse, donc le garde-fou est traversé sans bruit et
le modèle reçoit un `NaN`. La réponse **paraît normale** alors qu'elle repose sur
une entrée invalide : c'est plus grave qu'une erreur, car rien ne signale le
problème.

L'infini, lui, est correctement intercepté (409 `feature_extrapolation`),
uniquement parce que `inf > maximum` est vrai. La protection est donc
accidentelle, pas intentionnelle.

### D3 — Six endpoints manquants pour un produit fini

`/version`, `/metrics`, `/models`, catalogue produit, recherche produit. Sans
catalogue ni recherche, aucune interface ne peut proposer de sélectionner un
produit parmi 300 sans que l'utilisateur connaisse déjà les identifiants.

### D4 — Métriques dupliquées en dur dans le code

`api/main.py` code en dur `pricing_wape=0.5526` et `pricing_bias=0.0013`, et les
noms de modèles `"popularite_globale"` / `"lgbm_tweedie_moyenne"`. Ces valeurs
existent déjà dans `models/FINAL_STATUS.json` et dans le bundle. Trois copies
d'une même vérité peuvent diverger silencieusement.

### D5 — Format d'erreur sans enveloppe `success`

Format actuel : `{"request_id": ..., "error": {"code", "message", "details"}}`.
Format demandé : `{"success": false, "error": {"code", "message", "details",
"request_id"}}`. Écart de forme uniquement ; le contenu est déjà correct et les
codes HTTP sont déjà bien choisis (400 / 404 / 409 / 422 / 501 / 503).

### D6 — Le pricing échoue en bloc si une seule remise viole un garde-fou

`simulate()` lève une `ApiError` 409 dès qu'une remise passe sous le coût ou sous
la marge de 5 %. Avec plusieurs remises candidates, une seule remise invalide
annule toute la simulation. Pour l'interface, il faut un statut **par remise**
afin d'afficher les scénarios valides et d'expliquer le blocage des autres.

### D7 — Ergonomie : `stock_at_cutoff` obligatoire

L'API exige une feature technique que l'utilisateur final ne peut pas connaître.
Le catalogue contient pourtant déjà un `feature_snapshot` par produit :
l'interface devra pré-remplir cette valeur, et l'API accepter son absence en
retombant sur le snapshot.

---

## 6. Ce qui fonctionne déjà bien

À porter au crédit de la base existante, et à préserver :

- **zéro HTTP 500** sur 76 appels ;
- vérification SHA-256 des artefacts au démarrage, avec allowlist stricte ;
- refus explicite de charger un modèle invalidé (`RuntimeError` si le pricing
  sélectionné n'est pas `lgbm_tweedie_moyenne`, ou la reco autre que
  `popularite_globale`) ;
- refus de la feature `n_lignes` au chargement **et** à la requête ;
- garde-fous pricing déjà implémentés : prix ≥ coût, marge ≥ 5 %, remises
  limitées au support historique, extrapolation hors plage refusée ;
- `personalization_validated: false` et `catalog_coverage_warning: true` déjà
  exposés — la non-personnalisation est déjà annoncée honnêtement ;
- readiness dégradée : `ModelRegistry.unavailable()` évite le crash au démarrage ;
- validation Pydantic stricte (`extra="forbid"`, types stricts, bornes).

---

## 7. Divergence bloquante constatée en Phase 2

**Les métriques de recommandation annoncées dans la consigne ne correspondent pas
au périmètre du modèle général.** Le détail est en
[`02_divergence_metriques_recommandation.md`](02_divergence_metriques_recommandation.md).
Conformément à la consigne (« arrête-toi et documente la divergence avant de
modifier l'interface »), l'implémentation de l'interface est suspendue jusqu'à
arbitrage.

---

## 8. Commandes de reproduction

```bash
python -m scripts.api_test_matrix --base https://examen-data-driven.onrender.com --label render_before --out reports/product_v2/api_test_matrix_before.json
```

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8011
```

```bash
python -m scripts.api_test_matrix --base http://127.0.0.1:8011 --label local_before --out /tmp/matrix_local_before.json
```
