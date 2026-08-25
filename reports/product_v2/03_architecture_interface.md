# 03 — Architecture de l'interface

## 1. Stack retenue

La stack existante est FastAPI + Pydantic v2, sans frontend. Conformément à la
consigne (« n'ajoute pas une architecture lourde si elle n'est pas nécessaire »),
l'interface reste **servie par FastAPI lui-même** :

| Couche | Choix | Motif |
|---|---|---|
| Serveur | FastAPI, `StaticFiles` monté sur `/static` | déjà présent, un seul déployable |
| Page | un `index.html` unique, routage par ancre | pas de build, pas de bundler |
| Script | JavaScript natif, `api/static/app.js` | aucune dépendance, aucun CDN |
| Style | CSS local, `api/static/styles.css` | mobile-first, variables CSS |
| Graphiques | SVG dessiné à la main dans `app.js` | évite une bibliothèque de 200 ko |

**Aucune requête réseau externe** : ni CDN, ni police distante, ni bibliothèque
tierce. L'interface fonctionne hors ligne dès que l'API répond, ce qui la rend
robuste en salle d'examen.

### Pourquoi la même origine

L'interface appelle l'API sur la même origine. Cela supprime toute question de
CORS pour l'usage normal, et permet un déploiement unique. `CORS_ORIGINS` reste
configurable pour un éventuel frontend séparé.

## 2. Routes de l'interface

| Ancre | Page | Contenu |
|---|---|---|
| `#/accueil` | Accueil et synthèse | trois modules, statut, modèle, métrique principale, avertissement |
| `#/performances` | Performances | métriques par domaine, sens de lecture, limites, historique invalidé |
| `#/prevision` | Prévision | produit, horizon 7/14/30, total, graphique, tableau, export CSV |
| `#/pricing` | Simulateur de remise | remises supportées, garde-fous par scénario, marge |
| `#/recommandation` | Recommandation | visiteur anonyme ou panier, Top-K, origine de la sortie |
| `#/technique` | État technique | version, contrôles, modèles, limites, clé d'accès |

`/console` conserve l'ancienne console technique, pour ne rien casser.

## 3. Endpoints backend ajoutés

| Endpoint | Accès | Rôle |
|---|---|---|
| `GET /version` | public | version API, bundle, commit, environnement |
| `GET /metrics` | public | métriques officielles centralisées, avec explications |
| `GET /models` | public | modèles exposés, statuts, modèle interdit et son motif |
| `GET /api/v1/catalog/products` | public | catalogue trié par popularité, paginé |
| `GET /api/v1/catalog/search` | public | recherche par référence, bornée à 50 |
| `POST /api/v1/forecast` | clé si configurée | consultation du backtest validé |

**Choix d'accès.** Aucun endpoint ne mute quoi que ce soit et les données sont
synthétiques. Les endpoints de lecture sont donc publics, ce qui rend
l'interface utilisable immédiatement ; les endpoints de calcul respectent
`API_KEY` s'il est défini, et l'interface propose alors un champ dédié dans
« État technique ». L'interface fonctionne dans les deux configurations.

## 4. Source centrale de vérité

`api/status.py` est le seul endroit où les métriques prennent une forme
affichable. Il lit `models/FINAL_STATUS.json` et le bundle, tous deux vérifiés
par SHA-256 au démarrage. **Aucune métrique n'est plus codée en dur** dans
`main.py`.

Chaque métrique exposée porte : sa valeur, son libellé, le sens de lecture
(`lower` / `higher` / `zero`), une explication en français, et surtout ce
qu'elle **ne permet pas** de conclure.

### Règle de périmètre

`build_domains` expose les deux périmètres de recommandation **séparément** :

- **Recommandation générale — prochain achat** : Recall@10 0,06686, NDCG@10
  0,03771, couverture 6,08 %, sur 4 fenêtres de 30 jours ;
- **Complément panier — leave-one-item-out F2–F4** : Recall@10 0,05558,
  NDCG@10 0,02400, couverture 4,22 %, statut `none_validated`.

Un test (`test_les_deux_perimetres_de_recommandation_restent_separes`) vérifie
que les deux jeux restent distincts et ne peuvent pas fusionner.

## 5. Forecasting : ce qui est exposé, et ce qui ne l'est pas

Le bundle ne contenait aucun artefact de prévision (`forecasting.exposed =
false`). Plutôt que de fabriquer une prédiction, l'API **republie la dernière
fenêtre du backtest validé** : cutoff 2026-07-01, 30 jours, 300 produits,
issue de `direct_lightgbm_predictions.parquet`.

La réponse le déclare explicitement : `kind = "backtest_valide"`, et
l'interface affiche « backtest validé, non recalculé en direct ». Un produit
absent de la fenêtre reçoit un repli documenté (`fallback_used = true`) avec son
motif, jamais une valeur inventée.

L'extension a été faite par `api/scripts/extend_bundle_readonly.py`, qui
**ne réentraîne rien** : `pricing_model.joblib` et `catalog.json` sont
inchangés. Le script `build_model_bundle.py` d'origine, qui réajuste le modèle,
n'a pas été utilisé et reste intact.

## 6. Format d'erreur

```json
{
  "success": false,
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "message": "Le produit demandé est introuvable.",
    "details": {},
    "request_id": "…"
  }
}
```

Codes HTTP : 200 succès · 400 requête incohérente · 404 ressource absente ·
409 garde-fou métier · 422 validation · 501 non implémenté · 503 dépendance
indisponible · 500 réservé aux erreurs internes réelles.

`CODE_ALIASES` traduit les codes internes en codes stables en majuscules.
Un test vérifie qu'aucune réponse d'erreur ne contient de trace d'exécution ni
de chemin local.

## 7. Expérience utilisateur

Chaque formulaire applique le même contrat, implémenté une seule fois dans
`brancheEnvoi()` :

- exemple prérempli valide et bouton **« Charger un exemple »** ;
- bouton désactivé et libellé « Traitement… » pendant la requête ;
- double clic impossible (verrou `enCours`) ;
- loader animé, respectant `prefers-reduced-motion` ;
- au-delà de 3,5 s, message dédié au réveil du serveur ;
- délai de 75 s, adapté à un cold start Render ;
- en cas d'échec, message en français, code stable, bouton **Réessayer** ;
- **les valeurs saisies sont conservées** : le formulaire n'est jamais réinitialisé ;
- listes vides gérées par un état vide explicite.

## 8. Accessibilité

- `lang="fr"`, titres hiérarchisés, `<caption class="sr-only">` sur les tableaux ;
- lien d'évitement « Aller au contenu principal » ;
- `aria-current="page"` sur l'onglet actif, `aria-live` sur la zone de vue,
  `role="alert"` sur les erreurs ;
- cibles tactiles de 44 px minimum ;
- focus visible à fort contraste ;
- couleur jamais seule porteuse de sens : chaque badge porte un texte.

## 9. Responsive vérifié

| Largeur | Grilles | Débordement horizontal |
|---|---|---|
| 375 px (mobile) | 1 colonne | aucun |
| 500 px | 1 colonne | aucun |
| 1280 px (desktop) | 3 et 2 colonnes | aucun |

La navigation défile horizontalement sur mobile ; les tableaux larges défilent
dans leur propre conteneur, jamais la page.
