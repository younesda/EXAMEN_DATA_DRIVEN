"""Clôture formelle Recommandation V2 — 4 livrables + contrôles.

    python -m v2.recommendation.finalize_recsys_v2

Corrige également la conclusion sur R4 : l'absence de gain vaut **dans ce
protocole**, avec ces critères de routage prédéfinis. Elle ne prouve pas
qu'aucun sous-groupe pertinent ne puisse exister avec d'autres données ou
d'autres critères validés ultérieurement.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

from src.config.settings import PROJECT_ROOT
from v2.config.v1_reference import verify_lock
from v2.evaluation.harness import V2_EVAL, V2_MODELS, V2_REPORTS

METADATA_PATH = V2_MODELS / "recsys_v2_metadata.json"
MANIFEST_PATH = V2_MODELS / "recsys_v2_manifest.json"
CHECKS_PATH = V2_EVAL / "recsys_v2_final_checks.json"
REPORT_PATH = V2_REPORTS / "12_recsys_v2_cloture.md"

R4_REASON = "no_personalization_gain_under_predefined_routing_protocol"

R4_CONCLUSION = (
    "Les critères d'éligibilité prédéfinis classent presque tous les clients comme personnalisables "
    "(99,9 %) et R3 ne démontre aucun gain sur cette population. R4 n'est donc pas justifié dans ce "
    "protocole. **Cela ne prouve pas qu'aucun sous-groupe pertinent ne puisse exister** avec d'autres "
    "données ou d'autres critères validés ultérieurement."
)

MANIFEST_ARTIFACTS = (
    "v2/config/recsys_v2_thresholds.json",
    "v2/recommendation/v1_recsys_reference.py",
    "v2/recommendation/candidates_r1_r2.py",
    "v2/recommendation/candidate_r3.py",
    "v2/evaluation/recsys_R1_R2_metrics.json",
    "v2/evaluation/R3_pilote_metrics.json",
    "v2/evaluation/recsys_v2_decision_finale.json",
    "v2/models/recsys_v2_status.json",
    "v2/reports/08_recsys_v2_protocole.md",
    "v2/reports/09_recsys_R1_R2.md",
    "v2/reports/10_recsys_R3_pilote.md",
    "v2/reports/11_recsys_v2_cloture.md",
    "v2/tests/test_recsys_r1_r2.py",
)

SECRET_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"postgres(?:ql)?://[^\s\"']+:[^\s\"']+@"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def run_test_suite() -> dict:
    """Exécute la suite de tests AVANT tout chargement de données lourdes.

    Le process parent garde sinon en mémoire pandas, numpy et l'ensemble des
    métriques, ce qui a déjà provoqué des erreurs de collecte pytest purement
    liées à la pression mémoire de cet environnement (et non à un vrai échec).
    En lançant les tests en premier, le sous-processus dispose du maximum de
    mémoire disponible. En cas d'échec, la sortie complète est conservée pour
    que le problème soit diagnosticable, jamais réduit à un simple compteur.
    """
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT,
                           capture_output=True, text=True, timeout=600)
        out = r.stdout.strip()
        resume = out.splitlines()[-1] if out else "voir stderr"
        return {
            "ok": r.returncode == 0, "resume": resume, "attendu_min": 201,
            "returncode": r.returncode,
            "sortie_complete_si_echec": None if r.returncode == 0 else out[-4000:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "resume": f"échec d'exécution : {exc}", "attendu_min": 201}


def main() -> None:
    tests_result = run_test_suite()

    r1r2 = json.loads((V2_EVAL / "recsys_R1_R2_metrics.json").read_text(encoding="utf-8"))
    r3 = json.loads((V2_EVAL / "R3_pilote_metrics.json").read_text(encoding="utf-8"))
    v1 = r1r2["reference_v1"]
    var = r1r2["variantes"]
    part_perso = float(np.mean([e["part_clients_personnalises"] for e in r3["statistiques_eligibilite"]]))

    # --- Métadonnées --------------------------------------------------------
    metadata = {
        "primary_model": "v1_popularite_globale",
        "recommendation_v2_validated": False,
        "personalization_validated": False,
        "diversity_challenger": "R2",
        "diversity_challenger_automatic_use": False,
        "R4_status": "not_launched",
        "R4_reason": R4_REASON,
        "genere_le": datetime.now(timezone.utc).isoformat(),

        "usage_autorise_r2": (
            "Scénario métier expérimental « Découvrir d'autres produits » uniquement, "
            "avec test A/B OBLIGATOIRE avant toute utilisation réelle. Jamais en usage automatique, "
            "jamais en remplacement du moteur principal."
        ),
        "r4_conclusion_nuancee": R4_CONCLUSION,

        "references_v1": {
            "recall_at_10": v1["recall_at_10"],
            "ndcg_at_10": v1["ndcg_at_10"],
            "couverture_catalogue": v1["couverture_catalogue"],
            "personalisation_validee": v1["personalisation_validee"],
        },
        "candidats": {
            "R1": {
                "status": "experiment_not_retained", "reason": "no_improvement_over_v1",
                "recall_at_10": var["R1_decouverte"]["moyennes"]["recall_at_10"],
                "ndcg_at_10": var["R1_decouverte"]["moyennes"]["ndcg_at_10"],
                "couverture": var["R1_decouverte"]["moyennes"]["catalog_coverage"],
            },
            "R2": {
                "status": "exploratory_diversity_challenger",
                "primary_model_eligible": False,
                "reason": "coverage_and_diversity_improved_but_relevance_loss_exceeds_threshold",
                "recall_at_10": var["R2_decouverte"]["moyennes"]["recall_at_10"],
                "ndcg_at_10": var["R2_decouverte"]["moyennes"]["ndcg_at_10"],
                "couverture": var["R2_decouverte"]["moyennes"]["catalog_coverage"],
                "concentration_top10": var["R2_decouverte"]["concentration_moyenne"],
                "concentration_r1_comparaison": var["R1_decouverte"]["concentration_moyenne"],
                "penalite_non_reglee_retrospectivement": True,
                "test_ab_obligatoire_avant_usage": True,
            },
            "R3": {
                "status": "experiment_not_retained", "reason": "relevance_not_improved",
                "part_clients_personnalises": part_perso,
                "seuils_eligibilite": r3["seuils_eligibilite_fixes_a_priori"],
                "signal_sous_groupe": r3["signal_sous_groupe_personnalisable"],
            },
            "R4": {"status": "not_launched", "reason": R4_REASON, "conclusion": R4_CONCLUSION},
        },
        "donnees_supplementaires_necessaires": [
            "order_id", "session_id", "event_timestamp", "davantage d'interactions par client",
        ],
        "perimetre": {"n_fenetres": 4, "artefacts_v1_modifies": False},
        "aucune_publication_supabase": True,
        "aucun_deploiement": True,
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- Manifeste ----------------------------------------------------------
    manifest = {"genere_le": datetime.now(timezone.utc).isoformat(), "artefacts": {}}
    for rel in MANIFEST_ARTIFACTS:
        path = PROJECT_ROOT / rel
        manifest["artefacts"][rel] = (
            {"sha256": sha256_of(path), "taille_octets": path.stat().st_size}
            if path.exists() else {"statut": "ABSENT"}
        )
    manifest["n_artefacts"] = len(manifest["artefacts"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- Contrôles ----------------------------------------------------------
    checks: dict = {"genere_le": datetime.now(timezone.utc).isoformat()}

    problems = verify_lock()
    checks["v1_intacte"] = {"ok": not problems, "n_artefacts_verrouilles": 22, "ecarts": problems}

    statuts = {k: v.get("status") for k, v in metadata["candidats"].items()}
    checks["statuts_candidats"] = {
        "ok": statuts == {
            "R1": "experiment_not_retained", "R2": "exploratory_diversity_challenger",
            "R3": "experiment_not_retained", "R4": "not_launched",
        },
        "statuts": statuts,
    }

    checks["aucun_doublon_ni_produit_ineligible"] = {
        "ok": all(v["n_doublons_total"] == 0 and v["n_ineligibles_total"] == 0 for v in var.values()),
        "detail": {k: {"doublons": v["n_doublons_total"], "ineligibles": v["n_ineligibles_total"]}
                   for k, v in var.items()},
    }

    checks["aucun_candidat_accepte"] = {
        "ok": not any(v["accepte"] for v in r1r2["verdicts"].values()) and not r3["porte_franchie"],
        "note": "La V1 reste le modèle principal — résultat par défaut du protocole.",
    }

    checks["r2_non_eligible_usage_automatique"] = {
        "ok": metadata["diversity_challenger_automatic_use"] is False,
        "note": "R2 exige un test A/B avant toute utilisation réelle.",
    }

    manifeste_ok = all("sha256" in v for v in manifest["artefacts"].values())
    checks["manifeste_complet"] = {"ok": manifeste_ok, "n_artefacts": manifest["n_artefacts"]}

    secrets = {}
    for rel in MANIFEST_ARTIFACTS:
        path = PROJECT_ROOT / rel
        if path.exists() and path.suffix in (".py", ".json", ".md"):
            hits = [p.pattern for p in SECRET_PATTERNS if p.search(path.read_text(encoding="utf-8", errors="ignore"))]
            if hits:
                secrets[rel] = hits
    checks["aucun_secret"] = {"ok": not secrets, "detail": secrets}

    checks["tests"] = tests_result

    checks["verdict_global"] = (
        "TOUS LES CONTROLES PASSENT"
        if all(v.get("ok") for v in checks.values() if isinstance(v, dict) and "ok" in v)
        else "AU MOINS UN CONTROLE A ECHOUE"
    )
    CHECKS_PATH.write_text(json.dumps(checks, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    _write_report(metadata, checks, var, v1, r3, part_perso)
    print(f"Clôture Recommandation V2 écrite. Verdict : {checks['verdict_global']} — {checks['tests']['resume']}")


def _write_report(meta, checks, var, v1, r3, part_perso) -> None:
    lines = [
        "# 12 — Clôture formelle Recommandation V2",
        "",
        f"_Généré le {meta['genere_le']}. Branche `feature/v2-model-improvements`, non fusionnée dans `main`._",
        "",
        "## 1. Statut officiel",
        "",
        "```",
        f"primary_model: {meta['primary_model']}",
        f"recommendation_v2_validated: {str(meta['recommendation_v2_validated']).lower()}",
        f"personalization_validated: {str(meta['personalization_validated']).lower()}",
        f"diversity_challenger: {meta['diversity_challenger']}",
        f"diversity_challenger_automatic_use: {str(meta['diversity_challenger_automatic_use']).lower()}",
        f"R4_status: {meta['R4_status']}",
        f"R4_reason: {meta['R4_reason']}",
        "```",
        "",
        "## 2. Conclusion corrigée sur R4",
        "",
        meta["r4_conclusion_nuancee"],
        "",
        "Cette nuance est importante : le protocole a testé **un** jeu de critères de routage, fixé a "
        "priori (≥3 achats, ≥2 catégories, ≥60 % dans les catégories dominantes). Ces critères se sont "
        f"révélés non discriminants sur ces données ({part_perso:.1%} des clients éligibles). Un autre "
        "jeu de critères, ou des données plus riches, pourrait faire apparaître un sous-groupe où la "
        "personnalisation apporte réellement quelque chose. **Ce qui est établi ici, c'est l'absence de "
        "gain dans ce protocole — pas une impossibilité générale.**",
        "",
        "## 3. Résultats consolidés",
        "",
        "| Modèle | Recall@10 | NDCG@10 | Couverture | Statut |",
        "|---|---:|---:|---:|---|",
        f"| **V1 popularité globale** | {_fmt(v1['recall_at_10'])} | {_fmt(v1['ndcg_at_10'])} | "
        f"{_fmt(v1['couverture_catalogue'])} | **Modèle principal** |",
        f"| R1 | {_fmt(var['R1_decouverte']['moyennes']['recall_at_10'])} | "
        f"{_fmt(var['R1_decouverte']['moyennes']['ndcg_at_10'])} | "
        f"{_fmt(var['R1_decouverte']['moyennes']['catalog_coverage'])} | `experiment_not_retained` |",
        f"| R2 | {_fmt(var['R2_decouverte']['moyennes']['recall_at_10'])} | "
        f"{_fmt(var['R2_decouverte']['moyennes']['ndcg_at_10'])} | "
        f"{_fmt(var['R2_decouverte']['moyennes']['catalog_coverage'])} | `exploratory_diversity_challenger` |",
        f"| R3 (pilote F1-F2) | {_fmt(r3['moyennes_r3']['recall_at_10'])} | "
        f"{_fmt(r3['moyennes_r3']['ndcg_at_10'])} | {_fmt(r3['moyennes_r3']['catalog_coverage'])} | "
        "`experiment_not_retained` |",
        "",
        "## 4. Usage autorisé de R2",
        "",
        meta["usage_autorise_r2"],
        "",
        f"R2 réduit la concentration des recommandations sur les 10 produits les plus recommandés de "
        f"**{_fmt(var['R1_decouverte']['concentration_moyenne'])} à "
        f"{_fmt(var['R2_decouverte']['concentration_moyenne'])}** et augmente la couverture catalogue de "
        "+64,6 %. C'est un levier de diversité démontré — mais au prix d'une perte de pertinence "
        "supérieure aux tolérances fixées, d'où l'exigence d'un test A/B avant tout usage réel.",
        "",
        "## 5. Contrôles de clôture",
        "",
        "| Contrôle | Résultat |",
        "|---|:---:|",
    ]
    libelles = {
        "v1_intacte": "V1 intacte (22 artefacts verrouillés)",
        "statuts_candidats": "Statuts R1-R4 conformes",
        "aucun_doublon_ni_produit_ineligible": "Aucun doublon ni produit inéligible",
        "aucun_candidat_accepte": "Aucun candidat accepté (V1 reste principale)",
        "r2_non_eligible_usage_automatique": "R2 non éligible à un usage automatique",
        "manifeste_complet": "Manifeste SHA-256 complet",
        "aucun_secret": "Aucun secret",
        "tests": "Suite de tests",
    }
    for key, label in libelles.items():
        lines.append(f"| {label} | {'✅' if checks.get(key, {}).get('ok') else '❌'} |")

    lines += [
        "",
        f"**{checks['verdict_global']}** — {checks['tests']['resume']} "
        f"(dont 21 tests R1/R2 ajoutés après constat d'un manque réel).",
        "",
        "## 6. Données supplémentaires nécessaires",
        "",
        "Pour espérer une personnalisation utile : " + ", ".join(f"`{d}`" for d in meta["donnees_supplementaires_necessaires"]) + ".",
        "",
        "## 7. Livrables",
        "",
        "- `v2/reports/12_recsys_v2_cloture.md` (ce document)",
        "- `v2/models/recsys_v2_metadata.json`",
        "- `v2/models/recsys_v2_manifest.json`",
        "- `v2/evaluation/recsys_v2_final_checks.json`",
        "",
        "Aucune écriture Supabase, aucun déploiement, aucune fusion dans `main`. Aucune expérience de "
        "recommandation supplémentaire n'a été relancée.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
