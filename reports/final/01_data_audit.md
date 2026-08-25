# 01 — Audit des données finales

## Verdict

**VALIDÉ — entraînements autorisés.**

Extraction fraîche, locale et strictement en lecture seule. Aucun cache ou résultat V1 n'a été réutilisé.

## Contrôles

| Contrôle | Résultat | Détail |
|---|---:|---|
| `volume::dim_client` | OK | 5,000/5,000 |
| `volume::dim_date` | OK | 546/546 |
| `volume::dim_produit` | OK | 300/300 |
| `volume::dim_promotion` | OK | 120/120 |
| `volume::fact_evenements_web` | OK | 657,392/657,392 |
| `volume::fact_stock` | OK | 117,763/117,763 |
| `volume::fact_ventes` | OK | 84,319/84,319 |
| `pk::ventes` | OK | uniques=84,319 |
| `pk::web` | OK | uniques=657,392 |
| `pk::stock` | OK | produit×jour |
| `statuts` | OK | {"confirmee": 80130, "annulee": 2531, "retournee": 1658} |
| `fk::ventes_produit` | OK | 0 orpheline |
| `fk::ventes_client` | OK | 0 orpheline |
| `fk::web_produit` | OK | 0 orpheline |
| `utc` | OK | datetime64[ns, UTC] |
| `bots` | OK | exclus=34,952 |
| `sessions_timeout_30` | OK | écart max=15.0 min |
| `purchase_order` | OK | 84,319 achats |
| `purchase_quantity` | OK | 100 % renseigné |
| `ventes_web` | OK | 49,872 commandes appariées |
| `order_mono_client` | OK | max=1 |
| `order_mono_date` | OK | max=1 |
| `order_mono_status` | OK | max=1 |
| `stock_formula` | OK | écarts=0 |
| `price_formula` | OK | 100 % à ±2,1 %; médiane=0.0100 |
| `catalog_price_fixed` | OK | aucune variation intra-produit |

## Datasets reconstruits

| Dataset | Lignes | SHA-256 |
|---|---:|---|
| `product_daily_forecasting` | 163,800 | `e46095fc0dc00dee05f3451bc6d2daed0ac9d6ec4994e39142f40bf0c24da6ef` |
| `product_day_discount_pricing` | 55,586 | `b336733bfd4c8db7c192c268ac6d303d0ffe37a1369655a5f4f09c8e51eaa1db` |
| `order_baskets` | 80,130 | `278183c3aeda82385ccaea09ea1a5025ec5c29c5c89dddbf50b56adc1b3a5a8d` |
| `session_sequences` | 622,440 | `4e89c148085b34fd671c9cfa6c1d59e73668f5b3840d61d58608245e8ce9054e` |
| `client_product_interactions` | 622,440 | `ba81136aca57b5e4f20d7bf840528d2e1763650bb739577a0f1d7979e55af740` |

## Limites documentées

- `quantite_vendue` du stock inclut tous les statuts; aucune réintégration d'annulation/retour n'est modélisée.
- Le prix catalogue est fixe par produit : le pricing ne peut être ni causal ni un optimum continu; il reste un simulateur de promotions/marge.
- La règle session est un timeout d'inactivité ≤30 minutes; la durée totale peut dépasser 30 minutes.
- Les visiteurs anonymes sont conservés sans création de client fictif.
