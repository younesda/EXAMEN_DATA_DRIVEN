# 07 — Matrice des contrôles actifs

Les 47 tests historiques restent ignorés : ils dépendent de `table_analytique.parquet` ou de prédictions V1 non versionnées. Ils ne sont pas réactivés. Cette matrice relie leurs contrôles importants aux tests et audits de la reconstruction finale.

| Ancien contrôle important | Équivalent actif final | Preuve |
|---|---|---|
| Grain produit × jour, doublons | Audit des cinq datasets + `test_paniers_grain_et_cible_confirmee_uniquement` | `01_data_audit.md`, nouveau test synthétique |
| Conservation et cible confirmée | `test_pricing_cible_et_grain_confirmes_explicitement`, test panier confirmé | Métadonnées pricing et builder panier |
| Bornes temporelles train/test | `test_forecasting_calibration_strictement_anterieure_aux_six_fenetres`, `test_pricing_calibration_lightgbm_strictement_anterieure` | Dates publiées dans les métadonnées |
| Anti-fuite des lags | `test_perturber_le_futur_ne_change_jamais_la_prevision`, `test_build_training_matrix_ne_depasse_jamais_le_train_fourni` | Tests actifs existants |
| Six fenêtres et périmètre | `test_forecasting_calibration_strictement_anterieure_aux_six_fenetres` | Politique finale à six fenêtres, indépendante de la V1 |
| Cold-start et historique court | `test_forecasting_cold_start_sans_nan_ni_negatif` | Fixture sans aucun historique |
| NaN, infinis et négatifs | même test + garde-fou d'exécution sur toutes les prédictions modèle-jour | Métadonnées forecasting |
| Déterminisme | `test_sessions_deterministes_a_horodatage_egal`, `test_bootstrap_recommandation_deterministe`, tests de popularité existants | Tie-break événement, seed bootstrap, scores |
| Promotions issues de la dimension | `test_audit_promotions_produit_et_categorie_sans_mismatch` | Portées produit/catégorie et dates contrôlées séparément |
| Prix payé, coût et marge | tests `test_pricing_dataset.py` + `test_pricing_bornes_cout_et_marge` | Formules unitaires et plancher 5 % |
| Candidats recommandables | `test_candidats_recommandation_exclus_et_deterministes`, `test_aucun_produit_ineligible_recommande` | Exclusions, finitude et éligibilité |
| Purchase web non doublé avec les ventes | `test_achats_web_non_doubles_et_futur_exclu_du_signal_hybride`, `test_evenements_purchase_exclus_du_profil_web` | Purchase exclu du signal hybride, cible issue des commandes |
| Sélection adaptative AutoETS/WA28 V1 | Sans équivalent requis | Candidat historique abandonné, absent des décisions finales |
| Comparabilité stricte aux six fenêtres V1 | Remplacée par le protocole final à six fenêtres | Les nouvelles fenêtres sont définies par dates et profondeur de train, pas par artefacts V1 absents |

Les contrôles ajoutés sont autonomes ou s'appuient sur des métadonnées versionnées; ils ne nécessitent aucun des artefacts historiques ignorés.
