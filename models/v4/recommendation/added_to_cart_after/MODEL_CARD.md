# Model card — recommandation V4 — added_to_cart_after

Statut : `synthetic_academic_experiment`. Donnees synthetiques, projet
academique. Aucune performance commerciale reelle n'est revendiquee.

Modele retenu : `pointwise_conversion`.
NDCG@10 moyen : 0.0144
Recall@10 moyen : 0.0225

Cible : `added_to_cart_after`. Grain : reclassement des 5 candidats d'une slate.

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
