"""Journalisation structuree du service V4.

Chaque evenement est emis en JSON sur une seule ligne, pour rester lisible
par un agregateur de journaux. Aucune donnee client n'est journalisee : le
service ne manipule que des identifiants produit et des parametres de
simulation.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

_LOGGER = logging.getLogger("api_v4")


def configure(niveau: int = logging.INFO) -> None:
    if _LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(niveau)
    _LOGGER.propagate = False


def _emettre(niveau: int, evenement: str, **champs: Any) -> None:
    configure()
    charge = {"evenement": evenement, **champs}
    _LOGGER.log(niveau, json.dumps(charge, ensure_ascii=False, default=str))


def info(evenement: str, **champs: Any) -> None:
    _emettre(logging.INFO, evenement, **champs)


def avertissement(evenement: str, **champs: Any) -> None:
    _emettre(logging.WARNING, evenement, **champs)


def erreur(evenement: str, **champs: Any) -> None:
    _emettre(logging.ERROR, evenement, **champs)
