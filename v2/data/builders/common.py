"""Utilitaires partagés par les builders de datasets futurs.

Aucun de ces builders ne tourne sur les données actuelles : ils sont écrits et
testés à l'avance, sur fixtures synthétiques uniquement.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

# Statuts retirés par défaut de tout dataset d'apprentissage.
STATUTS_EXCLUS_PAR_DEFAUT: tuple[str, ...] = ("annulee", "retournee")


class ColonnesManquantes(ValueError):
    """Une colonne indispensable est absente.

    Levée volontairement plutôt que compensée : un builder qui se replie
    silencieusement sur une heuristique produit un dataset dont personne ne
    sait plus s'il repose sur des données ou sur des suppositions.
    """


def exiger_colonnes(df: pd.DataFrame, colonnes: Sequence[str], contexte: str) -> None:
    manquantes = [c for c in colonnes if c not in df.columns]
    if manquantes:
        raise ColonnesManquantes(
            f"{contexte} : colonne(s) absente(s) {manquantes}. "
            "Ce dataset ne peut pas être construit sans elles, et aucune valeur de "
            "remplacement n'est inventée."
        )


def masque_lignes_valides(
    ventes: pd.DataFrame,
    statuts_exclus: tuple[str, ...] = STATUTS_EXCLUS_PAR_DEFAUT,
    exclure_retours: bool = True,
) -> pd.Series:
    """Lignes retenues après exclusion des annulations et des retours.

    Si les colonnes de statut sont absentes, **aucune exclusion n'est appliquée**
    et toutes les lignes sont conservées. C'est un choix assumé : inventer un
    statut serait pire que de documenter qu'on ne sait pas.
    """
    garde = pd.Series(True, index=ventes.index)
    if "statut_commande" in ventes.columns:
        garde &= ~ventes["statut_commande"].isin(statuts_exclus)
    if "is_annulee" in ventes.columns:
        garde &= ~ventes["is_annulee"].fillna(False).astype(bool)
    if exclure_retours and "is_retour" in ventes.columns:
        garde &= ~ventes["is_retour"].fillna(False).astype(bool)
    return garde


def exclure_bots_et_tests(web: pd.DataFrame) -> pd.DataFrame:
    """Retire le trafic robotique et interne.

    Si les indicateurs manquent, la fonction lève : contrairement aux statuts de
    commande, on ne peut pas construire un dataset de recommandation en
    ignorant la question du trafic non humain — les popularités et les taux de
    conversion en dépendent directement.
    """
    # La livraison finale expose `est_bot` et ne contient pas d'indicateur de
    # trafic interne. On accepte l'ancien alias uniquement pour compatibilité.
    bot_col = "est_bot" if "est_bot" in web.columns else "is_bot"
    exiger_colonnes(web, (bot_col,), contexte="exclusion bots")
    garde = ~web[bot_col].fillna(False).astype(bool)
    if "is_test_interne" in web.columns:
        garde &= ~web["is_test_interne"].fillna(False).astype(bool)
    return web[garde].copy()


def normaliser_timestamps(serie: pd.Series, colonne: str) -> pd.Series:
    """Convertit en UTC en exigeant un fuseau explicite.

    Un horodatage naïf est refusé : le supposer UTC ou local décalerait les
    journées et fausserait silencieusement toutes les fenêtres temporelles.
    """
    ts = pd.to_datetime(serie, errors="coerce", utc=False)
    # ``is_datetime64tz_dtype`` est déprécié dans pandas ; l'instance explicite
    # conserve le même contrôle sans dépendre d'une API retirée.
    if isinstance(ts.dtype, pd.DatetimeTZDtype):
        return ts.dt.tz_convert("UTC")
    raise ValueError(
        f"{colonne} : horodatages sans fuseau. Le fuseau de référence doit être fourni "
        "par le Data Engineer, il ne sera pas supposé."
    )
