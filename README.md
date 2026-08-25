# E-commerce — Forecasting, Pricing et Recommandation

> ## AVERTISSEMENT — résultats partiellement invalidés le 2026-08-18
>
> Un audit indépendant a identifié **trois fuites de données**. Deux des trois
> références historiquement publiées sont **invalides** et ne doivent plus servir
> de cible ni de comparaison :
>
> | Domaine | Score publié | Statut |
> |---|---:|---|
> | Forecasting 30 j | WAPE 0,25831 | Autorisé — **valide**, reproduit à l'identique |
> | Pricing | WAPE **0,4164** | Interdit — `invalidated_due_to_target_leakage` — niveau honnête : **0,5526** |
> | Complément panier | Recall@10 **0,437** / NDCG@10 **0,213** | Interdit — `invalidated_due_to_target_category_leakage` — niveau honnête : **0,0556 / 0,0240** |
> | Complément panier (hérité) | Recall@10 **0,1006** / NDCG@10 **0,0485** | Interdit — `invalidated_due_to_in_sample_evaluation_without_temporal_split` |
>
> **Aucun modèle n'est promu sur aucun domaine.**
>
> Lire d'abord [`SUPERSEDED_RESULTS.md`](SUPERSEDED_RESULTS.md), puis la série
> « correction » : [17 — fuites](reports/42_leakage_correction_report.md) ·
> [18 — pricing](reports/43_corrected_pricing_results.md) ·
> [19 — recommandation](reports/44_corrected_recommendation_results.md) ·
> [20 — décision finale](reports/45_final_corrected_decision.md).
>
> **Statuts officiels lisibles par machine :** [`models/FINAL_STATUS.json`](models/FINAL_STATUS.json)
> — `forecasting_status = validated`, `pricing_status = exploratory_non_causal`,
> `basket_complement_model = none_validated`, `automatic_pricing_allowed = false`.
> `lgbm_l1_mediane` (biais −18,14 %) **ne doit pas** alimenter le simulateur de marge.
>
> Les tableaux ci-dessous datent d'avant l'audit. Ils sont conservés pour
> traçabilité et **annotés ligne par ligne** ; en cas de contradiction, la série
> 42–45 fait foi.

Livraison finale reconstruite à partir d'une extraction Supabase fraîche, contrôlée et strictement en lecture seule. Les données brutes et analytiques restent locales et sont exclues de Git. Aucun modèle n'est déployé et aucune décision n'est appliquée automatiquement.

## Résultats publiés avant l'audit (statut annoté)

| Domaine | Sélection finale | Validation temporelle | Résultat principal | Usage autorisé |
|---|---|---|---|---|
| Forecasting quotidien | `CrostonOptimized` | 6 fenêtres non chevauchantes de 30 jours | WAPE 1,0945; 4 victoires sur 6 | Prévision quotidienne supervisée |
| Forecasting cumulé 30 j | `LightGBM_Tweedie` | mêmes 6 fenêtres | WAPE cumulée 0,3106 | Autorisé — valide — **supersédé** par `LightGBM_direct_per_horizon`, WAPE30 0,25831 |
| Pricing | `LightGBM_calibre` | 3 fenêtres temporelles, calibration antérieure séparée | ~~WAPE 0,4164~~ | Interdit — **INVALIDÉ** — fuite `n_lignes`; sans la fuite : 0,5625. Modèle de volume officiel : `lgbm_tweedie_moyenne`, WAPE 0,5526, biais +0,0013 |
| Recommandation — prochain achat | baseline `popularite_globale`; hybride `challenger_exploratoire` | 3 fenêtres, bootstrap client-fenêtre | ΔNDCG hybride +0,00095, IC95 % contenant zéro | Autorisé — valide — baseline contrôlée |
| Recommandation — complément panier | ~~`popularite_categorie`~~ | leave-one-item-out F2–F4 | ~~Recall@10 0,437 / NDCG@10 0,213~~ | Interdit — **INVALIDÉ** — fuite catégorie cible. Statut : `none_validated`, baseline `popularite_globale` (0,0556 / 0,0240) |

Ces métriques mesurent des tâches différentes et ne doivent pas être comparées entre domaines. Aucun modèle forecasting n'est déclaré vainqueur global. Le gain de l'hybride de recommandation n'est pas statistiquement établi.

**Les lignes barrées ci-dessus proviennent de pipelines fuités.** Le détail des mécanismes, des preuves et des mesures d'inflation est dans [`reports/42_leakage_correction_report.md`](reports/42_leakage_correction_report.md).

## Données finales

L'audit a réconcilié 84 319 lignes de vente, 49 872 commandes, 657 392 événements web uniques et 117 763 observations de stock. Les cinq datasets reconstruits sont :

- `product_daily_forecasting` : 163 800 lignes;
- `product_day_discount_pricing` : 55 586 lignes;
- `order_baskets` : 80 130 lignes, commandes confirmées uniquement;
- `session_sequences` : 622 440 événements humains;
- `client_product_interactions` : 622 440 interactions.

Les bots sont exclus, les visiteurs anonymes restent anonymes, les achats web sont rattachés aux commandes réelles et ne sont jamais additionnés aux ventes. Les prix catalogue sont fixes pour les 300 produits : le pricing ne peut donc pas être présenté comme causal ni comme un optimum continu.

## Reproduction

Prérequis : Python 3.11+ et un `.env` local configuré avec un accès Supabase en lecture seule.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Extraction locale fraîche puis construction/audit
python -m src.pipelines.extract
python -m src.pipelines.final_build_datasets

# Entraînements séquentiels — ne pas les lancer en parallèle
python -m src.pipelines.final_forecasting
python -m src.pipelines.final_pricing
python -m src.pipelines.final_recommendation

# Série de correction des fuites (2026-08-18)
python -m src.experiments.pricing_corrected
python -m src.experiments.complement_leak_audit
python -m src.experiments.complement_honest_baseline
python -m src.experiments.complement_end_to_end
python -m src.experiments.complement_candidate_pilot
python -m src.pipelines.refresh_manifests

# Validation — 222 passés, 30 ignorés (historiques), 0 échec
python -m pytest -q
```

Le fichier `.env` est exclu par `.gitignore`. Ne jamais l'afficher, le journaliser ou le committer. Les répertoires `data/raw`, `data/cache`, `data/processed`, `checkpoints` et `logs` ne sont pas versionnés.

## Garde-fous métier

- Forecasting : aucun pilotage automatique; intervalles conformes 80/95 % calibrés uniquement sur des résidus antérieurs. Croston sert le quotidien, LightGBM Tweedie le cumul 30 jours.
- Pricing : prix jamais inférieur au coût, marge minimale configurable (5 % par défaut), remise limitée au support historique, validation humaine obligatoire. Le résultat est associatif, pas causal. **Le simulateur de marge est alimenté exclusivement par le modèle de volume à biais contrôlé** (`lgbm_tweedie_moyenne`, biais +0,0013), jamais par le meilleur prédicteur WAPE (`lgbm_l1_mediane`, biais −0,1814) : une sous-estimation de 18 % du volume fausserait toute projection de marge. Registre de disponibilité des features : [`src/pricing/feature_registry.py`](src/pricing/feature_registry.py).
- Recommandation : popularité globale comme baseline officielle; hybride exploratoire uniquement. **Complément panier : `basket_complement_model = none_validated`, `reason = no_complementarity_signal`** — les paniers sont statistiquement des tirages indépendants (0,2182 observé contre 0,222 attendu). Le scoring passe obligatoirement par [`src/recsys/complement.py`](src/recsys/complement.py), dont la signature rend la fuite structurellement impossible. Le scénario sessionnel est déclaré non utilisable.

## Artefacts et rapports

- Audit des données : [`reports/final/01_data_audit.md`](reports/final/01_data_audit.md)
- Forecasting : [`reports/final/02_forecasting.md`](reports/final/02_forecasting.md), `models/forecasting/`
- Pricing : [`reports/final/03_pricing.md`](reports/final/03_pricing.md) **invalidé** → [`reports/43_corrected_pricing_results.md`](reports/43_corrected_pricing_results.md), `models/advanced/pricing_corrected/`
- Recommandation : [`reports/final/04_recommendation.md`](reports/final/04_recommendation.md) **partiellement invalidé** → [`reports/44_corrected_recommendation_results.md`](reports/44_corrected_recommendation_results.md), `models/advanced/complement_honest/`
- Synthèse exécutive : [`reports/final/05_executive_summary.md`](reports/final/05_executive_summary.md)
- Addendum méthodologique : [`reports/final/06_methodology_addendum.md`](reports/final/06_methodology_addendum.md) **partiellement invalidé** (NDCG@10 0,0485)
- Matrice des contrôles actifs : [`reports/final/07_active_test_matrix.md`](reports/final/07_active_test_matrix.md)

Chaque répertoire de modèles contient des métadonnées et un manifeste SHA-256. Les anciens rapports V1 restent versionnés pour traçabilité.

**Référence courante après audit :** [`SUPERSEDED_RESULTS.md`](SUPERSEDED_RESULTS.md) et la série `reports/42` à `reports/45`. Les artefacts issus des pipelines fuités sont conservés, non supprimés, dans `models/pricing/metadata.invalidated.json` et `models/advanced/recommendation_ranking/invalidated/`, chacun avec son motif d'invalidation et son manifeste SHA-256.

## Statut de livraison

Branche de correction : branche d'audit independant (audit et correction des fuites du 2026-08-18).
Branche de la livraison initiale : `rebuild/final-enriched-dataset`.

Aucun merge vers `main`, aucun push, aucun déploiement et aucune écriture dans Supabase. L'historique Git et les branches distantes historiques ne sont pas modifiés : la série 42–45 les supersède.
