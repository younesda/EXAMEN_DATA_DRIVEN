import json
import numpy as np
import pandas as pd
from src.config.settings import PROJECT_ROOT

OUT=PROJECT_ROOT/"models"/"advanced"/"recommendation_ranking"; SEED=42
d=pd.read_parquet(OUT/"complement_topk_predictions.parquet")
def unit(g):
    g=g.sort_values('rank'); rel=g.label.to_numpy()[:10]; pos=np.flatnonzero(rel)
    return pd.Series({'recall10':float(rel.sum()>0),'ndcg10':float(sum(v/np.log2(i+2) for i,v in enumerate(rel))), 'mrr':1/(pos[0]+1) if len(pos) else 0.})
u=d.groupby(['window','model','order_id']).apply(unit,include_groups=False).reset_index()
mean=u.groupby(['window','model'])[['recall10','ndcg10']].mean().reset_index()
best_simple=mean[(mean.model.isin(['global','category','cooccurrence','bm25','association']))].sort_values('ndcg10',ascending=False).iloc[0].model
def boot(a,b, reps=2000):
    x=a.merge(b,on=['window','order_id'],suffixes=('_a','_b')); rng=np.random.default_rng(SEED); vals=[]
    for _ in range(reps):
        q=[]
        for _,g in x.groupby('window'): q.extend(rng.choice((g.ndcg10_a-g.ndcg10_b).to_numpy(),len(g),replace=True))
        vals.append(float(np.mean(q)))
    return {'mean_ndcg10_diff':float(np.mean(vals)),'ci95':[float(np.quantile(vals,.025)),float(np.quantile(vals,.975))],'favorable_fraction':float(np.mean(np.asarray(vals)>0))}
comparisons=[]
for a,b in [(best_simple,'reference'),('rrf','reference'),('rrf',best_simple),('lambdarank_f4',best_simple)]:
    if a=='lambdarank_f4':
        lp=pd.read_parquet(OUT/'complement_lambdarank_predictions_f4.parquet'); lp['model']='lambdarank_f4'; bp=d[(d.window==4)&d.model.eq(best_simple)].copy(); bp['model']='best_f4'; lu=lp.groupby(['window','model','order_id']).apply(unit,include_groups=False).reset_index(); bu=bp.groupby(['window','model','order_id']).apply(unit,include_groups=False).reset_index(); comparisons.append({'a':a,'b':b,**boot(lu,bu)}); continue
    comparisons.append({'a':a,'b':b,**boot(u[u.model.eq(a)],u[u.model.eq(b)])})
payload={'best_simple_model':best_simple,'best_simple_rule':'maximum mean NDCG@10 F2-F4 before coverage gate','comparisons':comparisons,'coverage_gate_per_window':mean[mean.model.eq(best_simple)].to_dict('records'),'lambda_rank_f4_reference_file':'complement_lambdarank_metrics.json','note':'old reference is recalculated on identical masked-target F2-F4 orders; legacy global 0.1006/0.0485 remains a different perimeter'}
(OUT/'complement_decision_metadata.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
pd.DataFrame(comparisons).to_csv(OUT/'complement_decision_bootstrap.csv',index=False)
