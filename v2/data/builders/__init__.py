"""Builders des datasets attendus après la livraison enrichie.

**Aucun de ces builders n'est exécuté sur les données actuelles.** Ils exigent
des colonnes (`order_id`, `session_id`, `event_timestamp`, `is_bot`, ...) qui
n'existent pas encore. Chacun lève `ColonnesManquantes` plutôt que de se
replier sur une heuristique : un dataset construit sur des suppositions est
pire qu'un dataset absent, parce que plus rien ne distingue ensuite ce qui a
été mesuré de ce qui a été deviné.

Ils sont couverts par `v2/tests/test_future_dataset_builders.py`, exclusivement
sur des fixtures synthétiques explicitement étiquetées comme telles.
"""

from v2.data.builders.common import ColonnesManquantes, exiger_colonnes

__all__ = ["ColonnesManquantes", "exiger_colonnes"]
