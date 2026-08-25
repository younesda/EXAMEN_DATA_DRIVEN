# Ranking pilote — prochain achat

Les candidats proviennent des générateurs audités ; les cibles de prochaine commande restent strictement futures.

|   window | model                |   recall_at10 |   ndcg_at10 |   coverage |   n_clients |
|---------:|:---------------------|--------------:|------------:|-----------:|------------:|
|        1 | popularite_globale   |        0.1471 |      0.0723 |     1.0000 |        1538 |
|        1 | heuristique_rrf      |        0.1284 |      0.0652 |     1.0000 |        1538 |
|        1 | LightGBM_LambdaRank  |        0.1039 |      0.0515 |     1.0000 |        1538 |
|        1 | logistique_pointwise |        0.0762 |      0.0366 |     1.0000 |        1538 |
|        2 | popularite_globale   |        0.1139 |      0.0555 |     1.0000 |        2228 |
|        2 | heuristique_rrf      |        0.1139 |      0.0553 |     1.0000 |        2228 |
|        2 | LightGBM_LambdaRank  |        0.0725 |      0.0350 |     1.0000 |        2228 |
|        2 | logistique_pointwise |        0.0732 |      0.0330 |     1.0000 |        2228 |

| model                |   recall_at10 |   ndcg_at10 |   coverage |   windows |
|:---------------------|--------------:|------------:|-----------:|----------:|
| LightGBM_LambdaRank  |        0.0882 |      0.0432 |     1.0000 |         2 |
| heuristique_rrf      |        0.1212 |      0.0602 |     1.0000 |         2 |
| logistique_pointwise |        0.0747 |      0.0348 |     1.0000 |         2 |
| popularite_globale   |        0.1305 |      0.0639 |     1.0000 |         2 |

Gate pilote : {'pilot_windows': [1, 2], 'ndcg_gain_ge_5pct': False, 'recall_loss_le_2pct': False, 'coverage_ge_15pct': True, 'four_window_continued': False}

Aucune poursuite vers quatre fenêtres ni bootstrap n'est exécutée si le gate échoue. Popularité globale reste officielle tant qu'un IC95 % bootstrap favorable n'est pas obtenu.