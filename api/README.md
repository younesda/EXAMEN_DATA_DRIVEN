# API et interface web — modèles V2 corrigés

Interface française de démonstration des trois modules V2 : prévision de la
demande, simulation de remise et recommandation de produits.

## Lancement local

```bash
pip install -r requirements-api.lock
```

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8013
```

Puis ouvrir **http://127.0.0.1:8013/**.

Aucune clé n'est nécessaire en local : `API_KEY` est vide par défaut.

## Pages

| Adresse | Contenu |
|---|---|
| `/` | interface complète, six pages |
| `/docs` | documentation Swagger |
| `/console` | ancienne console technique |

## Endpoints

| Méthode | Chemin | Accès | Rôle |
|---|---|---|---|
| GET | `/health` | public | processus vivant |
| GET | `/ready` | public | artefacts chargés et vérifiés |
| GET | `/version` | public | version, bundle, commit, environnement |
| GET | `/metrics` | public | métriques officielles avec explications |
| GET | `/models` | public | modèles exposés et statuts |
| GET | `/api/v1/catalog/products` | public | catalogue trié par popularité |
| GET | `/api/v1/catalog/search?q=` | public | recherche par référence |
| GET | `/api/v1/models/status` | clé | métadonnées du bundle |
| POST | `/api/v1/forecast` | clé | prévision issue du backtest validé |
| POST | `/api/v1/pricing/simulate` | clé | simulation de remise sous garde-fous |
| POST | `/api/v1/recommendations/general` | clé | recommandation générale |
| POST | `/api/v1/recommendations/basket` | clé | complément panier (repli popularité) |
| POST | `/api/v1/recommendations/session` | clé | 501 : modèle non utilisable |

« clé » signifie : protégé **uniquement si** `API_KEY` est défini. Sans clé
configurée, tout est accessible — c'est le mode de démonstration.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `APP_ENV` | `development` | environnement affiché par `/version` |
| `API_HOST` | `0.0.0.0` | interface d'écoute |
| `API_PORT` | `8000` | port d'écoute |
| `LOG_LEVEL` | `INFO` | niveau de journalisation |
| `MODEL_ROOT` | `models` | racine des artefacts |
| `API_KEY` | vide | si défini, protège les endpoints de calcul |
| `CORS_ORIGINS` | `http://localhost:3000` | origines autorisées, séparées par des virgules |
| `GIT_COMMIT` | `unknown` | commit affiché ; `RENDER_GIT_COMMIT` sert de repli |
| `REQUEST_TIMEOUT_S` | `30` | délai applicatif |

Aucun secret n'est journalisé ni renvoyé dans une réponse d'erreur.

## Docker

```bash
docker build -t examen-api:v2 .
```

```bash
docker run --rm -p 8000:8000 -e API_KEY= examen-api:v2
```

Le conteneur tourne en utilisateur non privilégié, expose un `HEALTHCHECK` sur
`/ready` et n'embarque ni `.env`, ni données brutes, ni tests.

## Tests

```bash
python -m pytest api/tests -q
```

```bash
python -m scripts.api_test_matrix --base http://127.0.0.1:8013 --label local --out /tmp/matrix.json
```

## Régénérer le bundle

Extension additive, **sans réentraînement** — republie le backtest forecasting
validé et complète les métadonnées :

```bash
python -m api.scripts.extend_bundle_readonly
```

`api/scripts/build_model_bundle.py` reconstruit tout **en réajustant le modèle
pricing** : à n'utiliser que délibérément.

## Limites

- Données synthétiques, projet académique.
- La simulation de remise est observationnelle et **non causale** ; validation
  humaine obligatoire, aucune application automatique.
- La recommandation est une **baseline de popularité** ; aucune personnalisation
  forte n'est démontrée, aucun modèle de complément panier n'est validé.
- Les prévisions proviennent du **backtest validé**, pas d'une inférence en direct.
- Sur hébergement gratuit, le premier appel après inactivité peut demander
  jusqu'à une minute.
