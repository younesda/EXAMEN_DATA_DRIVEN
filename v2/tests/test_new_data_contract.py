"""Tests du contrat de données et de la comparaison de schémas.

Toutes les données de ce fichier sont **SYNTHÉTIQUES** : petites fixtures
écrites à la main pour couvrir des cas précis. Elles ne décrivent aucune
réalité métier et ne doivent jamais apparaître dans un rapport comme des
mesures.
"""

from __future__ import annotations

import pytest

from v2.data.contract import (
    ChangeKind,
    changements_bloquants,
    compare_schemas,
    load_contract,
)

# --------------------------------------------------------------------------- #
# Fixtures SYNTHÉTIQUES
# --------------------------------------------------------------------------- #
SYNTH_AVANT = {
    "fact_ventes": {
        "colonnes": {
            "vente_id": {"type": "text", "nullable": False},
            "quantite": {"type": "integer", "nullable": False},
            "client_key": {"type": "text", "nullable": True},
        },
        "cle_primaire": ["vente_id"],
        "grain": "ligne de vente",
    },
}


def _apres(**changements) -> dict:
    """Copie de SYNTH_AVANT avec les modifications demandées."""
    base = {
        "fact_ventes": {
            "colonnes": dict(SYNTH_AVANT["fact_ventes"]["colonnes"]),
            "cle_primaire": list(SYNTH_AVANT["fact_ventes"]["cle_primaire"]),
            "grain": SYNTH_AVANT["fact_ventes"]["grain"],
        }
    }
    base["fact_ventes"].update(changements)
    return base


# --------------------------------------------------------------------------- #
# Le contrat lui-même
# --------------------------------------------------------------------------- #
def test_contrat_se_charge_et_expose_les_sections_attendues():
    c = load_contract()
    assert c.schema_actuel and c.champs_attendus
    assert c.seuils_couverture and c.controles_integrite


def test_contrat_declare_les_champs_bloquants_attendus():
    """order_id, session_id, event_timestamp et les indicateurs bot/test sont
    la raison d'être de la nouvelle livraison : ils doivent être obligatoires."""
    obligatoires = set(load_contract().champs_obligatoires())
    for attendu in [
        ("fact_ventes", "order_id"),
        ("fact_evenements_web", "session_id"),
        ("fact_evenements_web", "event_timestamp"),
        ("fact_evenements_web", "is_bot"),
        ("fact_evenements_web", "is_test_interne"),
    ]:
        assert attendu in obligatoires, f"{attendu} devrait être obligatoire"


def test_chaque_champ_attendu_documente_son_comportement_si_absent():
    """Sans cette règle, un champ manquant laisserait le pipeline décider seul."""
    c = load_contract()
    for table, champs in c.champs_attendus.items():
        for champ in champs:
            texte = champ.get("si_absent", "")
            assert texte and len(texte) > 20, f"{table}.{champ['nom']} : si_absent non documenté"


def test_chaque_champ_attendu_declare_type_nullabilite_et_usage():
    c = load_contract()
    for table, champs in c.champs_attendus.items():
        for champ in champs:
            for cle in ("type", "nullable", "obligatoire", "usage", "regle_qualite", "format"):
                assert cle in champ, f"{table}.{champ['nom']} : '{cle}' manquant"
            assert champ["usage"], f"{table}.{champ['nom']} : usage vide"


def test_contrat_interdit_ecriture_et_valeurs_fictives():
    meta = load_contract().raw["meta"]
    assert meta["lecture_seule"] is True
    assert meta["ecriture_supabase_autorisee"] is False
    assert meta["creation_de_valeurs_fictives_autorisee"] is False


def test_seuils_couverture_sont_des_parts_valides():
    c = load_contract()
    for cle, regle in c.seuils_couverture.items():
        if cle == "couverture_historique_minimale":
            assert 0.0 < float(regle["part_periode_actuelle_couverte"]) <= 1.0
            continue
        assert 0.0 < float(regle["min_non_null"]) <= 1.0, cle


# --------------------------------------------------------------------------- #
# Détection des changements
# --------------------------------------------------------------------------- #
def test_detecte_un_ajout_de_colonne():
    apres = _apres(colonnes={**SYNTH_AVANT["fact_ventes"]["colonnes"],
                             "order_id": {"type": "text", "nullable": False}})
    ch = compare_schemas(SYNTH_AVANT, apres)
    assert [c.colonne for c in ch if c.kind is ChangeKind.AJOUT] == ["order_id"]


def test_detecte_une_suppression_de_colonne():
    cols = dict(SYNTH_AVANT["fact_ventes"]["colonnes"])
    del cols["client_key"]
    ch = compare_schemas(SYNTH_AVANT, _apres(colonnes=cols))
    assert [c.colonne for c in ch if c.kind is ChangeKind.SUPPRESSION] == ["client_key"]


def test_detecte_un_changement_de_type():
    cols = dict(SYNTH_AVANT["fact_ventes"]["colonnes"])
    cols["quantite"] = {"type": "numeric", "nullable": False}
    ch = compare_schemas(SYNTH_AVANT, _apres(colonnes=cols))
    assert [c.colonne for c in ch if c.kind is ChangeKind.TYPE] == ["quantite"]


def test_alias_de_type_ne_produit_pas_de_faux_positif():
    """int4 et integer sont le même type : les signaler noierait les vrais
    changements dans du bruit."""
    cols = dict(SYNTH_AVANT["fact_ventes"]["colonnes"])
    cols["quantite"] = {"type": "int4", "nullable": False}
    cols["vente_id"] = {"type": "character varying", "nullable": False}
    ch = compare_schemas(SYNTH_AVANT, _apres(colonnes=cols))
    assert [c for c in ch if c.kind is ChangeKind.TYPE] == []


def test_detecte_un_changement_de_nullabilite():
    cols = dict(SYNTH_AVANT["fact_ventes"]["colonnes"])
    cols["quantite"] = {"type": "integer", "nullable": True}
    ch = compare_schemas(SYNTH_AVANT, _apres(colonnes=cols))
    nulls = [c for c in ch if c.kind is ChangeKind.NULLABILITE]
    assert len(nulls) == 1 and nulls[0].apres is True


def test_detecte_un_changement_de_cle_primaire():
    ch = compare_schemas(SYNTH_AVANT, _apres(cle_primaire=["order_id", "produit_key"]))
    assert any(c.kind is ChangeKind.CLE for c in ch)


def test_detecte_un_changement_de_grain():
    ch = compare_schemas(SYNTH_AVANT, _apres(grain="commande x produit"))
    grains = [c for c in ch if c.kind is ChangeKind.GRAIN]
    assert len(grains) == 1
    assert "recalculé" in grains[0].detail or "comparable" in grains[0].detail


def test_renommage_declare_est_fusionne_et_non_compte_deux_fois():
    """Un renommage vu comme suppression + ajout masquerait la rupture :
    le code aval qui lit l'ancien nom casserait sans avertissement."""
    avant = {"fact_evenements_web": {
        "colonnes": {"type_event": {"type": "text", "nullable": False}},
        "cle_primaire": ["event_id"], "grain": "evenement"}}
    apres = {"fact_evenements_web": {
        "colonnes": {"event_type": {"type": "text", "nullable": False}},
        "cle_primaire": ["event_id"], "grain": "evenement"}}

    ch = compare_schemas(avant, apres, load_contract().renommages_probables)
    assert [c.kind for c in ch] == [ChangeKind.RENOMMAGE_PROBABLE]
    assert (ch[0].avant, ch[0].apres) == ("type_event", "event_type")


def test_renommage_non_declare_reste_suppression_plus_ajout():
    """On ne devine pas les renommages : seuls ceux du contrat sont fusionnés."""
    cols = dict(SYNTH_AVANT["fact_ventes"]["colonnes"])
    del cols["client_key"]
    cols["customer_key"] = {"type": "text", "nullable": True}
    kinds = {c.kind for c in compare_schemas(SYNTH_AVANT, _apres(colonnes=cols))}
    assert kinds == {ChangeKind.SUPPRESSION, ChangeKind.AJOUT}


def test_table_disparue_est_signalee():
    ch = compare_schemas(SYNTH_AVANT, {})
    assert len(ch) == 1 and ch[0].kind is ChangeKind.SUPPRESSION and ch[0].colonne is None


@pytest.mark.parametrize("kind", [ChangeKind.GRAIN, ChangeKind.CLE, ChangeKind.SUPPRESSION])
def test_changements_invalidant_la_comparaison_v1(kind):
    """Grain, clé et suppression cassent la comparabilité avec les baselines V1
    et doivent donc être remontés comme bloquants."""
    if kind is ChangeKind.GRAIN:
        apres = _apres(grain="commande x produit")
    elif kind is ChangeKind.CLE:
        apres = _apres(cle_primaire=["autre"])
    else:
        cols = dict(SYNTH_AVANT["fact_ventes"]["colonnes"])
        del cols["quantite"]
        apres = _apres(colonnes=cols)

    assert any(c.kind is kind for c in changements_bloquants(compare_schemas(SYNTH_AVANT, apres)))


def test_aucun_changement_quand_les_schemas_sont_identiques():
    assert compare_schemas(SYNTH_AVANT, _apres()) == []
