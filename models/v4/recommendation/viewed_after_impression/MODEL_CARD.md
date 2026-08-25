# Model card — recommandation V4 — viewed_after_impression

Statut : `synthetic_academic_experiment`. Donnees synthetiques, projet
academique. Aucune performance commerciale reelle n'est revendiquee.

Modele evalue : `CatBoostRanker`.
NDCG@10 moyen : 0.0119
Recall@10 moyen : 0.0193

Statut de promotion : EXPLORATOIRE, pas VALIDE. Une verification statistique
independante (voir reports/v4_training/07_validation_independante.md), menee
avec un test de permutation construit differemment de celui du pipeline
d'entrainement, obtient une p-value brute de 0.088 pour la comparaison a la
baseline popularite_globale_v1 : non significative au seuil conventionnel de
5%, meme avant toute correction pour comparaisons multiples. Le pipeline
d'entrainement obtenait deja une p-value corrigee Holm de 0.168 sur la meme
comparaison. Les deux verifications concordent : le gain est reproductible en
valeur ponctuelle mais n'est pas demontre de facon statistiquement robuste.
La reference retenue pour cette cible reste `popularite_globale_v1`.

Cible : `viewed_after_impression`. Grain : reclassement des 5 candidats d'une slate.

Features utilisees : category_code, brand_code, device_code, source_code, channel_code, prix_base_xof, client_purchase_count_before, client_recency_days, client_frequency_90d, client_category_affinity, product_popularity_before, product_recent_popularity_28d, is_anonymous, is_cold_start_client

Features explicitement exclues : `rank`, `model_score` (encodent la politique
qui a produit l'exposition ; usage reserve a l'evaluation « bout en bout » de
la liste servie), toute variable posterieure a l'impression, les trois cibles
elles-memes, `clicked` (absente de la semantique V4).

`exposure_probability_status = deterministic_top_k` : la selection reelle des
5 candidats est deterministe (Top-5 par score), pas un tirage selon le softmax
theorique de `product_exposure_probability`. Cette propension n'est jamais
utilisee comme poids IPS.

Limites : experience synthetique, aucune revendication causale, usage
academique et benchmark de pipeline uniquement.
