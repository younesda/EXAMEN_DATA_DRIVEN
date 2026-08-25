"""Recommandation finale: paniers, sessions, collaboratif léger et hybride."""
from __future__ import annotations
import gc,hashlib,json
from collections import defaultdict
from pathlib import Path
import joblib,numpy as np,pandas as pd
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity
from src.config.settings import PROJECT_ROOT

ROOT=PROJECT_ROOT/'data/processed/final';OUT=PROJECT_ROOT/'models/recommendation';REPORT=PROJECT_ROOT/'reports/final';SEED=42
def top(scores,k=10,exclude=None):
    z=np.asarray(scores,float).copy();
    if exclude:z[list(exclude)]=-np.inf
    order=np.lexsort((np.arange(len(z)),-z));return order[np.isfinite(z[order])][:k]
def eligible_historical_web(interactions,cutoff):
    cutoff=pd.Timestamp(cutoff,tz='UTC') if pd.Timestamp(cutoff).tzinfo is None else pd.Timestamp(cutoff)
    return interactions[(interactions.event_timestamp<cutoff)&interactions.type_identite.eq('client')&~interactions.event_type.eq('purchase')]
def met(recs,targets,k,pop,cats):
    rr=[];prec=[];nd=[];ap=[];items=[];div=[];nov=[]
    for u,t in targets.items():
        if not t or u not in recs:continue
        r=recs[u][:k];hits=np.array([int(x in t) for x in r]);rr.append(hits.sum()/len(t));prec.append(hits.sum()/k)
        nd.append(sum(h/np.log2(i+2) for i,h in enumerate(hits))/sum(1/np.log2(i+2) for i in range(min(len(t),k))))
        ap.append(sum((hits[:i+1].sum()/(i+1))*hits[i] for i in range(k))/max(1,min(len(t),k)));items+=list(r)
        div.append(len({cats[x] for x in r})/k);nov.append(np.mean([-np.log2(max(pop[x],1e-9)) for x in r]))
    return {'recall':float(np.mean(rr)),'precision':float(np.mean(prec)),'ndcg':float(np.mean(nd)),'map':float(np.mean(ap)),
      'catalog_coverage':len(set(items))/len(pop),'user_coverage':len(rr)/max(len(targets),1),'diversity':float(np.mean(div)),
      'novelty':float(np.mean(nov)),'concentration_top10':sum(pd.Series(items).value_counts().head(10))/max(len(items),1)}
def user_metric(rec,target,k=10):
    r=rec[:k];hits=np.array([int(x in target) for x in r]);recall=float(hits.sum()/max(len(target),1))
    ideal=sum(1/np.log2(i+2) for i in range(min(len(target),k)))
    ndcg=float(sum(h/np.log2(i+2) for i,h in enumerate(hits))/max(ideal,1e-12))
    return recall,ndcg
def paired_bootstrap(frame,columns=('recall_diff','ndcg_diff'),draws=5000):
    rng=np.random.default_rng(SEED);out={'unit':'client_fenetre','draws':draws,'seed':SEED}
    n=len(frame)
    for col in columns:
        values=frame[col].to_numpy(float);samples=np.empty(draws)
        for j in range(draws):samples[j]=values[rng.integers(0,n,n)].mean()
        out[col]={'mean':float(values.mean()),'ci95_low':float(np.quantile(samples,.025)),'ci95_high':float(np.quantile(samples,.975))}
    return out
def write_manifest():
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='manifest.sha256.json'}
    (OUT/'manifest.sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
def main():
    OUT.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    b=pd.read_parquet(ROOT/'order_baskets.parquet');s=pd.read_parquet(ROOT/'session_sequences.parquet',columns=['session_id','event_timestamp','event_type','produit_key','order_id']);i=pd.read_parquet(ROOT/'client_product_interactions.parquet',columns=['identite','type_identite','produit_key','event_timestamp','event_type','poids_total'])
    b['date_commande']=pd.to_datetime(b.date_commande);s['event_timestamp']=pd.to_datetime(s.event_timestamp,utc=True);i['event_timestamp']=pd.to_datetime(i.event_timestamp,utc=True)
    products=sorted(b.produit_key.unique());pidx={p:j for j,p in enumerate(products)};cats=b.drop_duplicates('produit_key').set_index('produit_key').categorie.reindex(products).fillna('inconnue').to_numpy()
    windows=[];artifact={};paired=[]
    for wi,back in enumerate((90,60,30),1):
        cut=b.date_commande.max()-pd.Timedelta(days=back);end=cut+pd.Timedelta(days=29)
        tr=b[b.date_commande<cut];te=b[b.date_commande.between(cut,end)];users=sorted(tr.client_key.unique());uidx={u:j for j,u in enumerate(users)}
        M=sparse.csr_matrix((tr.quantite.to_numpy(float),([uidx[x] for x in tr.client_key],[pidx[x] for x in tr.produit_key])),shape=(len(users),len(products)))
        seen={u:set(M[uidx[u]].indices) for u in users};targets=defaultdict(set)
        for r in te.itertuples():
            if r.client_key in uidx:targets[r.client_key].add(pidx[r.produit_key])
        pop=np.asarray(M.sum(axis=0)).ravel();prob=pop/max(pop.sum(),1);recent=tr[tr.date_commande>=cut-pd.Timedelta(days=60)];rpop=np.bincount([pidx[x] for x in recent.produit_key],weights=recent.quantite,minlength=len(products))
        binary=(M>0).astype(float);sim=cosine_similarity(binary.T);np.fill_diagonal(sim,0)
        co=(binary.T@binary).toarray();lift=co/(np.maximum(pop[:,None],1)*np.maximum(pop[None,:],1)/max(len(users),1));np.fill_diagonal(lift,0)
        svd=TruncatedSVD(n_components=32,random_state=SEED);U=svd.fit_transform(M);svscores=U@svd.components_
        # Web humain strictement antérieur; purchase exclu pour ne pas doubler les ventes.
        iw=eligible_historical_web(i,cut)
        wg=iw.groupby(['identite','produit_key']).poids_total.sum();H=M.toarray().astype(float)
        for (u,p),val in wg.items():
            if u in uidx and p in pidx:H[uidx[u],pidx[p]]+=.2*val
        hsim=cosine_similarity(H.T);np.fill_diagonal(hsim,0)
        model_names=['popularite_globale','popularite_recente','popularite_categorie','item_item_commandes','regles_association_lift','SVD_implicite','hybride_achats_web']
        recs_discovery={m:{} for m in model_names};recs_replenishment={m:{} for m in model_names}
        catpop={c:np.where(cats==c,pop,-np.inf) for c in set(cats)}
        latest_product=(tr.sort_values(['client_key','date_commande','order_id'])
                        .groupby('client_key').produit_key.last().map(pidx))
        for u in targets:
            ex=seen[u];vec=M[uidx[u]].toarray().ravel();lastcat=cats[int(latest_product[u])]
            raw_scores={
                'popularite_globale':pop,
                'popularite_recente':rpop,
                'popularite_categorie':catpop[lastcat],
                'item_item_commandes':vec@sim,
                'regles_association_lift':vec@lift,
                'SVD_implicite':svscores[uidx[u]],
                'hybride_achats_web':H[uidx[u]]@hsim,
            }
            for name,scores in raw_scores.items():
                recs_discovery[name][u]=top(scores,10,ex)
                recs_replenishment[name][u]=top(scores,10,None)
            gr,gnd=user_metric(recs_discovery['popularite_globale'][u],targets[u])
            hr,hnd=user_metric(recs_discovery['hybride_achats_web'][u],targets[u])
            paired.append({'window':wi,'client_key':u,'global_recall':gr,'hybrid_recall':hr,
                           'global_ndcg':gnd,'hybrid_ndcg':hnd,'recall_diff':hr-gr,'ndcg_diff':hnd-gnd})
        for name in model_names:
            for scenario,use in [('decouverte',recs_discovery[name]),('reapprovisionnement',recs_replenishment[name])]:
                for k in (5,10):windows.append({'window':wi,'model':name,'scenario':scenario,'k':k,**met(use,targets,k,prob,cats)})
        if wi==3:artifact={'products':products,'popularity':pop,'item_similarity':sim,'hybrid_similarity':hsim,'svd':svd}
        del M,binary,co,lift,U,svscores,H,recs_discovery,recs_replenishment,iw,wg
        gc.collect()
    # Complémentaires panier: cacher un article de chaque commande multi-produit.
    orders=b.groupby('order_id').produit_key.apply(lambda x:list(dict.fromkeys(x)));comp={};ct={}
    for oid,ps in orders.items():
        if len(ps)>1:
            ctx=[pidx[x] for x in ps[:-1]];comp[oid]=top(sim[ctx].sum(axis=0),10,set(ctx));ct[oid]={pidx[ps[-1]]}
    compm=met(comp,ct,10,np.ones(len(products))/len(products),cats)
    # Session: contexte strictement avant purchase, anonymes conservés sans client fictif.
    confirmed_orders=set(b.order_id)
    del i
    gc.collect()
    purchases=s[s.event_type.eq('purchase')&s.order_id.isin(confirmed_orders)&s.produit_key.isin(pidx)]
    first_purchase=purchases.groupby('session_id',as_index=False).event_timestamp.min().rename(columns={'event_timestamp':'target_ts'})
    contexts=(s[s.session_id.isin(first_purchase.session_id)&s.produit_key.isin(pidx)]
              .merge(first_purchase,on='session_id',how='inner'))
    contexts=contexts[contexts.event_timestamp<contexts.target_ts]
    session_ids=sorted(set(contexts.session_id)&set(purchases.session_id));sx={x:j for j,x in enumerate(session_ids)}
    contexts=contexts[contexts.session_id.isin(sx)]
    C=sparse.csr_matrix((np.ones(len(contexts)),([sx[x] for x in contexts.session_id],[pidx[x] for x in contexts.produit_key])),shape=(len(session_ids),len(products)))
    session_scores=np.asarray(C@sim)
    # En intention de session, un produit vu avant le purchase reste candidat :
    # l'exclure rendrait impossible de mesurer la conversion vue→achat.
    sr={sid:top(session_scores[sx[sid]],10,None) for sid in session_ids}
    st={sid:set(pidx[x] for x in g.produit_key) for sid,g in purchases[purchases.session_id.isin(sx)].groupby('session_id')}
    sessm=met(sr,st,10,np.ones(len(products))/len(products),cats)
    context_sets={sid:set(C[sx[sid]].indices) for sid in session_ids};target_total=sum(len(st[sid]) for sid in session_ids)
    seen_targets=sum(len(context_sets[sid]&st[sid]) for sid in session_ids)
    self_only=sum(bool(context_sets[sid]) and context_sets[sid]<=st[sid] for sid in session_ids)
    session_diagnostic={'usable_model':False,'temporal_alignment':'contexte strictement antérieur au premier purchase confirmé',
      'temporal_violations':int((contexts.event_timestamp>=contexts.target_ts).sum()),'candidate_catalog_size':len(products),
      'targets_outside_candidates':sum(len({x for x in st[sid] if x>=len(products)}) for sid in session_ids),
      'exclude_seen_applied':False,'already_seen_target_rate':seen_targets/max(target_total,1),
      'target_survival_if_seen_excluded':1-seen_targets/max(target_total,1),'self_only_context_session_rate':self_only/max(len(session_ids),1),
      'confirmed_purchase_events':len(purchases),'confirmed_purchase_sessions':purchases.session_id.nunique(),
      'sessions_with_pre_purchase_product_context':len(session_ids),
      'ground_truth':'tous les produits des purchase reliés à une commande confirmée de la session; cutoff au premier purchase'}
    df=pd.DataFrame(windows);summary=df[df.k.eq(10)].groupby(['model','scenario']).agg(recall=('recall','mean'),ndcg=('ndcg','mean'),map10=('map','mean'),coverage=('catalog_coverage','mean'),diversity=('diversity','mean')).reset_index().sort_values(['scenario','ndcg'],ascending=[True,False])
    paired_frame=pd.DataFrame(paired);bootstrap=paired_bootstrap(paired_frame)
    per_window=(paired_frame.groupby('window').agg(global_recall=('global_recall','mean'),hybrid_recall=('hybrid_recall','mean'),global_ndcg=('global_ndcg','mean'),hybrid_ndcg=('hybrid_ndcg','mean'),n_client_windows=('client_key','size')).reset_index())
    per_window['recall_diff']=per_window.hybrid_recall-per_window.global_recall;per_window['ndcg_diff']=per_window.hybrid_ndcg-per_window.global_ndcg
    nd=bootstrap['ndcg_diff'];stable=bool((per_window.ndcg_diff>0).all() and nd['ci95_low']>0)
    hybrid_status='modele_retenu' if stable else 'challenger_exploratoire'
    joblib.dump(artifact,OUT/'recommender.joblib');meta={'selected':None if not stable else 'hybride_achats_web','official_baseline':'popularite_globale','hybrid_status':hybrid_status,'summary':summary.to_dict('records'),'per_window_hybrid_vs_global':per_window.to_dict('records'),'paired_bootstrap':bootstrap,'complementaires_panier':{'status':'systeme_metier_separe',**compm},'sessions_anonymes_et_connues':sessm,'session_diagnostic':session_diagnostic,'deep_model_used':False,'lightfm_available':False,'implicit_als_available':False}
    (OUT/'metadata.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8');write_manifest()
    bootstrap_text=f'- ΔNDCG@10 : {nd["mean"]:.6f}, IC95% [{nd["ci95_low"]:.6f}; {nd["ci95_high"]:.6f}].\n- ΔRecall@10 : {bootstrap["recall_diff"]["mean"]:.6f}, IC95% [{bootstrap["recall_diff"]["ci95_low"]:.6f}; {bootstrap["recall_diff"]["ci95_high"]:.6f}].'
    lines=['# 04 — Recommandation finale','',f'**Baseline officielle : `popularite_globale`. Hybride : `{hybrid_status}`.**','',summary.to_markdown(index=False),'','## Comparaison hybride vs baseline par fenêtre','',per_window.to_markdown(index=False),'','## Bootstrap apparié client-fenêtre','',bootstrap_text,'', '## Systèmes spécialisés','',f'- Complémentaires panier : système métier séparé, NDCG@10 {compm["ndcg"]:.4f}.',f'- Sessions : modèle non utilisable, NDCG@10 {sessm["ndcg"]:.6g}.','',
      'Les achats confirmés fournissent les cibles. Les `purchase` web ne sont jamais additionnés aux ventes; leur statut vient de la commande. Les bots sont exclus. Les anonymes restent des identités de session, sans client inventé.','',
      'LightFM/ALS/BPR natifs indisponibles dans l’environnement; SVD implicite légère évaluée. Aucun Transformer ou réseau profond, volume insuffisant pour le justifier.','',
      f'Diagnostic session : {json.dumps(session_diagnostic,ensure_ascii=False)}','',
      'Commande : `python -m src.pipelines.final_recommendation`.']
    (REPORT/'04_recommendation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'official_baseline':'popularite_globale','hybrid_status':hybrid_status,'basket_ndcg10':compm['ndcg'],'session_ndcg10':sessm['ndcg']},default=str))
if __name__=='__main__':main()
