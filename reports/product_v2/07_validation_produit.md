# 07 — Validation du produit V2

Branche : `product/v2-web-interface`, issue de `feature/dockerized-model-api`
(`c77a04f`), elle-même descendante du squash corrigé `40bdfae`.

## Critères de validation

| Critère | Statut | Preuve |
|---|---|---|
| Aucune erreur 500 sur les scénarios normaux | ✅ | 0 sur 76 appels avant, 0 sur 38 après |
| Tous les endpoints principaux répondent | ✅ | 38/38 conformes en local |
| Erreurs utilisateur propres et compréhensibles | ✅ | format unique, messages français, testé |
| Modèles chargés et identifiés | ✅ | `/ready` : 5 contrôles OK, `/models` |
| Métriques officielles correctes | ✅ | comparées à `FINAL_STATUS.json` par test |
| Aucune métrique invalidée affichée | ✅ | balayage API + statiques, testé |
| Interfaces responsive | ✅ | 375 / 500 / 1280 px, aucun débordement |
| Tests backend réussis | ✅ | 53 passés, 1 ignoré |
| Tests frontend réussis | ✅ | navigation, formulaires, résultats vérifiés |
| **Build Docker réussi** | ❌ | **démon indisponible, non exécuté** |
| **Healthcheck réussi** | ❌ | **non exécuté, faute de démon** |
| Aucune donnée sensible versionnée | ✅ | `.env` jamais suivi, `.dockerignore` vérifié |
| Aucune dépendance à un chemin local Windows | ✅ | test `test_no_tracked_file_leaks_an_absolute_local_path` |
| Première utilisation compréhensible sans Swagger | ✅ | exemples préremplis sur les trois modules |
| Aucune table ou donnée V3 utilisée | ✅ | seuls le bundle V2 et `FINAL_STATUS.json` sont lus |

**Deux critères ne sont pas satisfaits** : le build Docker et le healthcheck
n'ont pas pu être exécutés faute de démon Docker sur ce poste. Le Dockerfile a
été corrigé et est couvert par des contrôles statiques, mais je ne peux pas
affirmer que l'image se construit et démarre.

## Avant / après

| Indicateur | Avant | Après (local) |
|---|---:|---:|
| Scénarios conformes | 32/38 | **38/38** |
| Erreurs 500 | 0 | 0 |
| Endpoints exposés | 7 | **13** |
| Interface web | console technique | **6 pages françaises responsive** |
| Métriques codées en dur | 2 dans `main.py` | **0** |
| `NaN` en entrée pricing | accepté silencieusement | **rejeté (422)** |
| Contexte pricing obligatoire | oui | non, repli catalogue |
| Blocage d'une remise | annule toute la simulation | **par remise, avec motif** |
| Forecasting | non exposé | backtest validé consultable |
| Tests API | 28 | **53** |

## Statuts publiés dans l'interface

| Domaine | Modèle | Métrique | Statut affiché |
|---|---|---|---|
| Prévision 30 j | `LightGBM_direct_per_horizon` | WAPE30 macro 0,25831 · micro 0,25743 · biais −0,02589 | Validé |
| Prévision quotidienne | `CrostonOptimized` | — | Validé, non exposé par l'API |
| Remise | `lgbm_tweedie_moyenne` | WAPE 0,5526 · biais +0,0013 | Exploratoire — non causal |
| Recommandation générale | `popularite_globale` | Recall@10 0,06686 · NDCG@10 0,03771 · couverture 6,08 % | Baseline validée |
| Complément panier | `popularite_globale` (repli) | Recall@10 0,05558 · NDCG@10 0,02400 · couverture 4,22 % | `none_validated` |
| RRF | — | — | challenger diversité, non promu |
| Sessionnel | — | — | `non_utilisable` |

Le modèle `lgbm_l1_mediane` est déclaré **non exposé**, avec son motif : biais de
volume de −18,14 %, interdit pour toute simulation de marge.

## Ce qui reste cassé côté Render

Le déploiement public **n'a pas été touché** : aucun déploiement n'était
autorisé. Il reste dans l'état constaté en Phase 1 :

- `/` renvoie 404 : le commit déployé est antérieur à toute interface ;
- `API_KEY` est défini : les 7 endpoints fonctionnels renvoient 401 ;
- les 6 nouveaux endpoints n'existent pas encore côté Render.

Classification : **variable d'environnement** et **commit déployé obsolète**,
pas un bug de code. `/ready` répond correctement et les artefacts y sont
vérifiés : le service fonctionne, il est seulement en retard et verrouillé.

## Commandes de reproduction

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8013
```

```bash
python -m scripts.api_test_matrix --base http://127.0.0.1:8013 --label local_after --out /tmp/after.json
```

```bash
python -m pytest api/tests -q
```

```bash
python -m api.scripts.extend_bundle_readonly
```
