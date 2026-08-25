"""Référence V1 immuable — verrouillage et chargement.

Deux responsabilités, strictement séparées :

1. **Verrouillage** : empreintes SHA-256 de tous les artefacts V1 (les trois
   phases), figées dans ``v2/config/v1_lock.json``. Un test dédié échoue si
   l'un d'eux change — la V2 ne doit JAMAIS modifier la V1.
2. **Chargement des références chiffrées** : les seuils de comparaison V1
   (WAPE 30j/7j/quotidien, couverture des intervalles sur produits A) sont
   lus **directement depuis les artefacts V1**, jamais recopiés en dur dans
   le code V2. Si un chiffre de référence change côté V1, la V2 s'en aperçoit
   au lieu de comparer à une valeur périmée.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
V1_LOCK_PATH = PROJECT_ROOT / "v2" / "config" / "v1_lock.json"

V1_SNAPSHOT_PATH = PROJECT_ROOT / "reports" / "forecast_final" / "v1_metrics_snapshot.json"
V1_FORECAST_META_PATH = PROJECT_ROOT / "models" / "forecast_final" / "metadata.json"
V1_INTERVALS_AE_PATH = PROJECT_ROOT / "reports" / "23_intervals_ae.csv"
V1_FORECASTING_REPORT = PROJECT_ROOT / "reports" / "23_rapport_final_forecasting.md"

# Artefacts V1 verrouillés — toute modification fait échouer
# `v2/tests/test_v1_artifacts_unchanged.py`.
V1_LOCKED_ARTIFACTS: tuple[Path, ...] = (
    # --- Forecasting V1 ---
    PROJECT_ROOT / "models" / "forecast_final" / "metadata.json",
    PROJECT_ROOT / "reports" / "forecast_final" / "v1_metrics_snapshot.json",
    PROJECT_ROOT / "reports" / "forecast_final" / "v1_manifest.json",
    PROJECT_ROOT / "reports" / "forecast_final" / "v1_final_checks.json",
    PROJECT_ROOT / "reports" / "forecast_final" / "previsions_finales.parquet",
    PROJECT_ROOT / "reports" / "forecast_final" / "previsions_finales.csv",
    PROJECT_ROOT / "reports" / "forecast_final" / "forecasting_v2_objectives.md",
    PROJECT_ROOT / "reports" / "23_rapport_final_forecasting.md",
    PROJECT_ROOT / "reports" / "24_entrainement_final.md",
    PROJECT_ROOT / "reports" / "25_forecasting_v1_cloture.md",
    # --- Pricing V1 ---
    PROJECT_ROOT / "reports" / "pricing_final" / "metadata.json",
    PROJECT_ROOT / "reports" / "pricing_final" / "manifest.json",
    PROJECT_ROOT / "reports" / "pricing_final" / "final_checks.json",
    PROJECT_ROOT / "reports" / "pricing_final" / "pricing_v2_objectives.md",
    PROJECT_ROOT / "reports" / "33_pricing_comparaison_rapport_final.md",
    # --- Recommandation V1 ---
    PROJECT_ROOT / "reports" / "recsys_final" / "metadata.json",
    PROJECT_ROOT / "reports" / "recsys_final" / "manifest.json",
    PROJECT_ROOT / "reports" / "recsys_final" / "final_checks.json",
    PROJECT_ROOT / "reports" / "recsys_final" / "recommendation_v2_objectives.md",
    PROJECT_ROOT / "reports" / "41_recsys_consolidation_finale.md",
    # --- Synthèses validées ---
    PROJECT_ROOT / "reports" / "SYNTHESE_EQUIPE_V1.md",
    PROJECT_ROOT / "reports" / "MESSAGE_SLACK_V1.md",
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_lock() -> dict:
    """Calcule les empreintes de tous les artefacts V1 verrouillés."""
    entries = {}
    for path in V1_LOCKED_ARTIFACTS:
        rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if not path.exists():
            entries[rel] = {"statut": "ABSENT"}
            continue
        entries[rel] = {"sha256": sha256_of(path), "taille_octets": path.stat().st_size}
    return {"artefacts": entries, "n_artefacts": len(entries)}


def write_lock() -> dict:
    lock = build_lock()
    V1_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    V1_LOCK_PATH.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
    return lock


def load_lock() -> dict:
    return json.loads(V1_LOCK_PATH.read_text(encoding="utf-8"))


def verify_lock() -> list[str]:
    """Renvoie la liste des écarts constatés (vide si tout est intact)."""
    lock = load_lock()
    problems = []
    for rel, expected in lock["artefacts"].items():
        path = PROJECT_ROOT / rel
        if expected.get("statut") == "ABSENT":
            if path.exists():
                problems.append(f"{rel}: artefact absent au verrouillage mais présent maintenant")
            continue
        if not path.exists():
            problems.append(f"{rel}: artefact V1 SUPPRIMÉ")
            continue
        actual = sha256_of(path)
        if actual != expected["sha256"]:
            problems.append(
                f"{rel}: artefact V1 MODIFIÉ (sha256 attendu {expected['sha256'][:12]}…, "
                f"obtenu {actual[:12]}…)"
            )
    return problems


# =============================================================================
# Références chiffrées V1 — chargées depuis les artefacts, jamais codées en dur
# =============================================================================
@dataclass(frozen=True)
class V1Reference:
    """Valeurs de référence V1, lues depuis le snapshot figé."""

    wape_cumule_30j: float
    wape_cumule_14j: float
    wape_cumule_7j: float
    wape_quotidien: float
    couverture_intervalle_80_produits_A: float
    couverture_intervalle_80_globale_j15_j30: float
    modele: str
    source_snapshot: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_v1_reference(model: str = "AutoETS") -> V1Reference:
    """Charge les références V1 depuis `reports/forecast_final/v1_metrics_snapshot.json`
    et `reports/23_intervals_ae.csv`. Aucune valeur n'est recopiée à la main.

    Note : `AutoETS` désigne ici le pipeline opérationnel complet
    « AutoETS + repli Naive » — c'est ce que le snapshot V1 mesure (cf.
    `reports/23_rapport_final_forecasting.md` §5), et donc la seule référence
    comparable à un candidat V2 évalué sur le même périmètre.
    """
    snapshot = json.loads(V1_SNAPSHOT_PATH.read_text(encoding="utf-8"))

    daily = snapshot["metriques_quotidiennes_grain_produit_jour"][model]
    cumule = snapshot["metriques_cumulees_7_14_30j"][model]

    couverture_A, couverture_globale = _load_v1_interval_coverage()

    return V1Reference(
        wape_cumule_30j=float(cumule["30"]["WAPE"]),
        wape_cumule_14j=float(cumule["14"]["WAPE"]),
        wape_cumule_7j=float(cumule["7"]["WAPE"]),
        wape_quotidien=float(daily["WAPE_quotidien"]),
        couverture_intervalle_80_produits_A=couverture_A,
        couverture_intervalle_80_globale_j15_j30=couverture_globale,
        modele=model,
        source_snapshot=str(V1_SNAPSHOT_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    )


def _load_v1_interval_coverage() -> tuple[float, float]:
    """Couverture empirique des intervalles 80 % de la V1.

    - Produits A : valeur publiée au rapport 23 §8 (couverture par segment),
      extraite du markdown car ce détail n'est pas dans le CSV d'intervalles.
    - Globale (bucket J+15-30) : lue depuis `reports/23_intervals_ae.csv`
      quand il est disponible, sinon depuis le tableau AutoETS du rapport 23
      versionné. Les deux artefacts publient la même mesure validée.
    """
    import csv
    import math
    import re

    couverture_globale = float("nan")
    if V1_INTERVALS_AE_PATH.exists():
        with open(V1_INTERVALS_AE_PATH, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("horizon") == "J+15 a J+30" and abs(float(row["niveau_vise"]) - 0.80) < 1e-9:
                    couverture_globale = float(row["couverture_empirique"])
                    break

    couverture_A = float("nan")
    if V1_FORECASTING_REPORT.exists():
        text = V1_FORECASTING_REPORT.read_text(encoding="utf-8")
        # Ligne du tableau §8, de la forme :
        #   | classe A | <niveau_vise> | <couverture_empirique> | <n_points> |
        # On extrait la 2e colonne numérique (couverture empirique observée).
        m = re.search(r"\|\s*classe A\s*\|\s*[\d.]+\s*\|\s*([\d.]+)\s*\|", text)
        if m:
            couverture_A = float(m.group(1))

        if math.isnan(couverture_globale):
            # Le CSV historique n'est pas versionné. Le premier tableau de la
            # section de couverture est celui d'AutoETS+repli, modèle V1 retenu.
            section_match = re.search(
                r"\*\*AutoETS\+repli — couverture empirique par horizon\s*:\*\*"
                r"(?P<table>.*?)"
                r"\*\*WindowAverage28",
                text,
                flags=re.DOTALL,
            )
            if section_match:
                row_match = re.search(
                    r"\|\s*J\+15 a J\+30\s*\|\s*0\.8000\s*\|\s*([\d.]+)\s*\|",
                    section_match.group("table"),
                )
                if row_match:
                    couverture_globale = float(row_match.group(1))

    return couverture_A, couverture_globale


if __name__ == "__main__":
    lock = write_lock()
    print(json.dumps(lock, indent=2, ensure_ascii=False))
    ref = load_v1_reference()
    print()
    print(json.dumps(ref.to_dict(), indent=2, ensure_ascii=False))
