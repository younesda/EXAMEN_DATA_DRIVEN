# 04 — Tests backend

Commande : `python -m pytest api/tests -q`
Résultat : **53 passés, 1 ignoré** (le test Docker, faute de démon disponible).

## Couverture par exigence

| Exigence | Test | Statut |
|---|---|---|
| Santé | `test_health` | OK |
| Readiness | `test_ready_declare_chaque_controle` | OK |
| Version | `test_version_expose_le_commit_et_l_environnement` | OK |
| Métriques | `test_metrics_publie_les_trois_domaines` | OK |
| Catalogue | `test_catalogue_est_trie_par_popularite` | OK |
| Recherche | `test_recherche_produit_filtre_et_borne` | OK |
| Forecasting valide | `test_forecast_renvoie_un_backtest_valide` | OK |
| Forecasting invalide | `test_forecast_borne_l_horizon` (0, 31, 999 → 422) | OK |
| Pricing valide | `test_pricing_accepte_un_contexte_vide` | OK |
| Pricing invalide | `test_pricing_rejette_les_valeurs_non_finies` | OK |
| Produit absent | `test_forecast_refuse_un_produit_inconnu` (404) | OK |
| Client absent | `reco_client_inexistant` (matrice, 200 + repli) | OK |
| Modèle absent | `test_registry_unavailable_is_degraded` | OK |
| Artefact corrompu | `test_loader_rejects_tampered_manifest` | OK |
| NaN / Infini | `test_pricing_rejette_les_valeurs_non_finies` | OK |
| Sérialisation JSON | `test_toutes_les_erreurs_partagent_le_meme_format` | OK |
| Garde-fous pricing | `test_les_garde_fous_pricing_restent_declares` | OK |
| Fallbacks | `test_mode_partiel_bloque_par_remise_sans_annuler_la_simulation` | OK |

## Tests notables

**`test_les_deux_perimetres_de_recommandation_restent_separes`** — vérifie que
la recommandation générale (0,06686 / 0,03771) et le complément panier
(0,05558 / 0,02400) restent deux jeux distincts, et que `ndcg` général ≠ `ndcg`
panier. C'est le garde-fou de la divergence documentée en rapport 02.

**`test_aucune_metrique_invalidee_n_est_exposee`** et
**`test_l_interface_n_affiche_aucune_metrique_invalidee`** — balaient les
réponses API et les trois fichiers statiques à la recherche de 0,4164, 0,437,
0,213, 0,1006 et 0,0485.

**`test_dockerfile_copies_every_runtime_module`** — contrôle statique qui compare
les modules de `api/*.py` aux instructions `COPY` du Dockerfile. Il a été écrit
après la découverte que `api/status.py` et `api/static/` n'étaient pas copiés :
l'image aurait été cassée sans qu'aucun test local n'échoue.

**`test_toutes_les_erreurs_partagent_le_meme_format`** — vérifie la forme
`{success, error{code, message, details, request_id}}` sur 404, 422 et 404
métier, et l'absence de `Traceback`, `C:\` et `/home/` dans le corps.

## Correctifs backend appliqués

| Défaut | Correction |
|---|---|
| D2 — `NaN` accepté silencieusement | `math.isfinite` sur chaque feature et chaque remise, avant tout contrôle de bornes → 422 `NON_FINITE_VALUE` |
| D3 — endpoints manquants | `/version`, `/metrics`, `/models`, catalogue, recherche, forecasting |
| D4 — métriques dupliquées | `api/status.py`, source unique lisant `FINAL_STATUS.json` et le bundle |
| D5 — format d'erreur | enveloppe `success: false`, codes stables, message français |
| D6 — échec en bloc du pricing | `partial_results` : blocage **par remise** avec motif, sans annuler les scénarios valides |
| D7 — `stock_at_cutoff` obligatoire | contexte optionnel, repli sur le snapshot catalogue du produit |
| Dockerfile incomplet | `api/status.py` et `api/static/` ajoutés au `COPY` |

## Suite complète du projet

`python -m pytest tests api/tests -q` → **286 passés, 31 ignorés, 0 échec**.
Les 30 skips historiques (chaîne V1) sont inchangés ; le 31ᵉ est le test Docker.
