"""Registre de disponibilite des features pricing.

Regle unique
------------
La cible est `quantite` confirmee pour un produit `p`, un jour `D` et une
remise `r`. Une feature n'est autorisee que si sa valeur est **entierement
determinee avant `D 00:00`**, heure locale `Africa/Dakar`.

Trois familles sont autorisees :

* `statique`        - attribut de catalogue fige (prix, cout, categorie) ;
* `planifie`        - decide a l'avance et inscrit au calendrier (remise du
                      jour cible, campagne active) ; c'est la meme hypothese
                      de calendrier promotionnel gele que le forecasting ;
* `historique`      - agregat construit exclusivement sur des jours `< D`.

Est interdite toute variable mesuree **pendant** `D` : elle n'existe qu'une
fois la journee de ventes terminee. `n_lignes` en est le cas le plus grave :
la cible `quantite` est la somme des quantites de ces memes lignes.

Ce module est la source de verite ; `validate_matrix` doit etre appelee sur
toute matrice d'entrainement ou d'inference.
"""
from __future__ import annotations

from dataclasses import dataclass

SEGMENTS = ("nouveau", "occasionnel", "regulier", "vip")
HISTORY_PREFIXES = ("sales", "views", "carts", "orders", "clients", "basket")


@dataclass(frozen=True)
class FeatureRule:
    feature: str
    availability: str
    allowed: bool
    family: str
    justification: str


def _history(name: str, source: str) -> FeatureRule:
    return FeatureRule(
        feature=name, availability="D-1 23:59", allowed=True, family="historique",
        justification="agregat de " + source + " construit sur shift(1) puis rolling : "
                      "aucune valeur du jour D n'entre dans le calcul")


_RULES: list[FeatureRule] = [
    # ---------------------------------------------------------------- cible
    FeatureRule("quantite", "D 23:59", False, "cible",
                "cible du modele : quantite confirmee du produit-jour-remise"),
    # ------------------------------------------- interdites : contemporaines
    FeatureRule("n_lignes", "D 23:59", False, "contemporaine",
                "nombre de lignes de commande confirmees du jour D ; la cible "
                "quantite est la somme des quantites de ces lignes "
                "(correlation 0,708, ratio quantite/n_lignes borne a [1, 5]). "
                "Composant direct de la cible."),
    FeatureRule("ca_xof", "D 23:59", False, "contemporaine",
                "chiffre d'affaires realise le jour D ; ca_xof = prix_paye x quantite"),
    FeatureRule("marge_xof", "D 23:59", False, "contemporaine",
                "marge realisee le jour D ; fonction affine de la cible"),
    FeatureRule("prix_unitaire_paye_xof", "D 23:59", False, "contemporaine",
                "prix unitaire moyen effectivement paye ; connu apres les ventes du jour D"),
    FeatureRule("quantite_vendue", "D 23:59", False, "contemporaine",
                "quantite du jour D issue de fact_stock, tous statuts confondus"),
    FeatureRule("order_count", "D 23:59", False, "contemporaine",
                "nombre de commandes du jour D ; seules ses versions retardees "
                "orders_lag_* / orders_mean_* sont autorisees"),
    FeatureRule("distinct_clients", "D 23:59", False, "contemporaine",
                "nombre de clients distincts du jour D ; seules clients_lag_* / "
                "clients_mean_* sont autorisees"),
    FeatureRule("avg_basket_quantity", "D 23:59", False, "contemporaine",
                "panier moyen du jour D ; seules basket_lag_* / basket_mean_* sont autorisees"),
    FeatureRule("y", "D 23:59", False, "contemporaine",
                "quantite journaliere du jour D dans la table forecasting"),
    FeatureRule("niveau_stock", "D 23:59", False, "contemporaine",
                "stock de FIN de journee D ; seul stock_at_cutoff = shift(1) est autorise"),
    # -------------------------------------------------------------- statique
    FeatureRule("prix_base_xof", "statique", True, "statique",
                "prix catalogue fige par produit ; aucune variation intra-produit constatee"),
    FeatureRule("cout_xof", "statique", True, "statique",
                "cout unitaire fige dans dim_produit, constant sur toute la periode"),
    FeatureRule("product_code", "statique", True, "statique",
                "identifiant produit encode, attribut de catalogue immuable"),
    FeatureRule("category_code", "statique", True, "statique",
                "identifiant categorie encode, attribut de catalogue immuable"),
    FeatureRule("brand_code", "statique", True, "statique",
                "identifiant marque encode, attribut de catalogue immuable"),
    # -------------------------------------------------------------- planifie
    FeatureRule("remise_pct", "D-1 23:59", True, "planifie",
                "variable de decision : la remise du jour D est fixee par le calendrier "
                "promotionnel (dim_promotion.date_debut/date_fin) avant D"),
    FeatureRule("planned_paid_price_xof", "D-1 23:59", True, "planifie",
                "prix_base x (1 - remise/100) : fonction de deux variables connues avant D"),
    FeatureRule("unit_margin_before_xof", "statique", True, "statique",
                "prix_base_xof - cout_xof : difference de deux constantes de catalogue"),
    FeatureRule("unit_margin_after_xof", "D-1 23:59", True, "planifie",
                "prix planifie apres remise moins le cout unitaire de catalogue"),
    FeatureRule("margin_rate_after", "D-1 23:59", True, "planifie",
                "taux de marge unitaire calcule sur le prix planifie avant la journee D"),
    FeatureRule("discount_x_category", "D-1 23:59", True, "planifie",
                "interaction entre la remise planifiee et la categorie du produit"),
    FeatureRule("discount_x_product", "D-1 23:59", True, "planifie",
                "interaction entre la remise planifiee et l'identifiant du produit"),
    FeatureRule("product_campaign_active", "D-1 23:59", True, "planifie",
                "campagne produit active en D, connue par les dates de dim_promotion"),
    FeatureRule("category_campaign_active", "D-1 23:59", True, "planifie",
                "campagne categorie active en D, connue par les dates de dim_promotion"),
    FeatureRule("category_concurrent_promotions", "D-1 23:59", True, "planifie",
                "nombre de campagnes concurrentes sur la categorie en D, issu du calendrier"),
    # -------------------------------------------------------------- calendaire
    FeatureRule("dow", "deterministe", True, "planifie",
                "jour de la semaine de D, entierement determine par le calendrier"),
    FeatureRule("week", "deterministe", True, "planifie",
                "semaine ISO de D, entierement determinee par le calendrier"),
    FeatureRule("month", "deterministe", True, "planifie",
                "mois de D, entierement determine par le calendrier"),
    FeatureRule("weekend", "deterministe", True, "planifie",
                "indicateur week-end de D, entierement determine par le calendrier"),
    # ------------------------------------------------------------ historique
    FeatureRule("stock_at_cutoff", "D-1 23:59", True, "historique",
                "niveau_stock.shift(1) : stock de fin de journee D-1, connu avant D"),
    FeatureRule("restock_frequency_84", "D-1 23:59", True, "historique",
                "frequence de reapprovisionnement sur shift(1) puis rolling 84"),
    FeatureRule("sales_zero_rate_28", "D-1 23:59", True, "historique",
                "taux de jours sans vente sur shift(1) puis rolling 28"),
    FeatureRule("historical_view_to_cart_28", "D-1 23:59", True, "historique",
                "ratio paniers/vues sur shift(1) puis rolling 28"),
    FeatureRule("past_campaign_exposure_90", "D-1 23:59", True, "historique",
                "exposition promotionnelle passee sur shift(1) puis rolling 90"),
    FeatureRule("product_mean_before", "D-1 23:59", True, "historique",
                "moyenne expansive de quantite, cumsum - valeur du jour D : strictement anterieure"),
    FeatureRule("product_n_before", "D-1 23:59", True, "historique",
                "compte expansif d'observations, strictement anterieur a D"),
    FeatureRule("product_discount_mean_before", "D-1 23:59", True, "historique",
                "moyenne expansive par produit x remise, strictement anterieure a D"),
    FeatureRule("product_discount_n_before", "D-1 23:59", True, "historique",
                "compte expansif par produit x remise, strictement anterieur a D"),
    FeatureRule("category_discount_mean_before", "D-1 23:59", True, "historique",
                "moyenne expansive par categorie x remise, strictement anterieure a D"),
    FeatureRule("category_discount_n_before", "D-1 23:59", True, "historique",
                "compte expansif par categorie x remise, strictement anterieur a D"),
]
_RULES += [FeatureRule("segment_share_" + name + "_90", "D-1 23:59", True, "historique",
                       "part du segment " + name + " sur shift(1) puis rolling 90")
           for name in SEGMENTS]
for _prefix, _source in (("sales", "ventes confirmees"), ("views", "vues web"),
                         ("carts", "ajouts panier"), ("orders", "commandes confirmees"),
                         ("clients", "clients distincts"), ("basket", "quantite moyenne par panier")):
    _RULES += [_history(_prefix + "_lag_" + str(lag), _source) for lag in (1, 7, 28)]
    _RULES += [_history(_prefix + "_mean_" + str(window), _source) for window in (7, 28, 84)]

REGISTRY: dict[str, FeatureRule] = {rule.feature: rule for rule in _RULES}
IDENTIFIERS = frozenset({"produit_key", "ds", "categorie", "marque", "row_id", "remise_pct"})

#: Variables interdites, y compris comme composant d'une transformation.
FORBIDDEN: frozenset[str] = frozenset(
    rule.feature for rule in _RULES if not rule.allowed)

#: Racines interdites : toute colonne les contenant est refusee, ce qui bloque
#: les transformations indirectes du type ``log_n_lignes`` ou ``n_lignes_ratio``.
FORBIDDEN_ROOTS: tuple[str, ...] = (
    "n_lignes", "ca_xof", "marge_xof", "prix_unitaire_paye", "quantite_vendue",
    "order_count", "distinct_clients", "avg_basket_quantity",
)


def allowed_features() -> list[str]:
    """Liste ordonnee et figee des features autorisees."""
    return [rule.feature for rule in _RULES if rule.allowed]


def validate_matrix(columns) -> None:
    """Refuse toute colonne interdite ou inconnue du registre.

    Appelee sur la matrice d'entrainement ET sur la matrice d'inference : une
    feature autorisee a l'apprentissage mais indisponible en production serait
    une fuite operationnelle.
    """
    names = list(columns)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError("Colonnes dupliquees dans la matrice : " + str(duplicates))
    forbidden = sorted(name for name in names
                       if name in FORBIDDEN
                       or any(root in name for root in FORBIDDEN_ROOTS))
    if forbidden:
        raise ValueError(
            "Features contemporaines de la cible detectees : " + str(forbidden)
            + ". Chaque feature doit etre disponible avant le debut du produit-jour predit.")
    unknown = sorted(name for name in names
                     if name not in REGISTRY and name not in IDENTIFIERS)
    if unknown:
        raise ValueError(
            "Features absentes du registre : " + str(unknown)
            + ". Ajouter une FeatureRule explicite (disponibilite + justification) "
              "avant tout usage.")


def to_records() -> list[dict]:
    """Registre serialisable pour les rapports et les metadonnees."""
    return [{"feature": rule.feature, "disponible_a": rule.availability,
             "autorisee": rule.allowed, "famille": rule.family,
             "justification": rule.justification} for rule in _RULES]


def to_markdown() -> str:
    lines = ["| Feature | Disponible à | Statut | Famille | Justification |",
             "|---|---|---|---|---|"]
    for rule in _RULES:
        status = "autorisée" if rule.allowed else "**interdite**"
        lines.append("| `" + rule.feature + "` | " + rule.availability + " | " + status
                     + " | " + rule.family + " | " + rule.justification + " |")
    return "\n".join(lines)
