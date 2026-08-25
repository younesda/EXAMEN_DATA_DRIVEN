# 03 — Pricing final

**Méthode prédictive retenue : `panel_effets_fixes`.**

| model                    |     wape |        std |      bias |
|:-------------------------|---------:|-----------:|----------:|
| panel_effets_fixes       | 0.561381 | 0.0066927  | 0.0382604 |
| LightGBM_calibre         | 0.562544 | 0.022378   | 0.0334824 |
| hierarchique_categorie   | 0.562723 | 0.00554344 | 0.0332832 |
| GLM_Poisson              | 0.563072 | 0.00578726 | 0.0368272 |
| GLM_Tweedie              | 0.563288 | 0.00559501 | 0.0359466 |
| baseline_moyenne_produit | 0.5643   | 0.00866966 | 0.0416097 |
| descriptif_intra_produit | 0.566061 | 0.00805962 | 0.0372165 |

## Verdict métier

Le prix catalogue reste fixe pour les 300 produits. Il est interdit de présenter ce résultat comme un prix optimal continu ou un effet causal. Le livrable est un simulateur observationnel de promotions et marge.

Garde-fous : prix jamais sous coût, marge minimale 5%, remise limitée au support historique, validation humaine obligatoire, application automatique interdite.

Cible de la WAPE : `quantite` confirmée au grain produit × jour × remise; numérateur et dénominateur sont poolés sur toutes les lignes de chaque fenêtre.

LightGBM est ajusté avant le bloc de calibration; son facteur multiplicatif utilise uniquement les 60 jours précédant le test. Aucun test n’entre dans le fit ou la calibration.

## Métriques par fenêtre

| model                    |        1 |        2 |        3 |
|:-------------------------|---------:|---------:|---------:|
| GLM_Poisson              | 0.563332 | 0.568725 | 0.55716  |
| GLM_Tweedie              | 0.563481 | 0.568783 | 0.557598 |
| LightGBM_calibre         | 0.588125 | 0.552913 | 0.546593 |
| baseline_moyenne_produit | 0.570586 | 0.567905 | 0.55441  |
| descriptif_intra_produit | 0.57216  | 0.569099 | 0.556924 |
| hierarchique_categorie   | 0.562558 | 0.568347 | 0.557264 |
| panel_effets_fixes       | 0.562421 | 0.567493 | 0.554229 |

## Audit des portées promotionnelles

|          |   confirmed_rows |   target_mismatches |   date_mismatches | discounts                                 |
|:---------|-----------------:|--------------------:|------------------:|:------------------------------------------|
| category |            11584 |                   0 |                 0 | [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]       |
| product  |              384 |                   0 |                 0 | [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0] |

Commande : `python -m src.pipelines.final_pricing`.
