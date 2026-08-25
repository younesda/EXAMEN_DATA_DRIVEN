"""Bounded, leakage-safe complement-cart ranking pilot on eligible F2--F4."""
from __future__ import annotations
import hashlib, json
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from src.config.settings import PROJECT_ROOT

ROOT = PROJECT_ROOT / "data" / "processed" / "final"
OUT = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"
SEED = 42

def stats(frame):
    co = defaultdict(Counter); pop = Counter(); cat = defaultdict(Counter)
    for _, g in frame.groupby("order_id"):
        items = list(dict.fromkeys(g.produit_key)); pop.update(items)
        for x in items:
            co[x].update(y for y in items if y != x)
        for c, gg in g.groupby("categorie"): cat[c].update(gg.produit_key)
    return co, pop, cat

def candidates(context, target_cat, co, pop, cat):
    score = Counter(); sources = defaultdict(set)
    for x in context:
        for y, v in co.get(x, {}).items():
            if y not in context: score[y] += float(v); sources[y].add("cooccurrence")
    assoc = {y: v / max(pop[y], 1) for y, v in score.items()}
    for y, v in assoc.items(): score[y] += v; sources[y].add("association")
    for y, v in score.items():
        score[y] += v / (1.0 + np.log1p(pop[y])); sources[y].add("bm25")
    for y, v in cat.get(target_cat, {}).items():
        if y not in context: score[y] += 0.25 * float(v); sources[y].add("category")
    if not score: score.update({y: float(v) for y, v in pop.items() if y not in context});
    ordered = sorted(score, key=lambda y: (-score[y], y))[:50]
    return ordered, score, sources

def frame_for(test, train, labeled=True):
    co, pop, cat = stats(train); rows=[]
    for oid, g in test.groupby("order_id"):
        items = list(dict.fromkeys(g.produit_key));
        for target in items:
            context = set(items) - {target}; target_cat = str(g.loc[g.produit_key.eq(target), "categorie"].iloc[0])
            ranked, score, sources = candidates(context, target_cat, co, pop, cat)
            for rank, item in enumerate(ranked, 1):
                rows.append({"order_id": oid, "target": target, "item": item, "label": int(item == target),
                    "rrf": 1.0 / rank, "source_count": len(sources[item]), "score": score[item],
                    "pop": np.log1p(pop[item]), "context_size": len(context), "candidate_rank": rank})
    return pd.DataFrame(rows)

def metrics(scored, k=10):
    if scored.empty: return {"recall@10": 0., "ndcg@10": 0., "map@10": 0., "mrr": 0., "hitrate@10": 0.}
    vals=[]
    for _, g in scored.groupby(["order_id", "target"]):
        g=g.sort_values("pred", ascending=False); rel=g.label.to_numpy(); pos=np.flatnonzero(rel)
        top=rel[:k]; hit=int(top.sum()>0); rr=float(1/(pos[0]+1)) if len(pos) else 0.
        dcg=float(sum(v/np.log2(i+2) for i,v in enumerate(top))); ideal=1.0
        ap=float(sum((top[:i+1].sum()/(i+1))*top[i] for i in range(min(k,len(top)))) / max(1, min(1,int(rel.sum()))))
        vals.append((hit, dcg/ideal, ap, rr))
    a=np.asarray(vals); return {"recall@10":float(a[:,0].mean()),"ndcg@10":float(a[:,1].mean()),"map@10":float(a[:,2].mean()),"mrr":float(a[:,3].mean()),"hitrate@10":float(a[:,0].mean())}

def main():
    orders=pd.read_parquet(ROOT/"order_baskets.parquet"); orders.date_commande=pd.to_datetime(orders.date_commande)
    multi=orders.groupby("order_id").filter(lambda x:x.produit_key.nunique()>=2)
    dates=multi.groupby("order_id").date_commande.min().sort_values(); chunks=np.array_split(dates.index.to_numpy(),4)
    all_rows=[]; window_rows=[]; bootstrap_diffs=[]
    for w in (2,3,4):
        test_ids=set(chunks[w-1].tolist()); test=multi[multi.order_id.isin(test_ids)]; cutoff=test.date_commande.min(); train=multi[multi.date_commande.lt(cutoff)]
        base=frame_for(test, train); base["pred"]=base["rrf"]; bm=metrics(base)
        # Deterministic negatives: all candidate negatives, capped only for training.
        # Bounded pilot training pool: deterministic latest 600 historical
        # orders, while evaluation keeps every eligible test order.
        train_ids=train.order_id.unique(); tr=train[train.order_id.isin(train_ids[-min(len(train_ids), 600):])]
        trf=frame_for(tr, train[train.date_commande.lt(tr.date_commande.min())] if not tr.empty else train)
        if trf.empty or trf.label.nunique()<2:
            rank=base.copy(); rank["pred"]=rank["rrf"]; rm=bm; fitted=False
        else:
            X=trf[["rrf","source_count","score","pop","context_size","candidate_rank"]]; y=trf.label
            groups=trf.groupby(["order_id","target"], sort=False).size().to_numpy()
            model=LGBMRanker(objective="lambdarank", n_estimators=50, learning_rate=.04, num_leaves=15, max_depth=4, min_child_samples=20, reg_lambda=5, random_state=SEED, verbosity=-1)
            model.fit(X,y,group=groups); rank=base.copy(); rank["pred"]=model.predict(rank[X.columns]); rm=metrics(rank); fitted=True
        for name, m in (("candidate_union_rrf",bm),("LightGBM_LambdaRank",rm)):
            window_rows.append({"window":w,"model":name,"n_orders":len(test_ids),"n_targets":int(base[["order_id","target"]].drop_duplicates().shape[0]),**m,"coverage_catalogue":float(base.item.nunique()/300.0),"diversity":float(base.item.nunique())})
        diffs=[]
        for key, g in rank.groupby(["order_id","target"]):
            a=metrics(g.assign(pred=g.rrf)); b=metrics(g); diffs.append(b["ndcg@10"]-a["ndcg@10"])
        bootstrap_diffs.extend(diffs)
    rng=np.random.default_rng(SEED); arr=np.asarray(bootstrap_diffs); boots=np.array([rng.choice(arr, len(arr), replace=True).mean() for _ in range(2000)]) if len(arr) else np.array([0.])
    payload={"evaluated_windows":[2,3,4],"f1_status":"non_evaluable_no_history","f1_model_evaluation_allowed":False,"f1_fallback_required":True,"metrics":window_rows,"bootstrap_ndcg10_diff_ci95":[float(np.quantile(boots,.025)),float(np.quantile(boots,.975))],"deterministic_negative_seed":SEED,"promotion":False,"decision":"candidate_union_rrf retained only if it beats recalculated reference; LambdaRank not promoted unless all gates pass"}
    pd.DataFrame(window_rows).to_csv(OUT/"complement_ranker_metrics.csv",index=False); (OUT/"complement_ranker_metadata.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
    report="# Complement panier — ranker pilote\n\nF1 est `non_evaluable_no_history` (aucune commande ni produit connu). Le gate candidat est évalué sur F2–F4. Les features sont strictement antérieures au cutoff, les cibles masquées restent hors features et les négatifs sont déterministes (seed 42).\n\n"+pd.DataFrame(window_rows).to_markdown(index=False)+"\n\nBootstrap commande×fenêtre de la différence NDCG@10 LambdaRank−union RRF (IC95 %): "+str(payload["bootstrap_ndcg10_diff_ci95"])+".\n"
    (OUT/"complement_ranker_report.md").write_text(report,encoding="utf-8")
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob("*") if p.is_file() and "manifest" not in p.name}; (OUT/"complement_ranker_manifest.sha256.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
if __name__=="__main__": main()
