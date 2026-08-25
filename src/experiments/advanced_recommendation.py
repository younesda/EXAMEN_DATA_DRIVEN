"""Recommandation générale avancée à quatre fenêtres temporelles.

Les achats confirmés définissent exclusivement les cibles. Les événements web
`purchase` ne sont jamais additionnés aux ventes. Le ranker de chaque fenêtre
est appris sur une pseudo-fenêtre strictement antérieure au test externe.
"""
from __future__ import annotations

import gc
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import psutil
import torch
from catboost import CatBoostClassifier
from lightgbm import LGBMRanker
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity

from src.config.settings import PROJECT_ROOT
from src.data.extract import load_cached
from src.pipelines.final_recommendation import top

ROOT = PROJECT_ROOT / "data/processed/final"
OUT = PROJECT_ROOT / "models/advanced/recommendation"
CHECKPOINTS = PROJECT_ROOT / "checkpoints/advanced_recommendation"
LOG = PROJECT_ROOT / "logs/advanced_recommendation.jsonl"
REFERENCE = PROJECT_ROOT / "models/recommendation/metadata.json"
SEED = 42
BACKS = (120, 90, 60, 30)
K = 10
MAX_SECONDS_PER_MODEL = 300
GENERATOR_NAMES = ("popularite_globale", "popularite_recente", "item_item_commandes",
                   "BM25_implicite", "SVD_implicite", "BPR_implicite", "hybride_web_historique")
RANK_FEATURES = ("popularity", "recent_popularity", "item_item", "bm25", "svd", "bpr", "hybrid_web",
                 "user_item_quantity", "category_affinity", "last_basket_complementarity", "item_views",
                 "item_carts", "user_order_frequency", "user_recency_days", "stock_at_cutoff",
                 "price", "margin_rate", "category_code", "source_code", "device_code")
ABLATIONS = {
    "ranker_full": (),
    "ranker_no_web": ("hybrid_web", "item_views", "item_carts", "source_code", "device_code"),
    "ranker_no_stock": ("stock_at_cutoff",),
    "ranker_no_orders": ("item_item", "bm25", "svd", "bpr", "user_item_quantity",
                         "category_affinity", "last_basket_complementarity", "user_order_frequency", "user_recency_days"),
}


def _log(event: str, **payload) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"timestamp": pd.Timestamp.utcnow().isoformat(), "event": event, **payload}, default=str)+"\n")


def _normalize(values: np.ndarray) -> np.ndarray:
    x = np.nan_to_num(np.asarray(values, float), nan=0.0, posinf=0.0, neginf=0.0)
    scale = np.max(np.abs(x))
    return x / scale if scale > 0 else x


def bm25_item_similarity(matrix: sparse.csr_matrix, k1: float = 1.2, b: float = .75) -> np.ndarray:
    x = matrix.astype(float).tocsr(); n_users, _ = x.shape
    row_length = np.asarray(x.sum(axis=1)).ravel(); average = max(row_length.mean(), 1e-9)
    rows = np.repeat(np.arange(n_users), np.diff(x.indptr)); denominator = x.data + k1*(1-b+b*row_length[rows]/average)
    weighted = x.copy(); weighted.data = x.data*(k1+1)/denominator
    df = np.asarray((x > 0).sum(axis=0)).ravel()
    idf = np.maximum(0, np.log((n_users-df+.5)/(df+.5)+1))
    weighted = weighted @ sparse.diags(idf)
    similarity = cosine_similarity(weighted.T); np.fill_diagonal(similarity, 0)
    return similarity


def bpr_scores(matrix: sparse.csr_matrix, factors: int = 24, epochs: int = 8) -> np.ndarray:
    """BPR CPU léger et déterministe; matrice dense finale limitée à 5000×300."""
    torch.set_num_threads(2); torch.manual_seed(SEED); rng = np.random.default_rng(SEED)
    users, items = matrix.nonzero(); n_users, n_items = matrix.shape
    user_embedding = torch.nn.Embedding(n_users, factors); item_embedding = torch.nn.Embedding(n_items, factors)
    torch.nn.init.normal_(user_embedding.weight, std=.05); torch.nn.init.normal_(item_embedding.weight, std=.05)
    optimizer = torch.optim.Adam([*user_embedding.parameters(), *item_embedding.parameters()], lr=.02, weight_decay=1e-5)
    seen = [set(matrix[user].indices) for user in range(n_users)]
    order = np.arange(len(users))
    for _ in range(epochs):
        rng.shuffle(order)
        for start in range(0, len(order), 4096):
            batch = order[start:start+4096]; u = users[batch]; positive = items[batch]
            negative = rng.integers(0, n_items, len(batch))
            for index in range(len(batch)):
                while negative[index] in seen[u[index]]: negative[index] = rng.integers(0, n_items)
            ut = torch.as_tensor(u); pt = torch.as_tensor(positive); nt = torch.as_tensor(negative)
            uv = user_embedding(ut); difference = (uv*item_embedding(pt)).sum(1)-(uv*item_embedding(nt)).sum(1)
            loss = -torch.nn.functional.logsigmoid(difference).mean(); optimizer.zero_grad(); loss.backward(); optimizer.step()
    with torch.no_grad(): return (user_embedding.weight @ item_embedding.weight.T).cpu().numpy()


def _web_context(cutoff: pd.Timestamp, users: list[str], products: list[str]) -> tuple[np.ndarray, np.ndarray, dict, dict]:
    interactions = pd.read_parquet(ROOT / "client_product_interactions.parquet",
        columns=["identite", "type_identite", "produit_key", "event_timestamp", "event_type", "quantity"])
    interactions["event_timestamp"] = pd.to_datetime(interactions.event_timestamp, utc=True)
    cutoff_utc = pd.Timestamp(cutoff, tz="UTC")
    eligible = interactions[(interactions.event_timestamp < cutoff_utc) & interactions.type_identite.eq("client")
                            & ~interactions.event_type.eq("purchase")]
    uidx = {u:index for index,u in enumerate(users)}; pidx = {p:index for index,p in enumerate(products)}
    eligible = eligible[eligible.identite.isin(uidx) & eligible.produit_key.isin(pidx)].copy()
    eligible["weight"] = eligible.event_type.map({"view":1.0,"add_to_cart":3.0}).fillna(0)*eligible.quantity.fillna(1).clip(lower=1)
    web = sparse.csr_matrix((eligible.weight, ([uidx[x] for x in eligible.identite], [pidx[x] for x in eligible.produit_key])), shape=(len(users),len(products)))
    item_views = eligible[eligible.event_type.eq("view")].produit_key.value_counts().reindex(products, fill_value=0).to_numpy(float)
    item_carts = eligible[eligible.event_type.eq("add_to_cart")].produit_key.value_counts().reindex(products, fill_value=0).to_numpy(float)
    raw = load_cached("fact_evenements_web").copy(); raw["event_timestamp"] = pd.to_datetime(raw.event_timestamp, utc=True)
    raw = raw[(raw.event_timestamp < cutoff_utc) & ~raw.est_bot & raw.client_key.isin(uidx)]
    source = raw.groupby("client_key").source_trafic.agg(lambda x: x.value_counts().index[0] if len(x) else "unknown")
    device = raw.groupby("client_key").appareil.agg(lambda x: x.value_counts().index[0] if len(x) else "unknown")
    source_levels = {value:index+1 for index,value in enumerate(sorted(source.dropna().unique()))}
    device_levels = {value:index+1 for index,value in enumerate(sorted(device.dropna().unique()))}
    return web.toarray(), np.vstack([item_views,item_carts]), source.map(source_levels).to_dict(), device.map(device_levels).to_dict()


def build_state(baskets: pd.DataFrame, cutoff: pd.Timestamp, products: list[str], product_info: pd.DataFrame) -> dict:
    train = baskets[baskets.date_commande < cutoff].copy(); users = sorted(train.client_key.unique())
    uidx = {u:index for index,u in enumerate(users)}; pidx = {p:index for index,p in enumerate(products)}
    matrix = sparse.csr_matrix((train.quantite.to_numpy(float), ([uidx[x] for x in train.client_key],
        [pidx[x] for x in train.produit_key])), shape=(len(users),len(products)))
    binary = (matrix > 0).astype(float); popularity = np.asarray(matrix.sum(axis=0)).ravel()
    recent = train[train.date_commande >= cutoff-pd.Timedelta(days=60)]
    recent_popularity = np.bincount([pidx[x] for x in recent.produit_key], weights=recent.quantite, minlength=len(products))
    item_similarity = cosine_similarity(binary.T); np.fill_diagonal(item_similarity, 0)
    bm25_similarity = bm25_item_similarity(matrix)
    components = min(40, max(2, min(matrix.shape)-1)); svd = TruncatedSVD(n_components=components, random_state=SEED)
    svd_scores = svd.fit_transform(matrix) @ svd.components_
    start = time.perf_counter(); bpr = bpr_scores(matrix); _log("bpr_complete", cutoff=str(cutoff.date()), elapsed_seconds=time.perf_counter()-start,
        rss_mb=psutil.Process().memory_info().rss/2**20, success=True)
    web, web_items, source_codes, device_codes = _web_context(cutoff, users, products)
    hybrid_matrix = matrix.toarray()+.15*web; hybrid_similarity = cosine_similarity(hybrid_matrix.T); np.fill_diagonal(hybrid_similarity,0)
    last_orders = (train.sort_values(["client_key","date_commande","order_id"]).groupby("client_key").order_id.last())
    order_products = train.groupby("order_id").produit_key.apply(lambda x:[pidx[v] for v in dict.fromkeys(x)])
    last_baskets = {u:order_products.get(order,[]) for u,order in last_orders.items()}
    order_stats = train.groupby("client_key").agg(order_frequency=("order_id","nunique"), last_order=("date_commande","max"))
    stock_daily = pd.read_parquet(ROOT/"product_daily_forecasting.parquet", columns=["produit_key","ds","niveau_stock"])
    stock_daily["ds"] = pd.to_datetime(stock_daily.ds); stock_date = stock_daily[stock_daily.ds < cutoff].ds.max()
    stock = stock_daily[stock_daily.ds.eq(stock_date)].set_index("produit_key").niveau_stock.reindex(products).fillna(0).to_numpy(float)
    categories = product_info.set_index("produit_key").categorie.reindex(products).fillna("unknown")
    category_levels = {value:index for index,value in enumerate(sorted(categories.unique()))}
    return {"cutoff":cutoff,"train":train,"users":users,"uidx":uidx,"pidx":pidx,"products":products,"matrix":matrix,
        "seen":{u:set(matrix[uidx[u]].indices) for u in users},"popularity":popularity,"recent_popularity":recent_popularity,
        "item_similarity":item_similarity,"bm25_similarity":bm25_similarity,"svd_scores":svd_scores,"bpr_scores":bpr,
        "hybrid_matrix":hybrid_matrix,"hybrid_similarity":hybrid_similarity,"item_views":web_items[0],"item_carts":web_items[1],
        "source_codes":source_codes,"device_codes":device_codes,"last_baskets":last_baskets,"order_stats":order_stats,
        "stock":stock,"price":product_info.set_index("produit_key").prix_base_xof.reindex(products).to_numpy(float),
        "margin_rate":((product_info.set_index("produit_key").prix_base_xof-product_info.set_index("produit_key").cout_xof)/
                       product_info.set_index("produit_key").prix_base_xof).reindex(products).to_numpy(float),
        "categories":categories.to_numpy(),"category_code":categories.map(category_levels).to_numpy(int)}


def user_scores(state: dict, user: str) -> dict[str,np.ndarray]:
    n_items=len(state["products"]); zero=np.zeros(n_items); known=user in state["uidx"]
    if known:
        index=state["uidx"][user]; vector=state["matrix"][index].toarray().ravel()
        item_item=vector@state["item_similarity"]; bm25=vector@state["bm25_similarity"]
        svd=state["svd_scores"][index]; bpr=state["bpr_scores"][index]
        hybrid=state["hybrid_matrix"][index]@state["hybrid_similarity"]
        last=state["last_baskets"].get(user,[]); complement=state["item_similarity"][last].sum(axis=0) if last else zero
        category_quantity=pd.Series(vector).groupby(state["categories"]).transform("sum").to_numpy()
        stats=state["order_stats"].loc[user]; frequency=float(stats.order_frequency); recency=float((state["cutoff"]-stats.last_order).days)
    else:
        vector=item_item=bm25=svd=bpr=hybrid=complement=category_quantity=zero; frequency=0.; recency=999.
    return {"popularite_globale":state["popularity"],"popularite_recente":state["recent_popularity"],
            "item_item_commandes":item_item,"BM25_implicite":bm25,"SVD_implicite":svd,
            "BPR_implicite":bpr,"hybride_web_historique":hybrid,
            "user_item_quantity":vector,"category_affinity":category_quantity,
            "last_basket_complementarity":complement,"user_order_frequency":np.full(n_items,frequency),
            "user_recency_days":np.full(n_items,recency)}


def candidates_and_features(state: dict, users: list[str]) -> tuple[pd.DataFrame, dict[str,dict[str,list[int]]]]:
    rows=[]; generator_recs={name:{} for name in GENERATOR_NAMES}
    for user in users:
        scores=user_scores(state,user); exclude=state["seen"].get(user,set()); candidate=set()
        for name in GENERATOR_NAMES:
            rec=top(scores[name],30,exclude); generator_recs[name][user]=rec[:K].tolist(); candidate.update(rec.tolist())
        for item in sorted(candidate):
            rows.append({"client_key":user,"item":item,
                "popularity":_normalize(state["popularity"])[item],"recent_popularity":_normalize(state["recent_popularity"])[item],
                "item_item":_normalize(scores["item_item_commandes"])[item],"bm25":_normalize(scores["BM25_implicite"])[item],
                "svd":_normalize(scores["SVD_implicite"])[item],"bpr":_normalize(scores["BPR_implicite"])[item],
                "hybrid_web":_normalize(scores["hybride_web_historique"])[item],"user_item_quantity":scores["user_item_quantity"][item],
                "category_affinity":scores["category_affinity"][item],"last_basket_complementarity":_normalize(scores["last_basket_complementarity"])[item],
                "item_views":_normalize(state["item_views"])[item],"item_carts":_normalize(state["item_carts"])[item],
                "user_order_frequency":scores["user_order_frequency"][item],"user_recency_days":scores["user_recency_days"][item],
                "stock_at_cutoff":state["stock"][item],"price":state["price"][item],"margin_rate":state["margin_rate"][item],
                "category_code":state["category_code"][item],"source_code":state["source_codes"].get(user,0),
                "device_code":state["device_codes"].get(user,0)})
    return pd.DataFrame(rows),generator_recs


def truths(baskets: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, state: dict) -> tuple[dict,dict]:
    test=baskets[baskets.date_commande.between(start,end)]; raw=defaultdict(set)
    for row in test.itertuples(): raw[row.client_key].add(state["pidx"][row.produit_key])
    discovery={user:targets-state["seen"].get(user,set()) for user,targets in raw.items()}
    return dict(raw),discovery


def evaluate(recs: dict[str,list[int]], truth: dict[str,set[int]], n_items: int, k:int=K) -> tuple[dict,pd.DataFrame]:
    rows=[]; recommended=[]
    for user,targets in truth.items():
        rec=list(recs.get(user,[]))[:k]; hits=np.array([item in targets for item in rec],int)
        eligible=bool(targets); recall=float(hits.sum()/len(targets)) if eligible else 0.0
        ideal=sum(1/np.log2(index+2) for index in range(min(len(targets),k))) if eligible else 1.0
        ndcg=float(sum(hit/np.log2(index+2) for index,hit in enumerate(hits))/ideal) if eligible else 0.0
        rows.append({"client_key":user,"recall":recall,"ndcg":ndcg,"eligible_truth":eligible}); recommended+=rec
    frame=pd.DataFrame(rows); eligible=frame[frame.eligible_truth]
    metrics={"recall_end_to_end":float(frame.recall.mean()),"ndcg_end_to_end":float(frame.ndcg.mean()),
             "recall_eligible":float(eligible.recall.mean()) if len(eligible) else 0.,"ndcg_eligible":float(eligible.ndcg.mean()) if len(eligible) else 0.,
             "catalog_coverage":len(set(recommended))/n_items,"n_clients":len(frame),"n_eligible_truth":len(eligible),
             "eligible_truth_rate":float(frame.eligible_truth.mean())}
    return metrics,frame


def _fit_rankers(train_frame:pd.DataFrame, features:list[str]) -> tuple[object,object]:
    useful=train_frame.groupby("client_key").label.transform("sum").gt(0); train=train_frame[useful].sort_values("client_key")
    groups=train.groupby("client_key",sort=False).size().to_numpy(); X=train[features].replace([np.inf,-np.inf],np.nan).fillna(0); y=train.label
    lgb=LGBMRanker(objective="lambdarank",n_estimators=220,learning_rate=.035,num_leaves=31,min_child_samples=80,
                   random_state=SEED,n_jobs=2,verbosity=-1); lgb.fit(X,y,group=groups)
    cat=CatBoostClassifier(loss_function="Logloss",iterations=220,depth=7,learning_rate=.04,random_seed=SEED,
                           thread_count=2,verbose=False,allow_writing_files=False,auto_class_weights="Balanced")
    cat.fit(X,y); return lgb,cat


def _rank(frame:pd.DataFrame,model,features:list[str]) -> dict[str,list[int]]:
    data=frame.copy(); data["score"]=model.predict_proba(data[features].fillna(0))[:,1] if isinstance(model,CatBoostClassifier) else model.predict(data[features].fillna(0))
    return {user:group.sort_values(["score","item"],ascending=[False,True]).item.head(K).astype(int).tolist()
            for user,group in data.groupby("client_key")}


def paired_bootstrap(frame:pd.DataFrame,draws:int=5000)->dict:
    rng=np.random.default_rng(SEED); out={"unit":"client_fenetre","draws":draws,"seed":SEED}
    for column in ("recall_diff","ndcg_diff"):
        values=frame[column].to_numpy(float); estimates=np.empty(draws)
        for draw in range(draws): estimates[draw]=values[rng.integers(0,len(values),len(values))].mean()
        out[column]={"mean":float(values.mean()),"ci95_low":float(np.quantile(estimates,.025)),"ci95_high":float(np.quantile(estimates,.975))}
    return out


def main()->int:
    OUT.mkdir(parents=True,exist_ok=True); CHECKPOINTS.mkdir(parents=True,exist_ok=True)
    baskets=pd.read_parquet(ROOT/"order_baskets.parquet"); baskets["date_commande"]=pd.to_datetime(baskets.date_commande)
    products=sorted(baskets.produit_key.unique()); product_info=load_cached("dim_produit")[["produit_key","categorie","prix_base_xof","cout_xof"]].drop_duplicates("produit_key")
    max_ds=baskets.date_commande.max(); metric_rows=[]; paired=[]; candidate_audit=[]; last_artifact={}
    for window,back in enumerate(BACKS,1):
        start=max_ds-pd.Timedelta(days=back-1); end=start+pd.Timedelta(days=29); pseudo=start-pd.Timedelta(days=30)
        state_validation=build_state(baskets,pseudo,products,product_info)
        validation_raw,validation_truth=truths(baskets,pseudo,start-pd.Timedelta(days=1),state_validation)
        validation_users=sorted(validation_raw); validation_frame,_=candidates_and_features(state_validation,validation_users)
        validation_frame["label"]=[int(item in validation_truth[user]) for user,item in zip(validation_frame.client_key,validation_frame.item)]
        train_candidate_recall=float(sum(any(item in validation_truth[u] for item in g.item) for u,g in validation_frame.groupby("client_key"))/max(len(validation_truth),1))
        state=build_state(baskets,start,products,product_info); raw_truth,test_truth=truths(baskets,start,end,state); users=sorted(raw_truth)
        test_frame,generator_recs=candidates_and_features(state,users)
        test_candidate_recall=float(sum(any(item in test_truth[u] for item in g.item) for u,g in test_frame.groupby("client_key"))/max(len(test_truth),1))
        candidate_audit.append({"window":window,"train_candidate_client_recall":train_candidate_recall,
                                "test_candidate_client_recall":test_candidate_recall,"n_test_clients":len(users),
                                "population_filtered":False,"test_targets_injected":False})
        models={}
        start_fit=time.perf_counter(); full_features=list(RANK_FEATURES); lgb,cat=_fit_rankers(validation_frame,full_features)
        _log("rankers_complete",window=window,elapsed_seconds=time.perf_counter()-start_fit,
             rss_mb=psutil.Process().memory_info().rss/2**20,success=True)
        models["LightGBM_ranker"]=_rank(test_frame,lgb,full_features); models["CatBoost_ranker"]=_rank(test_frame,cat,full_features)
        for variant,removed in ABLATIONS.items():
            if variant=="ranker_full": models[variant]=models["LightGBM_ranker"]; continue
            features=[name for name in RANK_FEATURES if name not in removed]
            useful=validation_frame.groupby("client_key").label.transform("sum").gt(0); train=validation_frame[useful].sort_values("client_key")
            groups=train.groupby("client_key",sort=False).size().to_numpy(); ab=LGBMRanker(objective="lambdarank",n_estimators=180,
                learning_rate=.04,num_leaves=31,min_child_samples=80,random_state=SEED,n_jobs=2,verbosity=-1)
            ab.fit(train[features].fillna(0),train.label,group=groups); models[variant]=_rank(test_frame,ab,features)
        all_recs={**generator_recs,**models}; per_model={}
        baseline_frame=None
        for name,recs in all_recs.items():
            metrics,user_frame=evaluate(recs,test_truth,len(products)); metric_rows.append({"window":window,"model":name,**metrics}); per_model[name]=user_frame
            if name=="popularite_globale": baseline_frame=user_frame.rename(columns={"recall":"base_recall","ndcg":"base_ndcg"})
        rank_frame=per_model["LightGBM_ranker"].merge(baseline_frame[["client_key","base_recall","base_ndcg"]],on="client_key")
        rank_frame["recall_diff"]=rank_frame.recall-rank_frame.base_recall; rank_frame["ndcg_diff"]=rank_frame.ndcg-rank_frame.base_ndcg; rank_frame["window"]=window
        paired.append(rank_frame[["window","client_key","recall_diff","ndcg_diff"]])
        pd.DataFrame([{"client_key":u,"recommendations":models["LightGBM_ranker"].get(u,[])} for u in users]).to_parquet(CHECKPOINTS/f"window_{window}_recommendations.parquet",index=False)
        if window==4:last_artifact={"products":products,"ranker":lgb,"rank_features":full_features,"popularities":state["popularity"]}
        del state_validation,state,validation_frame,test_frame,lgb,cat,models;gc.collect()
    metrics=pd.DataFrame(metric_rows);summary=metrics.groupby("model",as_index=False).agg(recall=("recall_end_to_end","mean"),ndcg=("ndcg_end_to_end","mean"),
        recall_eligible=("recall_eligible","mean"),ndcg_eligible=("ndcg_eligible","mean"),coverage=("catalog_coverage","mean"),n_windows=("window","nunique")).sort_values("ndcg",ascending=False)
    paired_frame=pd.concat(paired,ignore_index=True); bootstrap=paired_bootstrap(paired_frame)
    per_window=metrics[metrics.model.isin(["popularite_globale","LightGBM_ranker"])].pivot(index="window",columns="model",values=["recall_end_to_end","ndcg_end_to_end"]).reset_index()
    per_window.columns=["_".join(str(x) for x in column if x).strip("_") if isinstance(column,tuple) else column for column in per_window.columns]
    nd=bootstrap["ndcg_diff"]; rank_summary=next(row for row in summary.to_dict("records") if row["model"]=="LightGBM_ranker")
    wins=int(sum(metrics[metrics.model.eq("LightGBM_ranker")].set_index("window").ndcg_end_to_end > metrics[metrics.model.eq("popularite_globale")].set_index("window").ndcg_end_to_end))
    thresholds={"recall_ge_008":rank_summary["recall"]>=.08,"ndcg_ge_0045":rank_summary["ndcg"]>=.045,
                "coverage_ge_020":rank_summary["coverage"]>=.20,"wins_ge_3_of_4":wins>=3,"bootstrap_ndcg_ci_above_zero":nd["ci95_low"]>0}
    promoted=all(thresholds.values())
    joblib.dump(last_artifact,OUT/"general_recommender.joblib")
    reference=json.loads(REFERENCE.read_text(encoding="utf-8"))
    payload={"status":"experimental","selected":"LightGBM_ranker" if promoted else None,
        "official_baseline":"popularite_globale","ranker_status":"retained" if promoted else "challenger_exploratoire",
        "validated_reference":{"path":"models/recommendation/metadata.json","sha256":hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                               "official_baseline":reference["official_baseline"],"hybrid_status":reference["hybrid_status"]},
        "window_metrics":metric_rows,"summary":summary.to_dict("records"),"candidate_audit":candidate_audit,
        "paired_bootstrap_vs_global":bootstrap,"per_window_ranker_vs_global":per_window.to_dict("records"),"decision_thresholds":thresholds,
        "ndcg_windows_won":wins,"methodology":{"outer_windows":4,"days_per_window":30,"ranker_training_window_days":30,
            "ranker_training_strictly_prior":True,"test_used_for_tuning":False,"confirmed_orders_only":True,
            "purchase_web_used_as_signal":False,"test_population_filtered":False,"seen_items_excluded":True,
            "empty_discovery_truth_scored_zero_end_to_end":True,"max_seconds_per_model":MAX_SECONDS_PER_MODEL,"sequential":True},
        "ablations":{"promotion":"not_used_in_general_ranker",**{k:list(v) for k,v in ABLATIONS.items()}},
        "availability":{"implicit_package":False,"lightfm_package":False,"manual_bm25":True,"torch_bpr":True,"deep_sequence_model":False}}
    (OUT/"general_metadata.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    manifest={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in OUT.iterdir() if path.is_file() and path.suffix!=".parquet" and path.name!="manifest.sha256.json"}
    (OUT/"manifest.sha256.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summary.to_dict("records"),"thresholds":thresholds,"bootstrap":bootstrap},default=str));return 0


if __name__=="__main__":raise SystemExit(main())
