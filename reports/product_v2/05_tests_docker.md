# 05 — Tests Docker

## Statut : build non exécuté dans cet environnement

`docker --version` puis `docker info` n'ont pas rendu la main (délai de 600 s
dépassé). Le démon Docker n'est pas démarré sur cette machine. Le build
`docker build --no-cache .` et le test en conteneur **n'ont donc pas pu être
exécutés**, et je ne les présente pas comme réussis.

Le test d'intégration `api/tests/test_docker.py` est en conséquence **ignoré**
(1 skip), et non passé.

## Ce qui a malgré tout été vérifié, statiquement

`api/tests/test_docker_manifest.py` — 5 contrôles qui ne nécessitent aucun démon :

| Contrôle | Résultat |
|---|---|
| Tous les modules `api/*.py` figurent dans un `COPY` | OK **après correction** |
| `api/static` et `api/services` sont copiés | OK **après correction** |
| Aucun `COPY` de `.env`, `api/tests`, `data/raw`, `data/processed`, `data/cache` | OK |
| `HEALTHCHECK` présent, ciblant `/ready` | OK |
| Port configurable via `${API_PORT}` | OK |
| Conteneur non root (`USER api`) | OK |
| `.dockerignore` exclut `.env`, `data`, `tests` | OK |
| Chaque asset référencé par la page existe | OK |

## Défaut Docker trouvé et corrigé

Le Dockerfile listait ses modules un par un :

```dockerfile
COPY api/__init__.py api/config.py api/errors.py api/logging.py api/main.py api/schemas.py api/ui.py ./api/
```

`api/status.py` (nouveau) et `api/static/` (l'interface) **n'y figuraient pas**.
L'image aurait démarré puis échoué à l'import de `api.status`, sans qu'aucun
test local ne le détecte. Corrigé :

```dockerfile
COPY api/__init__.py api/config.py api/errors.py api/logging.py api/main.py \
     api/schemas.py api/status.py api/ui.py ./api/
COPY api/services ./api/services
COPY api/static ./api/static
```

Le contrôle statique ajouté empêche la réapparition de ce défaut.

## Ce qui reste à vérifier avec un démon Docker

```bash
docker build --no-cache -t examen-api:v2 .
docker run --rm -d --name examen-api -p 8000:8000 -e API_KEY= examen-api:v2
docker inspect --format '{{.State.Health.Status}}' examen-api
python -m scripts.api_test_matrix --base http://127.0.0.1:8000 --label docker --out /tmp/matrix_docker.json
docker exec examen-api test ! -e /app/.env
docker exec examen-api test ! -d /app/api/tests
docker stop examen-api
```

Points à confirmer : démarrage sans volume local, healthcheck `healthy`,
absence de fichier sensible dans l'image, redémarrage propre, et les
38 scénarios de la matrice dans le conteneur.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `APP_ENV` | `production` | environnement affiché par `/version` |
| `API_HOST` | `0.0.0.0` | interface d'écoute |
| `API_PORT` | `8000` | port d'écoute, utilisé par le `CMD` |
| `LOG_LEVEL` | `INFO` | niveau de journalisation |
| `MODEL_ROOT` | `/app/models` | racine des artefacts vérifiés au démarrage |
| `API_KEY` | vide | si défini, protège les endpoints de calcul |
| `CORS_ORIGINS` | `http://localhost:3000` | origines autorisées, séparées par des virgules |
| `GIT_COMMIT` / `RENDER_GIT_COMMIT` | `unknown` | commit affiché par `/version` |
| `REQUEST_TIMEOUT_S` | `30` | délai applicatif |

Aucune de ces variables n'est journalisée avec sa valeur, et aucune n'apparaît
dans une réponse d'erreur.
