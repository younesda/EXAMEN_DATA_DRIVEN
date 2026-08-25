"""Validateur de livraison — LECTURE SEULE.

    python -m v2.data.validate_new_delivery

Compare la livraison reçue au contrat ``v2/config/expected_new_data_schema.yaml``
et produit un rapport. **Rien n'est écrit dans Supabase**, aucun DDL n'est émis,
aucune donnée réelle n'est modifiée. Le seul fichier produit est le rapport de
validation, sous ``v2/evaluation/``.

Code de sortie :

* ``0`` — validation réussie (des avertissements peuvent subsister) ;
* ``1`` — au moins une erreur : champ obligatoire absent, couverture
  insuffisante, ou rupture d'intégrité.

Options utiles :

* ``--tables t1,t2`` restreint l'inspection ;
* ``--limit N`` échantillonne (les contrôles d'unicité et de clés étrangères
  sont alors marqués comme partiels — un échantillon ne prouve pas l'unicité) ;
* ``--sortie chemin.json`` change la destination du rapport.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import pandas as pd

from src.config.settings import PROJECT_ROOT
from v2.data import checks
from v2.data.checks import CheckResult, expurger
from v2.data.contract import compare_schemas, changements_bloquants, load_contract

V2_EVAL = PROJECT_ROOT / "v2" / "evaluation"
RAPPORT_DEFAUT = V2_EVAL / "new_delivery_validation.json"

# Périmètre temporel actuel — sert de base à la couverture historique.
PERIODE_ACTUELLE = ("2025-02-01", "2026-07-31")

DOMAINES_ATTENDUS = {
    ("fact_evenements_web", "event_type"): ["view", "click", "add_to_cart", "purchase"],
    ("fact_ventes", "statut_commande"): ["confirmee", "annulee", "retournee", "en_attente"],
}


# --------------------------------------------------------------------------- #
# Lecture du schéma livré
# --------------------------------------------------------------------------- #
def inventorier_schema(source, tables: list[str]) -> dict:
    """Inventaire du schéma livré, dans la forme attendue par `compare_schemas`."""
    inventaire = {}
    for table in tables:
        cols = source.describe_columns(table)
        colonnes = {}
        for r in cols.itertuples():
            nullable = getattr(r, "is_nullable", None)
            if isinstance(nullable, str):
                nullable = nullable.strip().upper() == "YES"
            colonnes[getattr(r, "column_name")] = {
                "type": getattr(r, "data_type", None),
                "nullable": bool(nullable) if nullable is not None else None,
            }
        inventaire[table] = {
            "colonnes": colonnes,
            "lignes": int(source.count_rows(table)),
            # Ni la clé primaire ni le grain ne sont devinés : ils sont laissés
            # à None, ce qui neutralise leur comparaison plutôt que de produire
            # un faux « changement de clé ». Le formulaire de décision (rapport 15)
            # les fait confirmer par le Data Engineer.
            "cle_primaire": None,
            "grain": None,
        }
    return inventaire


def _schema_actuel_pour_comparaison(contrat) -> dict:
    return {
        t: {"colonnes": d.get("colonnes", {}), "cle_primaire": None, "grain": None}
        for t, d in contrat.schema_actuel.items()
    }


# --------------------------------------------------------------------------- #
# Batterie de contrôles
# --------------------------------------------------------------------------- #
def executer_controles(
    donnees: dict[str, pd.DataFrame], contrat, reference_temporelle=None, partiel: bool = False
) -> list[CheckResult]:
    """Exécute tous les contrôles applicables aux tables effectivement chargées.

    Un contrôle dont les colonnes manquent n'est pas silencieusement sauté : il
    retourne un échec explicite, conformément à la règle « un contrôle non
    évaluable compte comme échoué ».
    """
    resultats: list[CheckResult] = []
    web = donnees.get("fact_evenements_web")
    ventes = donnees.get("fact_ventes")

    # --- 1. Champs obligatoires ---
    colonnes_par_table = {t: list(df.columns) for t, df in donnees.items()}
    obligatoires = [
        (t, c) for t, c in contrat.champs_obligatoires() if t in colonnes_par_table
    ]
    comportements = {(t, c): contrat.comportement_si_absent(t, c) for t, c in obligatoires}
    resultats.append(checks.check_champs_obligatoires(colonnes_par_table, obligatoires, comportements))

    # --- 2. Couverture des champs ---
    for cle, regle in contrat.seuils_couverture.items():
        if cle == "couverture_historique_minimale" or "." not in cle:
            continue
        table, colonne = cle.split(".", 1)
        df = donnees.get(table)
        if df is None:
            continue
        portee = regle.get("portee", "toutes les lignes")
        masque = None
        if "purchase" in portee and "event_type" in df.columns:
            masque = df["event_type"] == "purchase"
        elif "client_key nul" in portee and "client_key" in df.columns:
            masque = df["client_key"].isna()
        resultats.append(
            checks.check_couverture(df, table, colonne, float(regle["min_non_null"]), masque, portee)
        )

    # --- 3. Couverture historique ---
    seuil_hist = contrat.seuils_couverture.get("couverture_historique_minimale", {})
    if web is not None and "event_timestamp" in web.columns:
        resultats.append(checks.check_couverture_historique(
            web["event_timestamp"], *PERIODE_ACTUELLE,
            float(seuil_hist.get("part_periode_actuelle_couverte", 0.90)),
        ))

    # --- 4. Unicité ---
    for regle in contrat.controles_integrite.get("unicite", []):
        df = donnees.get(regle["table"])
        if df is None:
            continue
        r = checks.check_unicite(df, regle["table"], regle["colonnes"])
        if partiel:
            r.details["avertissement_echantillon"] = (
                "Contrôle exécuté sur un échantillon : l'absence de doublon n'y prouve pas "
                "l'unicité sur la table entière."
            )
        resultats.append(r)

    # --- 5. Clés étrangères ---
    for regle in contrat.controles_integrite.get("cles_etrangeres", []):
        t_src, c_src = regle["source"].split(".", 1)
        t_cib, c_cib = regle["cible"].split(".", 1)
        src, cib = donnees.get(t_src), donnees.get(t_cib)
        if src is None or cib is None:
            continue
        resultats.append(checks.check_cle_etrangere(
            src, c_src, cib, c_cib, nom=f"fk::{regle['source']}->{regle['cible']}"
        ))

    # --- 6. Horodatages ---
    if web is not None:
        resultats.append(checks.check_timestamps_avec_fuseau(web, "event_timestamp"))
        resultats.append(checks.check_evenements_futurs(web, "event_timestamp", reference_temporelle))
        resultats.append(checks.check_ordre_dans_session(web, "session_id", "event_timestamp", "event_id"))
        resultats.append(checks.check_bots_et_tests(web, "is_bot", "is_test_interne"))
        resultats.append(checks.check_achats_web_sans_commande(web, "event_type", "order_id"))

    # --- 7. Cohérence commandes ---
    if web is not None and ventes is not None:
        resultats.append(checks.check_commandes_sans_ligne(web, ventes, "order_id", "order_id"))
    if ventes is not None:
        resultats.append(checks.check_order_id_mono_client(ventes, "order_id", "client_key"))
        resultats.append(checks.check_retours_coherents(
            ventes, "is_retour", "date_retour", "date_commande"
        ))

    # --- 8. Domaines fermés ---
    for (table, colonne), valeurs in DOMAINES_ATTENDUS.items():
        df = donnees.get(table)
        if df is not None and colonne in df.columns:
            resultats.append(checks.check_domaine_ferme(df, colonne, valeurs))

    return resultats


# --------------------------------------------------------------------------- #
# Rapport
# --------------------------------------------------------------------------- #
def construire_rapport(
    inventaire: dict, changements: list, resultats: list[CheckResult],
    volumetries: dict, partiel: bool,
) -> dict:
    r = checks.resume(resultats)
    bloquants = changements_bloquants(changements)
    return {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "mode": "lecture_seule",
        "ecriture_supabase": False,
        "donnees_reelles_modifiees": False,
        "echantillonnage_partiel": partiel,
        "validation_reussie": r["validation_reussie"],
        "resume": r,
        "volumetries": volumetries,
        "changements_de_schema": [c.as_dict() for c in changements],
        "changements_invalidant_la_comparaison_v1": [c.as_dict() for c in bloquants],
        "consequence_si_changements_bloquants": (
            "Les métriques V1 ne sont PAS directement comparables aux nouvelles. Il faut d'abord "
            "recalculer les baselines V1 sur le nouveau périmètre, puis seulement comparer."
            if bloquants else "Aucun changement invalidant la comparaison directe avec la V1."
        ),
        "controles": [c.as_dict() for c in resultats],
        "tables_inventoriees": sorted(inventaire),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validation en lecture seule d'une livraison.")
    parser.add_argument("--tables", default=None, help="liste séparée par des virgules")
    parser.add_argument("--limit", type=int, default=None, help="échantillon par table")
    parser.add_argument("--sortie", default=str(RAPPORT_DEFAUT))
    args = parser.parse_args(argv)

    contrat = load_contract()
    tables_cibles = (
        [t.strip() for t in args.tables.split(",") if t.strip()]
        if args.tables else sorted(contrat.schema_actuel)
    )

    try:
        from src.data.connection import get_data_source

        with get_data_source() as source:
            disponibles = set(source.list_tables())
            manquantes = [t for t in tables_cibles if t not in disponibles]
            tables = [t for t in tables_cibles if t in disponibles]

            inventaire = inventorier_schema(source, tables)
            donnees = {t: source.fetch_table(t, limit=args.limit) for t in tables}
    except Exception as exc:  # noqa: BLE001
        # Le message d'exception contient typiquement l'URL de connexion complète.
        print(f"Connexion impossible : {expurger(exc)}", file=sys.stderr)
        return 1

    if manquantes:
        print(f"Tables absentes de la livraison : {manquantes}", file=sys.stderr)

    changements = compare_schemas(
        _schema_actuel_pour_comparaison(contrat),
        {t: {**d, "cle_primaire": None, "grain": None} for t, d in inventaire.items()},
        contrat.renommages_probables,
    )
    resultats = executer_controles(donnees, contrat, partiel=args.limit is not None)

    volumetries = {
        t: {
            "lignes_livrees": inventaire[t]["lignes"],
            "lignes_reference": contrat.schema_actuel.get(t, {}).get("lignes"),
            "ecart_relatif": (
                (inventaire[t]["lignes"] - contrat.schema_actuel[t]["lignes"])
                / contrat.schema_actuel[t]["lignes"]
                if contrat.schema_actuel.get(t, {}).get("lignes") else None
            ),
        }
        for t in inventaire
    }

    rapport = construire_rapport(inventaire, changements, resultats, volumetries, args.limit is not None)

    V2_EVAL.mkdir(parents=True, exist_ok=True)
    texte = expurger(json.dumps(rapport, indent=2, ensure_ascii=False, default=str))
    from pathlib import Path

    Path(args.sortie).write_text(texte, encoding="utf-8")

    res = rapport["resume"]
    print(f"Contrôles : {res['n_controles']} | erreurs : {res['n_erreurs']} | "
          f"avertissements : {res['n_avertissements']}")
    for c in resultats:
        if not c.ok:
            marque = "ERREUR" if c.bloquant else "AVERT."
            print(f"  [{marque}] {c.nom} : {expurger(c.message)}")
    if rapport["changements_invalidant_la_comparaison_v1"]:
        print(f"\n{len(rapport['changements_invalidant_la_comparaison_v1'])} changement(s) de schéma "
              "invalident la comparaison directe avec les baselines V1.")
    print(f"\nRapport : {args.sortie}")

    return 0 if res["validation_reussie"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
