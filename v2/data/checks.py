"""Contrôles de qualité de la livraison — fonctions pures.

Chaque fonction prend des DataFrames et retourne un ``CheckResult``. Aucune
n'ouvre de connexion : elles sont donc testables sur des fixtures synthétiques,
et le même code exact tourne sur la livraison réelle.

Convention de sévérité :

* ``erreur``          — fait échouer la validation ;
* ``avertissement``   — signalé, ne fait pas échouer ;
* ``information``     — mesure sans jugement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SEVERITE_ERREUR = "erreur"
SEVERITE_AVERTISSEMENT = "avertissement"
SEVERITE_INFO = "information"


@dataclass
class CheckResult:
    nom: str
    ok: bool
    severite: str
    message: str
    details: dict = field(default_factory=dict)

    @property
    def bloquant(self) -> bool:
        return (not self.ok) and self.severite == SEVERITE_ERREUR

    def as_dict(self) -> dict:
        return {"controle": self.nom, "ok": self.ok, "severite": self.severite,
                "message": self.message, "details": self.details}


# --------------------------------------------------------------------------- #
# Expurgation des secrets
# --------------------------------------------------------------------------- #
_MOTIFS_SECRETS = [
    # Chaînes de connexion : on garde le schéma, on masque tout le reste.
    (re.compile(r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s\"']+"), r"\1://***MASQUE***"),
    # Paires clé=valeur sensibles, quel que soit le séparateur.
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|anon[_-]?key|"
                r"service[_-]?role|authorization|bearer)\b\s*[:=]\s*[^\s,;\"']+"), r"\1=***MASQUE***"),
    (re.compile(r"(?i)\b(host|hostname|user|username|dbname|database)\b\s*[:=]\s*[^\s,;\"']+"),
     r"\1=***MASQUE***"),
    # JWT.
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), "***JWT_MASQUE***"),
    # Hôtes Supabase.
    (re.compile(r"(?i)\b[a-z0-9-]+\.(supabase\.(?:co|com|net)|pooler\.supabase\.com)\b"), "***HOTE_MASQUE***"),
]


def expurger(texte: str) -> str:
    """Retire toute trace de secret d'un texte destiné au rapport.

    Appliquée systématiquement, y compris aux messages d'exception : une
    erreur de connexion contient typiquement l'URL complète avec identifiants.
    """
    out = str(texte)
    for motif, remplacement in _MOTIFS_SECRETS:
        out = motif.sub(remplacement, out)
    return out


# --------------------------------------------------------------------------- #
# Présence et couverture
# --------------------------------------------------------------------------- #
def check_champs_obligatoires(
    colonnes_par_table: dict[str, list[str]], obligatoires: list[tuple[str, str]],
    comportements: dict[tuple[str, str], str] | None = None,
) -> CheckResult:
    comportements = comportements or {}
    manquants = [
        {"table": t, "colonne": c, "si_absent": comportements.get((t, c), "non documenté")}
        for t, c in obligatoires
        if c not in set(colonnes_par_table.get(t, []))
    ]
    return CheckResult(
        "champs_obligatoires", not manquants, SEVERITE_ERREUR,
        "Tous les champs obligatoires sont présents." if not manquants
        else f"{len(manquants)} champ(s) obligatoire(s) manquant(s) — validation en échec.",
        {"manquants": manquants},
    )


def check_couverture(
    df: pd.DataFrame, table: str, colonne: str, min_non_null: float,
    portee_mask: pd.Series | None = None, portee: str = "toutes les lignes",
) -> CheckResult:
    nom = f"couverture::{table}.{colonne}"
    if colonne not in df.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Colonne absente : impossible de mesurer sa couverture.",
                           {"table": table, "colonne": colonne})

    sub = df if portee_mask is None else df[portee_mask]
    if len(sub) == 0:
        # Aucune ligne dans le périmètre : non évaluable. Conformément à la règle
        # appliquée depuis la V2, un contrôle non évaluable ne passe pas.
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           "Aucune ligne dans le périmètre : couverture non évaluable "
                           "(un contrôle non évaluable compte comme échoué).",
                           {"table": table, "colonne": colonne, "portee": portee, "n": 0})

    taux = float(sub[colonne].notna().mean())
    ok = taux >= min_non_null
    return CheckResult(
        nom, ok, SEVERITE_ERREUR,
        f"Couverture {taux:.4f} pour un minimum exigé de {min_non_null:.4f} ({portee}).",
        {"table": table, "colonne": colonne, "taux_non_null": taux,
         "min_exige": min_non_null, "n_lignes_perimetre": int(len(sub)), "portee": portee},
    )


def check_couverture_historique(
    dates: pd.Series, debut_actuel: str, fin_actuel: str, part_minimale: float
) -> CheckResult:
    """Part de la période actuellement couverte que la livraison couvre encore."""
    d = pd.to_datetime(dates, errors="coerce", utc=True).dropna()
    if d.empty:
        return CheckResult("couverture_historique", False, SEVERITE_ERREUR,
                           "Aucune date exploitable : couverture historique non évaluable.", {})

    debut, fin = pd.Timestamp(debut_actuel, tz="UTC"), pd.Timestamp(fin_actuel, tz="UTC")
    jours_attendus = (fin - debut).days + 1
    dans_periode = d[(d >= debut) & (d <= fin)]
    jours_couverts = dans_periode.dt.normalize().nunique()
    part = jours_couverts / jours_attendus if jours_attendus > 0 else 0.0

    return CheckResult(
        "couverture_historique", part >= part_minimale, SEVERITE_ERREUR,
        f"{jours_couverts}/{jours_attendus} jours de la période actuelle couverts "
        f"({part:.2%}, minimum {part_minimale:.0%}).",
        {"jours_couverts": int(jours_couverts), "jours_attendus": int(jours_attendus),
         "part": float(part), "part_minimale": part_minimale,
         "date_min_livraison": str(d.min()), "date_max_livraison": str(d.max())},
    )


# --------------------------------------------------------------------------- #
# Intégrité : unicité, clés étrangères
# --------------------------------------------------------------------------- #
def check_unicite(df: pd.DataFrame, table: str, colonnes: list[str]) -> CheckResult:
    nom = f"unicite::{table}({','.join(colonnes)})"
    absentes = [c for c in colonnes if c not in df.columns]
    if absentes:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Colonnes absentes : {absentes}.", {"colonnes_absentes": absentes})

    dupes = df.duplicated(subset=colonnes, keep=False)
    n = int(dupes.sum())
    exemples = (df.loc[dupes, colonnes].drop_duplicates().head(10).to_dict(orient="records")
                if n else [])
    return CheckResult(
        nom, n == 0, SEVERITE_ERREUR,
        "Unicité respectée." if n == 0 else f"{n} ligne(s) en doublon sur {colonnes}.",
        {"n_lignes_dupliquees": n, "exemples_cles": exemples},
    )


def check_cle_etrangere(
    source: pd.DataFrame, colonne_source: str, cible: pd.DataFrame, colonne_cible: str,
    nom: str | None = None,
) -> CheckResult:
    nom = nom or f"fk::{colonne_source}->{colonne_cible}"
    if colonne_source not in source.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Colonne source absente : {colonne_source}.", {})
    if colonne_cible not in cible.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Colonne cible absente : {colonne_cible}.", {})

    # Les valeurs nulles ne sont pas des orphelines : c'est l'affaire du
    # contrôle de couverture, pas de celui d'intégrité référentielle.
    valeurs = source[colonne_source].dropna()
    connues = set(cible[colonne_cible].dropna())
    orphelines = valeurs[~valeurs.isin(connues)]
    n = int(len(orphelines))
    return CheckResult(
        nom, n == 0, SEVERITE_ERREUR,
        "Aucune clé orpheline." if n == 0
        else f"{n} valeur(s) orpheline(s) sur {len(valeurs)} non nulles.",
        {"n_orphelines": n, "n_non_nulles": int(len(valeurs)),
         "exemples": sorted(map(str, orphelines.unique()[:10]))},
    )


# --------------------------------------------------------------------------- #
# Horodatages
# --------------------------------------------------------------------------- #
def check_timestamps_avec_fuseau(df: pd.DataFrame, colonne: str) -> CheckResult:
    nom = f"timestamp_fuseau::{colonne}"
    if colonne not in df.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR, f"Colonne absente : {colonne}.", {})

    serie = df[colonne]
    if pd.api.types.is_datetime64tz_dtype(serie):
        return CheckResult(nom, True, SEVERITE_ERREUR,
                           f"Horodatages porteurs d'un fuseau ({serie.dt.tz}).",
                           {"fuseau": str(serie.dt.tz)})

    if pd.api.types.is_datetime64_any_dtype(serie):
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           "Horodatages NAÏFS, sans fuseau. Toute conversion décalerait les "
                           "journées et fausserait les fenêtres temporelles. Le fuseau de "
                           "référence doit être fourni, jamais supposé.", {"dtype": str(serie.dtype)})

    # Colonne texte : on regarde si le fuseau est présent dans la chaîne.
    echantillon = serie.dropna().astype(str).head(1000)
    motif_tz = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")
    sans_tz = int((~echantillon.str.contains(motif_tz)).sum())
    return CheckResult(
        nom, sans_tz == 0, SEVERITE_ERREUR,
        "Fuseau présent dans toutes les chaînes examinées." if sans_tz == 0
        else f"{sans_tz} valeur(s) sur {len(echantillon)} examinées sans fuseau explicite.",
        {"n_examinees": int(len(echantillon)), "n_sans_fuseau": sans_tz},
    )


def check_evenements_futurs(
    df: pd.DataFrame, colonne: str, reference: datetime | None = None
) -> CheckResult:
    nom = f"evenements_futurs::{colonne}"
    if colonne not in df.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR, f"Colonne absente : {colonne}.", {})

    ref = reference or datetime.now(timezone.utc)
    ts = pd.to_datetime(df[colonne], errors="coerce", utc=True)
    futurs = int((ts > pd.Timestamp(ref)).sum())
    return CheckResult(
        nom, futurs == 0, SEVERITE_ERREUR,
        "Aucun événement postérieur à la date de référence." if futurs == 0
        else f"{futurs} événement(s) dans le futur — anomalie d'horodatage ou de fuseau.",
        {"n_futurs": futurs, "reference": str(ref), "max_observe": str(ts.max())},
    )


def check_ordre_dans_session(
    df: pd.DataFrame, session_col: str, ts_col: str, ordre_col: str
) -> CheckResult:
    """Événements désordonnés : l'ordre des identifiants contredit celui du temps.

    Sévérité `avertissement` : un `event_id` non séquentiel est une convention
    légitime. Ce contrôle mesure un fait, il ne prononce pas un défaut.
    """
    nom = "evenements_desordonnes"
    manquantes = [c for c in (session_col, ts_col, ordre_col) if c not in df.columns]
    if manquantes:
        return CheckResult(nom, False, SEVERITE_AVERTISSEMENT,
                           f"Colonnes absentes : {manquantes}.", {"colonnes_absentes": manquantes})

    d = df[[session_col, ts_col, ordre_col]].copy()
    d[ts_col] = pd.to_datetime(d[ts_col], errors="coerce", utc=True)
    d = d.dropna().sort_values([session_col, ordre_col])
    d["_delta"] = d.groupby(session_col)[ts_col].diff()
    n_desordre = int((d["_delta"] < pd.Timedelta(0)).sum())
    sessions = d.loc[d["_delta"] < pd.Timedelta(0), session_col].unique()
    return CheckResult(
        nom, n_desordre == 0, SEVERITE_AVERTISSEMENT,
        "Ordre temporel cohérent avec l'ordre des identifiants." if n_desordre == 0
        else f"{n_desordre} transition(s) à rebours dans {len(sessions)} session(s).",
        {"n_transitions_a_rebours": n_desordre, "n_sessions_concernees": int(len(sessions)),
         "exemples_sessions": sorted(map(str, sessions[:10]))},
    )


# --------------------------------------------------------------------------- #
# Cohérence métier
# --------------------------------------------------------------------------- #
def check_bots_et_tests(df: pd.DataFrame, col_bot: str, col_test: str) -> CheckResult:
    nom = "bots_et_tests"
    manquantes = [c for c in (col_bot, col_test) if c not in df.columns]
    if manquantes:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Indicateur(s) absent(s) : {manquantes}. Sans eux, aucune métrique de "
                           "recommandation n'est fiable, et aucune règle de détection maison ne "
                           "sera inventée.", {"colonnes_absentes": manquantes})

    n = len(df)
    n_bot = int(df[col_bot].fillna(False).astype(bool).sum())
    n_test = int(df[col_test].fillna(False).astype(bool).sum())
    part_exclue = (n_bot + n_test) / n if n else 0.0

    # Un taux strictement nul est possible mais suffisamment inhabituel pour
    # mériter une confirmation explicite plutôt qu'une acceptation silencieuse.
    suspect = n > 0 and n_bot == 0
    return CheckResult(
        nom, not suspect, SEVERITE_AVERTISSEMENT,
        f"{n_bot} bot(s) et {n_test} événement(s) de test sur {n} lignes "
        f"({part_exclue:.2%} à exclure)."
        + (" Taux de bots strictement nul : à confirmer avec le Data Engineer, "
           "un tel taux est inhabituel sur du trafic web réel." if suspect else ""),
        {"n_lignes": n, "n_bots": n_bot, "n_tests": n_test, "part_a_exclure": float(part_exclue),
         "taux_bot_nul_suspect": suspect},
    )


def check_achats_web_sans_commande(
    web: pd.DataFrame, col_type: str, col_order: str, valeur_achat: str = "purchase"
) -> CheckResult:
    nom = "achat_web_sans_commande"
    manquantes = [c for c in (col_type, col_order) if c not in web.columns]
    if manquantes:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Colonnes absentes : {manquantes}.", {"colonnes_absentes": manquantes})

    achats = web[web[col_type] == valeur_achat]
    if achats.empty:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Aucun événement '{valeur_achat}' : contrôle non évaluable "
                           "(compte comme échoué).", {"n_achats": 0})

    sans = int(achats[col_order].isna().sum())
    return CheckResult(
        nom, sans == 0, SEVERITE_ERREUR,
        "Tous les achats web portent un identifiant de commande." if sans == 0
        else f"{sans} achat(s) web sur {len(achats)} sans order_id — l'ambiguïté entre événement "
             "web et vente réelle, identifiée en V1, resterait entière.",
        {"n_achats": int(len(achats)), "n_sans_order_id": sans},
    )


def check_commandes_sans_ligne(
    web: pd.DataFrame, ventes: pd.DataFrame, col_order_web: str, col_order_ventes: str
) -> CheckResult:
    nom = "commande_sans_ligne"
    if col_order_web not in web.columns or col_order_ventes not in ventes.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           "Colonne order_id absente d'un des deux côtés.", {})

    refs = set(web[col_order_web].dropna())
    connues = set(ventes[col_order_ventes].dropna())
    orphelines = sorted(refs - connues)
    return CheckResult(
        nom, not orphelines, SEVERITE_ERREUR,
        "Toute commande référencée côté web a au moins une ligne de vente." if not orphelines
        else f"{len(orphelines)} commande(s) référencée(s) côté web sans aucune ligne dans fact_ventes.",
        {"n_orphelines": len(orphelines), "exemples": list(map(str, orphelines[:10]))},
    )


def check_order_id_mono_client(
    ventes: pd.DataFrame, col_order: str, col_client: str
) -> CheckResult:
    nom = "order_id_multi_client"
    manquantes = [c for c in (col_order, col_client) if c not in ventes.columns]
    if manquantes:
        return CheckResult(nom, False, SEVERITE_ERREUR,
                           f"Colonnes absentes : {manquantes}.", {"colonnes_absentes": manquantes})

    par_order = ventes.dropna(subset=[col_order]).groupby(col_order)[col_client].nunique()
    multi = par_order[par_order > 1]
    return CheckResult(
        nom, multi.empty, SEVERITE_ERREUR,
        "Chaque commande appartient à un seul client." if multi.empty
        else f"{len(multi)} commande(s) rattachée(s) à plusieurs clients — le grain commande "
             "n'est pas fiable.",
        {"n_commandes_multi_client": int(len(multi)),
         "exemples": list(map(str, multi.index[:10]))},
    )


def check_retours_coherents(
    ventes: pd.DataFrame, col_is_retour: str, col_date_retour: str, col_date_commande: str
) -> CheckResult:
    nom = "retours_et_annulations"
    presentes = [c for c in (col_is_retour, col_date_retour, col_date_commande) if c in ventes.columns]
    if col_is_retour not in ventes.columns:
        return CheckResult(nom, True, SEVERITE_AVERTISSEMENT,
                           "Aucun indicateur de retour : les retours ne sont pas distinguables. "
                           "Aucune correction n'est appliquée et le fait est documenté.",
                           {"colonnes_presentes": presentes})

    retours = ventes[ventes[col_is_retour].fillna(False).astype(bool)]
    details = {"n_retours": int(len(retours)), "colonnes_presentes": presentes}

    if col_date_retour not in ventes.columns or col_date_commande not in ventes.columns:
        return CheckResult(nom, True, SEVERITE_AVERTISSEMENT,
                           f"{len(retours)} retour(s) déclaré(s), mais non datables : ils ne "
                           "peuvent pas être utilisés dans une validation temporelle sans risque "
                           "de fuite.", details)

    dr = pd.to_datetime(retours[col_date_retour], errors="coerce", utc=True)
    dc = pd.to_datetime(retours[col_date_commande], errors="coerce", utc=True)
    anterieurs = int((dr < dc).sum())
    details["n_retours_anterieurs_a_la_commande"] = anterieurs
    return CheckResult(
        nom, anterieurs == 0, SEVERITE_ERREUR,
        f"{len(retours)} retour(s), tous postérieurs à leur commande." if anterieurs == 0
        else f"{anterieurs} retour(s) daté(s) avant leur propre commande.",
        details,
    )


def check_domaine_ferme(
    df: pd.DataFrame, colonne: str, valeurs_attendues: list[str]
) -> CheckResult:
    nom = f"domaine::{colonne}"
    if colonne not in df.columns:
        return CheckResult(nom, False, SEVERITE_ERREUR, f"Colonne absente : {colonne}.", {})

    observees = set(df[colonne].dropna().astype(str).unique())
    inconnues = sorted(observees - set(valeurs_attendues))
    return CheckResult(
        nom, not inconnues, SEVERITE_ERREUR,
        "Toutes les valeurs appartiennent au domaine déclaré." if not inconnues
        else f"{len(inconnues)} valeur(s) hors domaine : {inconnues[:10]}. Elles ne sont jamais "
             "rangées dans un « autre » implicite.",
        {"valeurs_attendues": valeurs_attendues, "valeurs_observees": sorted(observees),
         "valeurs_inconnues": inconnues},
    )


def resume(results: list[CheckResult]) -> dict:
    erreurs = [r for r in results if r.bloquant]
    avertissements = [r for r in results if not r.ok and r.severite == SEVERITE_AVERTISSEMENT]
    return {
        "n_controles": len(results),
        "n_erreurs": len(erreurs),
        "n_avertissements": len(avertissements),
        "validation_reussie": not erreurs,
        "controles_en_erreur": [r.nom for r in erreurs],
        "controles_en_avertissement": [r.nom for r in avertissements],
    }
