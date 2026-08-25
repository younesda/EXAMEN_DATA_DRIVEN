import json
import numpy as np
import pandas as pd
from lightgbm import LGBMRanker
from src.config.settings import PROJECT_ROOT

OUT = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"

def score(g):
    vals=[]
    for _, x in g.groupby(["order_id","target"]):
        x=x.sort_values("pred", ascending=False); rel=x.label.to_numpy()[:10]; pos=np.flatnonzero(rel)
        vals.append((float(rel.sum()>0), float(sum(v/np.log2(i+2) for i,v in enumerate(rel))), 1/(pos[0]+1) if len(pos) else 0.0))
    a=np.asarray(vals); return {"recall@10":float(a[:,0].mean()),"ndcg@10":float(a[:,1].mean()),"mrr":float(a[:,2].mean()),"n_targets":len(a)}

d=pd.read_parquet(OUT/"complement_topk_predictions.parquet"); d=d[d.model.eq("rrf")].copy(); cols=["rank","score"]
tr=d[d.window.isin([2,3])]; te=d[d.window.eq(4)].copy(); groups=tr.groupby(["order_id","target"],sort=False).size().to_numpy()
model=LGBMRanker(objective="lambdarank",n_estimators=80,learning_rate=.04,num_leaves=15,max_depth=4,min_child_samples=20,reg_lambda=5,random_state=42,verbosity=-1)
model.fit(tr[cols],tr.label,group=groups); te["pred"]=model.predict(te[cols]); base=te.copy(); base["pred"]=base["score"]
payload={"train_windows":[2,3],"test_window":4,"model":"LightGBM_LambdaRank","features":cols,"baseline_union_rrf_f4":score(base),"lambdarank_f4":score(te),"promotion":False,"reason":"Gate de promotion non satisfait; aucun retuning sur F4"}
(OUT/"complement_lambdarank_metrics.json").write_text(json.dumps(payload,indent=2),encoding="utf-8"); te.to_parquet(OUT/"complement_lambdarank_predictions_f4.parquet",index=False)
