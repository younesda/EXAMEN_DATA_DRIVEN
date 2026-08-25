# Model card — pricing V4 — margin_window_xof_7j

Statut : `synthetic_academic_experiment`. Donnees synthetiques, projet
academique. Aucune performance commerciale reelle n'est revendiquee.

Modele retenu : `baseline_mediane_produit`.
WAPE macro (moyenne des 6 fenetres) : 0.1305
Biais moyen : +0.0004

Cible : `margin_window_xof_7j`. Grain : une decision de tarification hebdomadaire par produit.
Le prix effectivement applique est toujours `prix_applique_xof`, jamais la
remise proposee.

Features utilisees : product_code, category_code, abc_code, prix_base_xof, cout_xof, discount_proposed, discount_applied, eligible_for_discount, cold_start_warmup, stock_at_decision, pre_decision_views, pre_decision_views_28d, pre_decision_carts_28d, dow, week_of_year, month, is_weekend, warmup_sales_mean_28, warmup_sales_mean_84, warmup_sales_lag_7, warmup_sales_zero_rate_28, product_age_days, discount_x_category, discount_x_abc

Features explicitement exclues : `product_impressions` (constante par produit
dans la table livree, ne represente pas un cumul pre-decision), toute variable
posterieure a la decision, les trois cibles elles-memes.

Limites : experience synthetique, remise confondue avec l'identite produit
(assignation persistante par produit), aucune revendication causale, usage
academique et benchmark de pipeline uniquement.
