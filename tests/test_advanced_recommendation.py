import numpy as np
from scipy import sparse

from src.experiments.advanced_recommendation import (
    ABLATIONS, RANK_FEATURES, bm25_item_similarity, evaluate, paired_bootstrap,
)


def test_bm25_similarity_is_deterministic_and_has_zero_diagonal():
    matrix=sparse.csr_matrix([[1,0,2],[0,1,1],[1,1,0]],dtype=float)
    first=bm25_item_similarity(matrix);second=bm25_item_similarity(matrix)
    np.testing.assert_allclose(first,second);np.testing.assert_allclose(np.diag(first),0)


def test_end_to_end_keeps_clients_without_eligible_discovery_truth():
    metrics,rows=evaluate({"A":[0],"B":[1]},{"A":{0},"B":set()},3)
    assert metrics["n_clients"]==2 and metrics["n_eligible_truth"]==1
    assert metrics["recall_end_to_end"]==.5 and rows.loc[rows.client_key.eq("B"),"recall"].item()==0


def test_ranker_ablations_are_declared_without_purchase_or_promotion_leakage():
    assert "ranker_no_web" in ABLATIONS and "ranker_no_stock" in ABLATIONS and "ranker_no_orders" in ABLATIONS
    assert all("purchase" not in feature and "promotion" not in feature for feature in RANK_FEATURES)


def test_recommendation_bootstrap_is_deterministic():
    import pandas as pd
    frame=pd.DataFrame({"recall_diff":[-.1,0,.1],"ndcg_diff":[-.05,.01,.04]})
    assert paired_bootstrap(frame,draws=200)==paired_bootstrap(frame,draws=200)
