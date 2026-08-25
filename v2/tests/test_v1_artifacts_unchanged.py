"""Garde-fou fondamental de la V2 : la V1 est immuable.

Ce test échoue dès qu'un artefact V1 (forecasting, pricing ou recommandation)
est modifié, supprimé ou remplacé — quelle qu'en soit la raison. Il est le
premier rempart contre une V2 qui « améliorerait » ses chiffres en touchant
discrètement à la référence.

Si ce test échoue légitimement (parce que la V1 doit réellement être
regénérée), il faut une décision explicite : regénérer le verrou avec
``python -m v2.config.v1_reference`` et documenter pourquoi — jamais le
contourner silencieusement.
"""

from __future__ import annotations

import pytest

from v2.config.v1_reference import (
    V1_LOCK_PATH,
    V1_LOCKED_ARTIFACTS,
    load_lock,
    load_v1_reference,
    verify_lock,
)


def test_le_verrou_v1_existe():
    assert V1_LOCK_PATH.exists(), (
        "Le verrou V1 est absent. Le générer avec `python -m v2.config.v1_reference` "
        "AVANT toute expérimentation V2."
    )


def test_aucun_artefact_v1_modifie():
    problems = verify_lock()
    assert not problems, (
        "Des artefacts V1 ont été modifiés — la V2 ne doit JAMAIS toucher à la V1 :\n  - "
        + "\n  - ".join(problems)
    )


def test_tous_les_artefacts_v1_attendus_sont_verrouilles():
    lock = load_lock()
    locked = set(lock["artefacts"].keys())
    expected = {
        str(p.relative_to(V1_LOCK_PATH.parents[2])).replace("\\", "/") for p in V1_LOCKED_ARTIFACTS
    }
    assert locked == expected, (
        "La liste des artefacts verrouillés a divergé de V1_LOCKED_ARTIFACTS — "
        "regénérer le verrou explicitement."
    )


def test_les_trois_phases_v1_sont_couvertes():
    """Le verrou doit couvrir les trois phases, pas seulement le forecasting."""
    lock = load_lock()
    keys = " ".join(lock["artefacts"].keys())
    assert "forecast_final" in keys, "Aucun artefact forecasting V1 verrouillé"
    assert "pricing_final" in keys, "Aucun artefact pricing V1 verrouillé"
    assert "recsys_final" in keys, "Aucun artefact recommandation V1 verrouillé"


def test_aucun_artefact_v1_manquant_au_verrouillage():
    lock = load_lock()
    absents = [rel for rel, e in lock["artefacts"].items() if e.get("statut") == "ABSENT"]
    assert not absents, f"Artefacts V1 attendus mais absents au moment du verrouillage : {absents}"


# =============================================================================
# Les références chiffrées viennent du snapshot V1, jamais d'une constante V2
# =============================================================================
def test_les_references_v1_sont_chargees_depuis_le_snapshot():
    ref = load_v1_reference()
    assert ref.source_snapshot.endswith("v1_metrics_snapshot.json")
    # Bornes de cohérence larges : le but n'est pas de refiger les valeurs ici
    # (ce serait exactement le codage en dur qu'on veut éviter), mais de
    # détecter un chargement cassé qui renverrait 0, None ou une valeur absurde.
    assert 0.0 < ref.wape_cumule_30j < 1.0
    assert 0.0 < ref.wape_cumule_7j < 1.0
    assert ref.wape_cumule_30j < ref.wape_cumule_7j, (
        "La WAPE cumulée à 30 j doit être inférieure à celle à 7 j (compensation des erreurs "
        "sur un horizon plus long) — un chargement inversé produirait l'inverse."
    )
    assert 1.0 < ref.wape_quotidien < 2.0
    assert 0.5 < ref.couverture_intervalle_80_produits_A < 1.0
    assert 0.5 < ref.couverture_intervalle_80_globale_j15_j30 < 1.0


def test_aucune_valeur_de_reference_codee_en_dur_dans_le_module_v2():
    """Vérification structurelle : le module de référence ne doit contenir
    aucune des valeurs V1 en dur — elles doivent toutes venir des fichiers."""
    import v2.config.v1_reference as mod

    source = open(mod.__file__, encoding="utf-8").read()
    for interdit in ("0.2772", "0.4619", "1.0947", "0.7436", "0.2771792"):
        assert interdit not in source, (
            f"La valeur {interdit} est codée en dur dans v1_reference.py — "
            "les références V1 doivent être lues depuis les artefacts, jamais recopiées."
        )
