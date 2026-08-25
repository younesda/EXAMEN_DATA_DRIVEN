"""Pilote R3 sur les fenêtres 1 et 2, avec porte stricte.

    python -m v2.recommendation.run_r3_pilot

Porte (fixée avant l'exécution) — R3 ne poursuit que si, sur les fenêtres 1 et 2 :

* NDCG@10 ≥ celle de la V1 ;
* Recall@10 ≥ celui de la V1 ;
* couverture catalogue > celle de la V1 ;
* aucune dégradation > 5 % sur les clients peu actifs.

Mesure également, en préalable à une éventuelle décision sur R4 : nombre et
proportion de clients éligibles, achats moyens, sparsité de la matrice, et
**performance de la V1 sur ce même sous-groupe** (la seule comparaison qui
permette de dire si la personnalisation apporte quelque chose là où elle
s'applique).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.pipelines.recsys_prototype import stock_availability_at
from src.recsys.data import WINDOWS, build_stock, build_ventes, load_raw
from src.recsys.metrics import evaluate_recommendations
from v2.evaluation.harness import V2_EVAL, V2_REPORTS, current_rss_mb, log_event
from v2.recommendation.candidate_r3 import (
    MIN_ACHATS,
    MIN_CATEGORIES,
    MIX_DEFAUT,
    MIXES,
    PART_MIN_DOMINANTES,
    build_client_profiles,
    choose_mix_from_previous_windows,
    recommend_r3,
)
from v2.recommendation.candidates_r1_r2 import popularity_scores
from v2.recommendation.v1_recsys_reference import load_v1_reference

FENETRES_PILOTE = (1, 2)
K = 10


def _segments(train_v: pd.DataFrame, relevant: dict) -> dict[str, str]:
    counts = train_v.groupby("client_key").size()
    median = counts.median() if len(counts) else 0
    return {
        c: ("cold_start" if counts.get(c, 0) == 0 else ("actif" if counts.get(c, 0) >= median else "peu_actif"))
        for c in relevant
    }


def main() -> None:
    t0 = time.time()
    log_event({"type": "debut", "candidat": "R3_pilote", "memoire_rss_mb": current_rss_mb()})

    tables = load_raw()
    ventes, stock = build_ventes(tables), build_stock(tables)
    v1_ref = load_v1_reference()
    all_products = sorted(ventes["produit_key"].unique())
    produit_categorie = ventes.drop_duplicates("produit_key").set_index("produit_key")["categorie"].to_dict()

    specs = [w for w in WINDOWS if w.index in FENETRES_PILOTE]

    # --- Étape 1 : NDCG de chaque mix par fenêtre (pour le choix expansif) ---
    mix_perf: dict[int, dict[str, float]] = {}
    cache = {}
    for w in specs:
        train_v = ventes[ventes["date_complete"] <= w.train_end]
        test_v = ventes[(ventes["date_complete"] >= w.test_start) & (ventes["date_complete"] <= w.test_end)]
        relevant = test_v.groupby("client_key")["produit_key"].apply(set).to_dict()
        purchased = train_v.groupby("client_key")["produit_key"].apply(set).to_dict()
        stock_ok = stock_availability_at(stock, w.train_end)
        scores = popularity_scores(train_v, w.train_end)
        profiles = build_client_profiles(train_v)
        cache[w.index] = (train_v, relevant, purchased, stock_ok, scores, profiles)

        mix_perf[w.index] = {}
        for mix in MIXES:
            recs = {}
            for client in relevant:
                cands = [p for p in all_products if stock_ok.get(p, False) and p not in purchased.get(client, set())]
                v1_rank = sorted(cands, key=lambda p: scores.get(p, 0.0), reverse=True)[:K]
                top, _ = recommend_r3(client, profiles, v1_rank, scores, produit_categorie, cands, mix, K)
                recs[client] = top
            ev = evaluate_recommendations(recs, relevant, produit_categorie, set(all_products), k_list=[5, 10])
            mix_perf[w.index][mix] = ev["summary"]["ndcg_at_10"]

    # --- Étape 2 : exécution avec le mix choisi sur les fenêtres antérieures ---
    par_fenetre, decisions = [], []
    elig_stats = []
    for w in specs:
        train_v, relevant, purchased, stock_ok, scores, profiles = cache[w.index]
        mix, detail = choose_mix_from_previous_windows(mix_perf, w.index)

        recs, sources = {}, {}
        recs_v1_only = {}
        for client in relevant:
            cands = [p for p in all_products if stock_ok.get(p, False) and p not in purchased.get(client, set())]
            v1_rank = sorted(cands, key=lambda p: scores.get(p, 0.0), reverse=True)[:K]
            top, source = recommend_r3(client, profiles, v1_rank, scores, produit_categorie, cands, mix, K)
            recs[client] = top
            sources[client] = source
            recs_v1_only[client] = v1_rank

        seg = _segments(train_v, relevant)
        ev = evaluate_recommendations(recs, relevant, produit_categorie, set(all_products), k_list=[5, 10])
        ev_v1 = evaluate_recommendations(recs_v1_only, relevant, produit_categorie, set(all_products), k_list=[5, 10])

        # Sous-groupe personnalisable : la comparaison qui compte pour R4
        perso_clients = {c for c, s in sources.items() if s == "personnalise"}
        sub_rel = {c: r for c, r in relevant.items() if c in perso_clients}
        ev_sub_r3 = evaluate_recommendations({c: recs[c] for c in sub_rel}, sub_rel, produit_categorie, set(all_products), k_list=[5, 10])["summary"] if sub_rel else {}
        ev_sub_v1 = evaluate_recommendations({c: recs_v1_only[c] for c in sub_rel}, sub_rel, produit_categorie, set(all_products), k_list=[5, 10])["summary"] if sub_rel else {}

        seg_r3, seg_v1 = {}, {}
        for name in ("actif", "peu_actif", "cold_start"):
            sub = {c: r for c, r in relevant.items() if seg.get(c) == name}
            if sub:
                seg_r3[name] = evaluate_recommendations({c: recs[c] for c in sub}, sub, produit_categorie, set(all_products), k_list=[5, 10])["summary"]
                seg_v1[name] = evaluate_recommendations({c: recs_v1_only[c] for c in sub}, sub, produit_categorie, set(all_products), k_list=[5, 10])["summary"]

        n_elig = len(perso_clients)
        eligibles_profiles = [p for c, p in profiles.items() if p.eligible]
        raisons = {}
        for p in profiles.values():
            if not p.eligible:
                raisons[p.raison_non_eligible] = raisons.get(p.raison_non_eligible, 0) + 1

        n_clients_train = train_v["client_key"].nunique()
        n_pairs = train_v[["client_key", "produit_key"]].drop_duplicates().shape[0]
        sparsite = 1 - n_pairs / max(n_clients_train * len(all_products), 1)

        elig_stats.append({
            "fenetre": w.index,
            "n_clients_evaluables": len(relevant),
            "n_clients_personnalises": n_elig,
            "part_clients_personnalises": n_elig / max(len(relevant), 1),
            "n_achats_moyen_eligibles": float(np.mean([p.n_achats for p in eligibles_profiles])) if eligibles_profiles else 0.0,
            "n_categories_moyen_eligibles": float(np.mean([p.n_categories for p in eligibles_profiles])) if eligibles_profiles else 0.0,
            "sparsite_matrice": sparsite,
            "raisons_non_eligibilite": raisons,
        })

        n_doublons = sum(len(t) - len(set(t)) for t in recs.values())
        n_ineligibles = sum(
            1 for c, t in recs.items() for p in t
            if not stock_ok.get(p, False) or p in purchased.get(c, set())
        )

        par_fenetre.append({
            "fenetre": w.index, "mix": mix,
            "summary_r3": ev["summary"], "summary_v1_recalcule": ev_v1["summary"],
            "sous_groupe_personnalisable": {"r3": ev_sub_r3, "v1": ev_sub_v1, "n_clients": len(sub_rel)},
            "segments_r3": seg_r3, "segments_v1": seg_v1,
            "n_doublons": n_doublons, "n_ineligibles": n_ineligibles,
        })
        decisions.append({"fenetre": w.index, "mix": mix, **detail})

    # --- Porte stricte -----------------------------------------------------
    moy_r3 = {m: float(np.mean([r["summary_r3"][m] for r in par_fenetre]))
              for m in ("recall_at_10", "ndcg_at_10", "catalog_coverage", "recall_at_5", "ndcg_at_5")}
    moy_v1 = {m: float(np.mean([r["summary_v1_recalcule"][m] for r in par_fenetre]))
              for m in ("recall_at_10", "ndcg_at_10", "catalog_coverage", "recall_at_5", "ndcg_at_5")}

    peu_actifs_r3 = [r["segments_r3"].get("peu_actif", {}).get("ndcg_at_10") for r in par_fenetre]
    peu_actifs_v1 = [r["segments_v1"].get("peu_actif", {}).get("ndcg_at_10") for r in par_fenetre]
    peu_actifs_r3 = [x for x in peu_actifs_r3 if x is not None]
    peu_actifs_v1 = [x for x in peu_actifs_v1 if x is not None]
    recul_peu_actifs = (
        (float(np.mean(peu_actifs_v1)) - float(np.mean(peu_actifs_r3))) / float(np.mean(peu_actifs_v1))
        if peu_actifs_v1 and float(np.mean(peu_actifs_v1)) > 0 else 1.0
    )

    porte = {
        "ndcg_at_10_au_moins_egal_v1": {
            "r3": moy_r3["ndcg_at_10"], "v1": moy_v1["ndcg_at_10"],
            "ok": moy_r3["ndcg_at_10"] >= moy_v1["ndcg_at_10"],
        },
        "recall_at_10_au_moins_egal_v1": {
            "r3": moy_r3["recall_at_10"], "v1": moy_v1["recall_at_10"],
            "ok": moy_r3["recall_at_10"] >= moy_v1["recall_at_10"],
        },
        "couverture_superieure_v1": {
            "r3": moy_r3["catalog_coverage"], "v1": moy_v1["catalog_coverage"],
            "ok": moy_r3["catalog_coverage"] > moy_v1["catalog_coverage"],
        },
        "recul_peu_actifs_max_5pct": {
            "valeur": recul_peu_actifs, "seuil": 0.05, "ok": recul_peu_actifs <= 0.05,
        },
    }
    porte_franchie = all(c["ok"] for c in porte.values())

    # --- Sous-groupe personnalisable : R3 bat-il la V1 là où il agit ? -----
    sub_r3 = [r["sous_groupe_personnalisable"]["r3"].get("ndcg_at_10") for r in par_fenetre]
    sub_v1 = [r["sous_groupe_personnalisable"]["v1"].get("ndcg_at_10") for r in par_fenetre]
    sub_r3 = [x for x in sub_r3 if x is not None]
    sub_v1 = [x for x in sub_v1 if x is not None]
    signal_sous_groupe = bool(sub_r3 and sub_v1 and float(np.mean(sub_r3)) > float(np.mean(sub_v1)))

    statut = "pilot_passed" if porte_franchie else "experiment_not_retained"
    raison = "gate_passed" if porte_franchie else "relevance_not_improved"

    payload = {
        "candidat": "R3_personnalisation_categorie",
        "etape": "pilote_fenetres_1_et_2",
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "status": statut, "reason": raison,
        "seuils_eligibilite_fixes_a_priori": {
            "min_achats": MIN_ACHATS, "min_categories": MIN_CATEGORIES,
            "part_min_dominantes": PART_MIN_DOMINANTES,
        },
        "mixes_compares": MIXES, "mix_defaut": MIX_DEFAUT,
        "porte": porte, "porte_franchie": porte_franchie,
        "moyennes_r3": moy_r3, "moyennes_v1_recalcule": moy_v1,
        "reference_v1_globale_4_fenetres": v1_ref.to_dict(),
        "par_fenetre": par_fenetre, "decisions_mix": decisions,
        "statistiques_eligibilite": elig_stats,
        "signal_sous_groupe_personnalisable": signal_sous_groupe,
        "sous_groupe_ndcg": {"r3": sub_r3, "v1": sub_v1},
        "decision_r4": (
            "lancer_r4" if signal_sous_groupe and porte_franchie else "not_launched"
        ),
        "raison_r4": (
            "signal_present" if (signal_sous_groupe and porte_franchie) else "no_personalization_signal_in_R3"
        ),
        "cout_calcul": {"duree_totale_s": round(time.time() - t0, 2), "memoire_rss_mb": current_rss_mb()},
    }

    V2_EVAL.mkdir(parents=True, exist_ok=True)
    (V2_EVAL / "R3_pilote_metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log_event({"type": "fin", "candidat": "R3_pilote", "statut": statut,
               "duree_totale_s": payload["cout_calcul"]["duree_totale_s"]})
    _write_report(payload)
    print(f"R3 : {statut} ({raison}) — porte franchie : {porte_franchie} | "
          f"signal sous-groupe : {signal_sous_groupe} | R4 : {payload['decision_r4']}")


def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _write_report(p: dict) -> None:
    lines = [
        "# 10 — Candidat R3 : personnalisation par catégorie (pilote fenêtres 1-2)",
        "",
        f"_Généré le {p['genere_le']}._",
        "",
        f"**Statut : `{p['status']}` — raison : `{p['reason']}`**",
        "",
        "## 1. Seuils d'éligibilité (fixés avant l'évaluation)",
        "",
        f"- Minimum {p['seuils_eligibilite_fixes_a_priori']['min_achats']} achats historiques",
        f"- Minimum {p['seuils_eligibilite_fixes_a_priori']['min_categories']} catégories observées",
        f"- Au moins {p['seuils_eligibilite_fixes_a_priori']['part_min_dominantes']:.0%} des achats dans "
        "les catégories dominantes",
        "",
        "Tout client ne remplissant pas ces conditions reçoit **automatiquement la liste V1**.",
        "",
        "## 2. Population personnalisable",
        "",
        "| Fenêtre | Clients évaluables | Personnalisés | Part | Achats moyens (éligibles) | Catégories moyennes | Sparsité |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for e in p["statistiques_eligibilite"]:
        lines.append(
            f"| {e['fenetre']} | {e['n_clients_evaluables']:,} | {e['n_clients_personnalises']:,} | "
            f"{e['part_clients_personnalises']:.1%} | {_fmt(e['n_achats_moyen_eligibles'], 1)} | "
            f"{_fmt(e['n_categories_moyen_eligibles'], 1)} | {_fmt(e['sparsite_matrice'])} |"
        )

    lines += ["", "Raisons de non-éligibilité :", ""]
    for e in p["statistiques_eligibilite"]:
        lines.append(f"- Fenêtre {e['fenetre']} : {e['raisons_non_eligibilite']}")

    lines += [
        "",
        "## 3. Résultats du pilote",
        "",
        "| Métrique | V1 (recalculée sur F1-F2) | R3 | Écart |",
        "|---|---:|---:|---:|",
    ]
    for m, label in [("recall_at_10", "Recall@10"), ("ndcg_at_10", "NDCG@10"),
                     ("recall_at_5", "Recall@5"), ("ndcg_at_5", "NDCG@5"),
                     ("catalog_coverage", "Couverture catalogue")]:
        v, r = p["moyennes_v1_recalcule"][m], p["moyennes_r3"][m]
        ecart = (r - v) / v if v else float("nan")
        lines.append(f"| {label} | {_fmt(v)} | {_fmt(r)} | {ecart:+.2%} |")

    lines += [
        "",
        "## 4. Porte stricte",
        "",
        "| Critère | V1 | R3 | Satisfait ? |",
        "|---|---:|---:|:---:|",
    ]
    for name, c in p["porte"].items():
        if "r3" in c:
            lines.append(f"| `{name}` | {_fmt(c['v1'])} | {_fmt(c['r3'])} | {'✅' if c['ok'] else '❌'} |")
        else:
            lines.append(f"| `{name}` | seuil {_fmt(c['seuil'])} | {_fmt(c['valeur'])} | {'✅' if c['ok'] else '❌'} |")

    lines += [
        "",
        f"**Porte franchie : {'oui' if p['porte_franchie'] else 'non'}**",
        "",
        "## 5. Le test qui compte vraiment : le sous-groupe personnalisable",
        "",
        "Comparer R3 à la V1 sur l'ensemble des clients dilue l'effet, puisque la majorité reçoit de "
        "toute façon la liste V1. La question utile est : **là où la personnalisation s'applique "
        "réellement, fait-elle mieux ?**",
        "",
        "| Fenêtre | Clients personnalisés | NDCG@10 V1 | NDCG@10 R3 | Écart |",
        "|---:|---:|---:|---:|---:|",
    ]
    for r in p["par_fenetre"]:
        sg = r["sous_groupe_personnalisable"]
        v = sg["v1"].get("ndcg_at_10")
        r3v = sg["r3"].get("ndcg_at_10")
        ecart = (r3v - v) / v if (v and r3v is not None) else float("nan")
        lines.append(
            f"| {r['fenetre']} | {sg['n_clients']:,} | {_fmt(v)} | {_fmt(r3v)} | "
            f"{ecart:+.2%} |" if v else f"| {r['fenetre']} | {sg['n_clients']:,} | n/a | n/a | n/a |"
        )

    lines += [
        "",
        f"**Signal de personnalisation sur le sous-groupe : "
        f"{'OUI' if p['signal_sous_groupe_personnalisable'] else 'NON'}**",
        "",
        "## 6. Mix retenu par fenêtre (choisi sur les fenêtres antérieures)",
        "",
        "| Fenêtre | Mix | Source | Fenêtres utilisées |",
        "|---:|---|---|---|",
    ]
    for d in p["decisions_mix"]:
        lines.append(f"| {d['fenetre']} | `{d['mix']}` | `{d['source']}` | {d.get('fenetres_utilisees', [])} |")

    lines += [
        "",
        "## 7. Contrôles durs",
        "",
        "| Fenêtre | Doublons Top-10 | Produits inéligibles |",
        "|---:|---:|---:|",
    ]
    for r in p["par_fenetre"]:
        lines.append(f"| {r['fenetre']} | {r['n_doublons']} | {r['n_ineligibles']} |")

    lines += [
        "",
        "## 8. Décision sur R4",
        "",
        f"**R4 : `{p['decision_r4']}` — raison : `{p['raison_r4']}`**",
        "",
    ]
    if p["decision_r4"] == "not_launched":
        lines += [
            "R4 était un routage « clients avec historique suffisant → modèle personnalisé, autres → "
            "popularité globale ». Or R3 vient de tester exactement ce routage, avec une personnalisation "
            "légère — et il **n'apporte pas de signal** sur le sous-groupe qu'il cible. Lancer un "
            "collaboratif plus lourd sur la même population, avec la même sparsité et le même volume "
            "d'historique, n'a pas de fondement : le problème n'est pas la sophistication du modèle, "
            "c'est l'absence de signal exploitable dans les données disponibles.",
            "",
        ]

    lines += [
        f"- Durée : **{p['cout_calcul']['duree_totale_s']} s** · mémoire {p['cout_calcul']['memoire_rss_mb']} Mo",
        "",
        "## 9. Garanties",
        "",
        "- Profils clients calculés **sur le train de chaque fenêtre uniquement**.",
        "- Mix choisi **uniquement sur les fenêtres antérieures** (F1 utilise le mix par défaut).",
        "- Repli V1 automatique pour tout client non éligible et pour le cold-start.",
        "- Aucun artefact V1 modifié.",
        "",
    ]
    V2_REPORTS.mkdir(parents=True, exist_ok=True)
    (V2_REPORTS / "10_recsys_R3_pilote.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
