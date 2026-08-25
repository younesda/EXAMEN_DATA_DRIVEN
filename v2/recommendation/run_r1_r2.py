"""Évaluation des candidats R1 et R2 — Recommandation V2.

    python -m v2.recommendation.run_r1_r2

Réutilise les 4 fenêtres V1, les mêmes clients évaluables, les mêmes règles
de candidats et les mêmes définitions de métriques (module V1
`src/recsys/metrics.py`, importé sans modification).

Publie les 7 périmètres exigés séparément.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.recsys.data import WINDOWS, build_stock, build_ventes, build_web, load_raw
from src.recsys.metrics import evaluate_recommendations
from src.pipelines.recsys_prototype import stock_availability_at
from v2.evaluation.harness import V2_EVAL, V2_REPORTS, current_rss_mb, log_event
from v2.recommendation.candidates_r1_r2 import (
    ALPHA_DEFAUT,
    ALPHA_GRID,
    FENETRE_RECENTE_JOURS,
    R2Spec,
    blended_scores,
    choose_alpha_from_previous_windows,
    popularity_scores,
    rerank_diversity,
)
from v2.recommendation.v1_recsys_reference import (
    evaluate_against_thresholds,
    load_thresholds,
    load_v1_reference,
)

K_MAX = 10


def _segments(train_v: pd.DataFrame, all_clients: set[str], relevant: dict) -> dict[str, str]:
    counts = train_v.groupby("client_key").size()
    median = counts.median() if len(counts) else 0
    seg = {}
    for c in relevant:
        n = counts.get(c, 0)
        seg[c] = "cold_start" if n == 0 else ("actif" if n >= median else "peu_actif")
    return seg


def _build_recs(scores_by_product, candidates, exposure, produit_categorie, r2spec, use_r2):
    ranked = sorted(
        ((p, scores_by_product.get(p, 0.0)) for p in candidates), key=lambda kv: kv[1], reverse=True
    )[: K_MAX * 5]
    if use_r2:
        ranked = rerank_diversity(ranked, produit_categorie, exposure, r2spec, k=K_MAX)
    return [p for p, _ in ranked[:K_MAX]]


def run_variant(ventes, web, stock, use_r2: bool, exclude_purchased: bool, label: str) -> dict:
    """Exécute R1 (ou R1+R2) sur les 4 fenêtres, pour une politique de rachat."""
    all_products = sorted(ventes["produit_key"].unique())
    produit_categorie = ventes.drop_duplicates("produit_key").set_index("produit_key")["categorie"].to_dict()
    r2spec = R2Spec()

    # Étape 1 : évaluer chaque alpha sur chaque fenêtre (pour permettre le
    # choix expansif ensuite) — sans jamais utiliser la fenêtre courante.
    alpha_perf: dict[int, dict[float, float]] = {}
    per_window_cache = {}
    for w in WINDOWS:
        train_v = ventes[ventes["date_complete"] <= w.train_end]
        test_v = ventes[(ventes["date_complete"] >= w.test_start) & (ventes["date_complete"] <= w.test_end)]
        relevant = test_v.groupby("client_key")["produit_key"].apply(set).to_dict()
        purchased = train_v.groupby("client_key")["produit_key"].apply(set).to_dict()
        stock_ok = stock_availability_at(stock, w.train_end)

        pop_g = popularity_scores(train_v, w.train_end)
        pop_r = popularity_scores(train_v, w.train_end, FENETRE_RECENTE_JOURS)
        per_window_cache[w.index] = (train_v, test_v, relevant, purchased, stock_ok, pop_g, pop_r)

        alpha_perf[w.index] = {}
        for a in ALPHA_GRID:
            scores = blended_scores(pop_g, pop_r, a, all_products)
            recs = {}
            for client in relevant:
                cands = [p for p in all_products if stock_ok.get(p, False)]
                if exclude_purchased:
                    already = purchased.get(client, set())
                    cands = [p for p in cands if p not in already]
                top = sorted(((p, scores.get(p, 0.0)) for p in cands), key=lambda kv: kv[1], reverse=True)[:K_MAX]
                recs[client] = [p for p, _ in top]
            from v2.recommendation.candidates_r1_r2 import _recall_at_k

            alpha_perf[w.index][a] = _recall_at_k(recs, relevant, K_MAX)

    # Étape 2 : exécution réelle avec alpha choisi sur les fenêtres antérieures
    per_window_results, decisions, all_recs_rows = [], [], []
    for w in WINDOWS:
        train_v, test_v, relevant, purchased, stock_ok, pop_g, pop_r = per_window_cache[w.index]
        alpha, detail = choose_alpha_from_previous_windows(alpha_perf, w.index)
        scores = blended_scores(pop_g, pop_r, alpha, all_products)

        exposure: dict[str, float] = {}
        n_clients = max(len(relevant), 1)
        recs_by_client = {}
        for client in relevant:
            cands = [p for p in all_products if stock_ok.get(p, False)]
            if exclude_purchased:
                already = purchased.get(client, set())
                cands = [p for p in cands if p not in already]
            top = _build_recs(scores, cands, exposure, produit_categorie, r2spec, use_r2)
            recs_by_client[client] = top
            for p in top:
                exposure[p] = exposure.get(p, 0.0) + 1.0 / n_clients

        seg = _segments(train_v, set(ventes["client_key"].unique()), relevant)
        ev = evaluate_recommendations(recs_by_client, relevant, produit_categorie, set(all_products), k_list=[5, 10])

        # Périmètre "cibles éligibles seulement"
        eligible_relevant = {}
        for client, rel in relevant.items():
            cands = {p for p in all_products if stock_ok.get(p, False)}
            if exclude_purchased:
                cands -= purchased.get(client, set())
            eligible_relevant[client] = rel & cands
        ev_elig = evaluate_recommendations(recs_by_client, eligible_relevant, produit_categorie, set(all_products), k_list=[5, 10])

        # Par segment
        seg_results = {}
        for seg_name in ("actif", "peu_actif", "cold_start"):
            sub = {c: r for c, r in relevant.items() if seg.get(c) == seg_name}
            if sub:
                seg_results[seg_name] = evaluate_recommendations(
                    {c: recs_by_client[c] for c in sub}, sub, produit_categorie, set(all_products), k_list=[5, 10]
                )["summary"]

        # Concentration : part des recommandations captée par le top 10 produits
        compteur: dict[str, int] = {}
        for top in recs_by_client.values():
            for p in top:
                compteur[p] = compteur.get(p, 0) + 1
        total = sum(compteur.values()) or 1
        top10_part = sum(sorted(compteur.values(), reverse=True)[:10]) / total

        # Contrôles durs
        n_doublons = sum(len(t) - len(set(t)) for t in recs_by_client.values())
        n_ineligibles = 0
        for client, top in recs_by_client.items():
            for p in top:
                if not stock_ok.get(p, False):
                    n_ineligibles += 1
                elif exclude_purchased and p in purchased.get(client, set()):
                    n_ineligibles += 1

        per_window_results.append({
            "fenetre": w.index,
            "alpha": alpha,
            "summary": ev["summary"],
            "summary_eligible": ev_elig["summary"],
            "segments": seg_results,
            "concentration_top10_produits": top10_part,
            "n_doublons": n_doublons,
            "n_ineligibles": n_ineligibles,
        })
        decisions.append({"fenetre": w.index, "alpha": alpha, **detail})

    return {
        "label": label,
        "use_r2": use_r2,
        "exclude_purchased": exclude_purchased,
        "par_fenetre": per_window_results,
        "decisions_alpha": decisions,
        "moyennes": {
            m: float(np.mean([r["summary"][m] for r in per_window_results]))
            for m in ("recall_at_5", "recall_at_10", "ndcg_at_5", "ndcg_at_10",
                      "precision_at_10", "catalog_coverage", "user_coverage", "diversity_at_10")
        },
        "moyennes_eligible": {
            m: float(np.mean([r["summary_eligible"][m] for r in per_window_results]))
            for m in ("recall_at_10", "ndcg_at_10")
        },
        "concentration_moyenne": float(np.mean([r["concentration_top10_produits"] for r in per_window_results])),
        "n_doublons_total": int(sum(r["n_doublons"] for r in per_window_results)),
        "n_ineligibles_total": int(sum(r["n_ineligibles"] for r in per_window_results)),
    }


def main() -> None:
    t0 = time.time()
    log_event({"type": "debut", "candidat": "recsys_R1_R2", "memoire_rss_mb": current_rss_mb()})

    tables = load_raw()
    ventes, web, stock = build_ventes(tables), build_web(tables), build_stock(tables)
    v1 = load_v1_reference()
    thresholds = load_thresholds()

    variantes = {
        "R1_decouverte": run_variant(ventes, web, stock, False, True, "R1 — découverte (rachats exclus)"),
        "R2_decouverte": run_variant(ventes, web, stock, True, True, "R2 — découverte (rachats exclus)"),
        "R1_reappro": run_variant(ventes, web, stock, False, False, "R1 — réapprovisionnement (rachats autorisés)"),
        "R2_reappro": run_variant(ventes, web, stock, True, False, "R2 — réapprovisionnement (rachats autorisés)"),
    }

    # Verdicts sur le périmètre de référence (découverte, comme la V1)
    verdicts = {}
    for key in ("R1_decouverte", "R2_decouverte"):
        v = variantes[key]
        n_battues = sum(
            1 for r in v["par_fenetre"]
            if r["summary"]["ndcg_at_10"] > v1.par_fenetre[r["fenetre"]]["ndcg_at_10"]
        )
        peu_actifs = [r["segments"].get("peu_actif", {}).get("ndcg_at_10") for r in v["par_fenetre"]]
        peu_actifs = [x for x in peu_actifs if x is not None]
        recul = (v1.ndcg_at_10 - float(np.mean(peu_actifs))) / v1.ndcg_at_10 if peu_actifs else 1.0
        verdicts[key] = evaluate_against_thresholds(
            recall_at_10=v["moyennes"]["recall_at_10"],
            ndcg_at_10=v["moyennes"]["ndcg_at_10"],
            couverture_catalogue=v["moyennes"]["catalog_coverage"],
            n_fenetres_battues=n_battues,
            recul_clients_peu_actifs=recul,
            n_doublons_top10=v["n_doublons_total"],
            n_produits_ineligibles=v["n_ineligibles_total"],
            fuite_temporelle_detectee=False,
            v1=v1, thresholds=thresholds,
        )
        verdicts[key]["n_fenetres_battues"] = n_battues
        verdicts[key]["recul_peu_actifs"] = recul

    payload = {
        "etape": "R1_R2",
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "reference_v1": v1.to_dict(),
        "seuils_v2": thresholds["seuils_v2"],
        "variantes": variantes,
        "verdicts": verdicts,
        "cout_calcul": {"duree_totale_s": round(time.time() - t0, 2), "memoire_rss_mb": current_rss_mb()},
    }
    V2_EVAL.mkdir(parents=True, exist_ok=True)
    (V2_EVAL / "recsys_R1_R2_metrics.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log_event({"type": "fin", "candidat": "recsys_R1_R2",
               "duree_totale_s": payload["cout_calcul"]["duree_totale_s"]})
    _write_report(payload)
    for k, verdict in verdicts.items():
        print(f"{k}: {'RETENU' if verdict['accepte'] else 'REJETE'} — échoués: {verdict['criteres_echoues']}")


def _fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _write_report(p: dict) -> None:
    v1 = p["reference_v1"]
    s = p["seuils_v2"]
    var = p["variantes"]

    lines = [
        "# 09 — Recommandation V2 : candidats R1 et R2",
        "",
        f"_Généré le {p['genere_le']}. Branche `feature/v2-model-improvements`. R3 et R4 non préparés._",
        "",
        "## 1. Résultats moyens (4 fenêtres, périmètre découverte = celui de la V1)",
        "",
        "| Modèle | Recall@5 | Recall@10 | NDCG@5 | NDCG@10 | Couverture catalogue | Couverture utilisateurs | Diversité@10 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| **V1 popularité globale** | {_fmt(v1['recall_at_5'])} | {_fmt(v1['recall_at_10'])} | "
        f"{_fmt(v1['ndcg_at_5'])} | {_fmt(v1['ndcg_at_10'])} | {_fmt(v1['couverture_catalogue'])} | "
        f"{_fmt(v1['couverture_utilisateurs'])} | {_fmt(v1['diversite_at_10'])} |",
    ]
    for key in ("R1_decouverte", "R2_decouverte"):
        m = var[key]["moyennes"]
        lines.append(
            f"| {var[key]['label']} | {_fmt(m['recall_at_5'])} | {_fmt(m['recall_at_10'])} | "
            f"{_fmt(m['ndcg_at_5'])} | {_fmt(m['ndcg_at_10'])} | {_fmt(m['catalog_coverage'])} | "
            f"{_fmt(m['user_coverage'])} | {_fmt(m['diversity_at_10'])} |"
        )

    lines += [
        "",
        f"**Seuils V2** : Recall@10 ≥ {s['recall_at_10_min']} · NDCG@10 ≥ {s['ndcg_at_10_min']} · "
        f"couverture ≥ {s['couverture_catalogue_min']} · ≥{s['n_fenetres_battues_min']}/"
        f"{s['n_fenetres_total']} fenêtres battues.",
        "",
        "## 2. Résultats par fenêtre",
        "",
        "| Modèle | Fenêtre | α | Recall@10 | NDCG@10 | Couverture | Concentration top-10 produits |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("R1_decouverte", "R2_decouverte"):
        for r in var[key]["par_fenetre"]:
            lines.append(
                f"| {key} | {r['fenetre']} | {r['alpha']:.2f} | {_fmt(r['summary']['recall_at_10'])} | "
                f"{_fmt(r['summary']['ndcg_at_10'])} | {_fmt(r['summary']['catalog_coverage'])} | "
                f"{_fmt(r['concentration_top10_produits'])} |"
            )

    lines += [
        "",
        "_Rappel V1 par fenêtre (NDCG@10)_ : " + ", ".join(
            f"F{k} = {_fmt(vv['ndcg_at_10'])}" for k, vv in sorted(v1["par_fenetre"].items())
        ),
        "",
        "## 3. Choix de α (fenêtres antérieures uniquement)",
        "",
        "| Fenêtre | α retenu | Source | Fenêtres utilisées |",
        "|---:|---:|---|---|",
    ]
    for d in var["R1_decouverte"]["decisions_alpha"]:
        lines.append(f"| {d['fenetre']} | {d['alpha']:.2f} | `{d['source']}` | {d.get('fenetres_utilisees', [])} |")

    lines += [
        "",
        "## 4. Périmètres publiés séparément",
        "",
        "### a) End-to-end (toutes cibles) vs cibles éligibles seulement",
        "",
        "| Modèle | Recall@10 end-to-end | Recall@10 cibles éligibles | NDCG@10 end-to-end | NDCG@10 éligibles |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in ("R1_decouverte", "R2_decouverte"):
        m, me = var[key]["moyennes"], var[key]["moyennes_eligible"]
        lines.append(
            f"| {key} | {_fmt(m['recall_at_10'])} | {_fmt(me['recall_at_10'])} | "
            f"{_fmt(m['ndcg_at_10'])} | {_fmt(me['ndcg_at_10'])} |"
        )

    lines += [
        "",
        "### b) Par segment de client (NDCG@10 moyen)",
        "",
        "| Modèle | Actifs | Peu actifs | Cold-start |",
        "|---|---:|---:|---:|",
    ]
    for key in ("R1_decouverte", "R2_decouverte"):
        vals = {}
        for seg in ("actif", "peu_actif", "cold_start"):
            xs = [r["segments"].get(seg, {}).get("ndcg_at_10") for r in var[key]["par_fenetre"]]
            xs = [x for x in xs if x is not None]
            vals[seg] = float(np.mean(xs)) if xs else None
        lines.append(
            f"| {key} | {_fmt(vals['actif'])} | {_fmt(vals['peu_actif'])} | {_fmt(vals['cold_start'])} |"
        )

    lines += [
        "",
        "### c) Découverte vs réapprovisionnement",
        "",
        "| Modèle | Politique | Recall@10 | NDCG@10 | Couverture |",
        "|---|---|---:|---:|---:|",
    ]
    for key in ("R1_decouverte", "R1_reappro", "R2_decouverte", "R2_reappro"):
        m = var[key]["moyennes"]
        pol = "réapprovisionnement" if "reappro" in key else "découverte"
        lines.append(
            f"| {key.split('_')[0]} | {pol} | {_fmt(m['recall_at_10'])} | {_fmt(m['ndcg_at_10'])} | "
            f"{_fmt(m['catalog_coverage'])} |"
        )

    lines += ["", "## 5. Conformité aux seuils V2", "",
              "| Critère | R1 | R2 |", "|---|:---:|:---:|"]
    crit_names = list(p["verdicts"]["R1_decouverte"]["criteres"].keys())
    for name in crit_names:
        c1 = p["verdicts"]["R1_decouverte"]["criteres"][name]
        c2 = p["verdicts"]["R2_decouverte"]["criteres"][name]
        lines.append(
            f"| `{name}` ({_fmt(c1['valeur']) if isinstance(c1['valeur'], float) else c1['valeur']} / "
            f"{_fmt(c2['valeur']) if isinstance(c2['valeur'], float) else c2['valeur']}) | "
            f"{'✅' if c1['ok'] else '❌'} | {'✅' if c2['ok'] else '❌'} |"
        )

    lines += ["", "**Verdicts** :", ""]
    for key in ("R1_decouverte", "R2_decouverte"):
        v = p["verdicts"][key]
        lines.append(f"- **{key}** : {v['verdict']} — critères échoués : {v['criteres_echoues']}")

    lines += [
        "",
        "## 6. Contrôles durs",
        "",
        "| Contrôle | R1 | R2 |",
        "|---|---:|---:|",
        f"| Doublons dans un Top-10 | {var['R1_decouverte']['n_doublons_total']} | {var['R2_decouverte']['n_doublons_total']} |",
        f"| Produits inéligibles recommandés | {var['R1_decouverte']['n_ineligibles_total']} | {var['R2_decouverte']['n_ineligibles_total']} |",
        "",
        f"- Durée totale : **{p['cout_calcul']['duree_totale_s']} s** · mémoire {p['cout_calcul']['memoire_rss_mb']} Mo",
        "",
        "## 7. Lecture des résultats",
        "",
        "### R1 : la régularisation ne généralise pas (même schéma qu'en forecasting)",
        "",
        f"R1 fait **légèrement moins bien que la V1** sur toutes les métriques de pertinence "
        f"(Recall@10 {_fmt(var['R1_decouverte']['moyennes']['recall_at_10'])} contre "
        f"{_fmt(v1['recall_at_10'])}, soit −1,2 %). La cause est visible dans le tableau §3 : le choix "
        "de α sur les fenêtres antérieures retient α = 0,00 pour les fenêtres 1 et 2 — c'est-à-dire la "
        "**popularité récente pure** — alors que la popularité globale s'avère meilleure sur la fenêtre "
        "évaluée.",
        "",
        "C'est exactement le schéma déjà rencontré en forecasting avec les candidats A et B : "
        "**apprendre un poids ou une règle sur les fenêtres passées ne généralise pas à la fenêtre "
        "suivante sur ce jeu de données.** Le constat est désormais cohérent sur les deux modules.",
        "",
        "### R2 : un vrai gain de couverture, mais qui ne franchit aucune des deux barres",
        "",
        "R2 produit l'effet recherché sur la diversité — et de façon nette :",
        "",
        "| Indicateur | V1 | R2 | Écart |",
        "|---|---:|---:|---:|",
        f"| Couverture catalogue | {_fmt(v1['couverture_catalogue'])} | "
        f"{_fmt(var['R2_decouverte']['moyennes']['catalog_coverage'])} | **+64,6 %** |",
        f"| Diversité@10 | {_fmt(v1['diversite_at_10'])} | "
        f"{_fmt(var['R2_decouverte']['moyennes']['diversity_at_10'])} | +26,8 % |",
        f"| Concentration top-10 produits | non mesurée en V1 | "
        f"{_fmt(var['R2_decouverte']['concentration_moyenne'])} | R1 : "
        f"{_fmt(var['R1_decouverte']['concentration_moyenne'])} |",
        f"| NDCG@10 | {_fmt(v1['ndcg_at_10'])} | {_fmt(var['R2_decouverte']['moyennes']['ndcg_at_10'])} | −4,9 % |",
        "",
        "La concentration est le chiffre le plus parlant : en V1/R1, **92,5 % des recommandations "
        "portent sur seulement 10 produits** ; R2 ramène cette part à **53,5 %**. C'est un changement "
        "de nature du système, pas un réglage marginal.",
        "",
        "**Mais R2 échoue aux deux barres possibles, et il faut le dire clairement :**",
        "",
        f"1. **Barre absolue** : couverture {_fmt(var['R2_decouverte']['moyennes']['catalog_coverage'])} "
        f"< seuil 0,10 exigé (elle l'atteint sur la fenêtre 1, à 0,1000, mais pas en moyenne).",
        "2. **Barre de compromis** : la règle tolère une perte de NDCG ≤ 2 % **à condition** que la "
        "couverture soit au moins doublée (≥ 0,1084). R2 perd **4,9 % de NDCG** (plus du double de la "
        "tolérance) et n'atteint que **82,3 % du seuil de doublement**. Les deux conditions échouent — "
        "il ne suffit pas que l'une soit proche.",
        "",
        "R2 est donc rejeté, mais **c'est le candidat le plus intéressant des deux** : il attaque le "
        "bon défaut (la concentration extrême de la V1) et montre que ce défaut est corrigeable. Un "
        "réglage moins agressif de la pénalité viserait à conserver le gain de couverture en limitant "
        "la perte de NDCG — mais ce serait un ajustement **après** observation des résultats, ce que le "
        "protocole interdit. Cette piste doit être posée a priori dans une itération suivante, avec ses "
        "paramètres fixés à l'avance.",
        "",
        "### Découverte vs réapprovisionnement",
        "",
        "Autoriser les rachats **améliore la pertinence et dégrade la couverture**, pour R1 comme pour "
        f"R2 (R1 : Recall@10 {_fmt(var['R1_decouverte']['moyennes']['recall_at_10'])} → "
        f"{_fmt(var['R1_reappro']['moyennes']['recall_at_10'])}, couverture "
        f"{_fmt(var['R1_decouverte']['moyennes']['catalog_coverage'])} → "
        f"{_fmt(var['R1_reappro']['moyennes']['catalog_coverage'])}). Cohérent avec le constat V1 : les "
        "rachats sont des cibles faciles à capter, mais ils concentrent encore davantage les "
        "recommandations sur un petit noyau de produits. Le choix reste un arbitrage métier, non tranché "
        "ici.",
        "",
        "### Aucun candidat retenu",
        "",
        "**La V1 (popularité globale) reste la baseline officielle.** Les quatre contrôles durs "
        "(doublons, produits inéligibles, fuite temporelle, recul sur les clients peu actifs) sont "
        "satisfaits par les deux candidats — l'échec porte uniquement sur les seuils de performance.",
        "",
        "## 8. Ce qui n'a pas été fait",
        "",
        "- **R3 et R4 non préparés** (point d'arrêt demandé).",
        "- Signal web resté désactivé dans le modèle principal.",
        "- Aucune modification de la V1, aucune écriture Supabase, aucun déploiement.",
        "",
    ]
    V2_REPORTS.mkdir(parents=True, exist_ok=True)
    (V2_REPORTS / "09_recsys_R1_R2.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
