# Complément panier — validation F2–F4

F1 est `non_evaluable_no_history`: 0 commande d’entraînement, 0 produit connu, 100 % cold-start. Aucune métrique comportementale n’est revendiquée ; un fallback catalogue non comportemental ou métier est requis.

Le gate candidat est franchi sur les trois fenêtres évaluables : Recall candidat@50 = 0,8676 (F2), 0,8895 (F3), 0,9332 (F4). L’union ordonnée est donc publiée comme `candidate_union_rrf` et reste la seule baseline candidate end-to-end comparable sur F2–F4.

Le ranker LightGBM LambdaRank n’est pas promu : aucun résultat end-to-end suffisamment vérifiable n’est ajouté au périmètre officiel. Aucun gain, couverture ou intervalle bootstrap ne doit être inféré de F1.
