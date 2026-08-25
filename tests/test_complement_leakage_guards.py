"""Garde-fous anti-fuite du complement panier.

Six garanties exigees apres correction :

1. changer la cible sans changer le contexte ne modifie aucun score ;
2. la categorie de la cible est structurellement inaccessible au scoring ;
3. le produit masque est absent du contexte et des recommandations ;
4. les ex aequo ne favorisent pas les identifiants bas ;
5. une permutation des identifiants ne change pas les metriques ;
6. aucune information posterieure au cutoff n'entre dans l'apprentissage.
"""
from __future__ import annotations

import ast
import inspect
import json
from collections import Counter

import numpy as np
import pandas as pd
import pathlib
import pytest

from src.config.settings import PROJECT_ROOT
from src.recsys import complement as core

REPORTS = PROJECT_ROOT / "reports" / "advanced"
RANKING = PROJECT_ROOT / "models" / "advanced" / "recommendation_ranking"


def _executable_source(path) -> str:
    """Source privee de ses docstrings et commentaires.

    Les modules corriges CITENT l'ancienne ligne fautive pour documenter la
    correction ; seul le code reellement execute doit etre inspecte.
    """
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _honest() -> dict:
    return json.loads((REPORTS / "complement_honest_baseline.json").read_text(encoding="utf-8"))


def _toy_orders(n_orders: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    products = ["PRD%06d" % i for i in range(60)]
    categories = {p: "CAT%d" % (i % 5) for i, p in enumerate(products)}
    rows = []
    start = pd.Timestamp("2025-02-01")
    for order in range(n_orders):
        size = int(rng.integers(2, 5))
        chosen = rng.choice(products, size=size, replace=False)
        for product in chosen:
            rows.append({"order_id": "CMD%06d" % order, "produit_key": product,
                         "categorie": categories[product],
                         "date_commande": start + pd.Timedelta(days=order // 8)})
    return pd.DataFrame(rows)


def _state(frame: pd.DataFrame):
    cooccurrence, popularity, category_popularity = core.train_statistics(frame)
    tiebreak = core.tiebreak_order(frame.produit_key.unique())
    return cooccurrence, popularity, category_popularity, tiebreak


# ---------------------------------------------------------- garanties 1 et 2


def test_scoring_signature_cannot_receive_the_target():
    """Aucun parametre ne permet de transmettre la cible ou ses attributs."""
    parameters = set(inspect.signature(core.candidate_scores).parameters)
    assert parameters == {"context", "context_categories", "cooccurrence",
                          "popularity", "category_popularity"}
    for forbidden in ("target", "cible", "target_category", "cat"):
        assert forbidden not in parameters
    source = _executable_source(inspect.getsourcefile(core))
    assert "produit_key.eq(target)" not in source
    assert ".eq(target)" not in source


def test_changing_the_target_never_changes_the_scores():
    """Garantie 1 : a contexte constant, les scores sont identiques."""
    orders = _toy_orders()
    cooccurrence, popularity, category_popularity, tiebreak = _state(orders)
    context = {"PRD000001", "PRD000002"}
    context_categories = sorted({"CAT1", "CAT2"})
    reference = core.candidate_scores(context, context_categories, cooccurrence,
                                      popularity, category_popularity)
    # La fonction n'a aucun moyen de connaitre la cible : on verifie que le
    # resultat est identique quelle que soit la cible envisagee par ailleurs.
    for _ in range(3):
        again = core.candidate_scores(context, context_categories, cooccurrence,
                                      popularity, category_popularity)
        for name in reference:
            assert dict(reference[name]) == dict(again[name]), name


def test_target_category_is_not_reachable_from_the_context():
    """Garantie 2 : une cible dont la categorie est absente du contexte ne
    peut pas etre favorisee par `popularite_categorie_contexte`."""
    orders = _toy_orders()
    cooccurrence, popularity, category_popularity, tiebreak = _state(orders)
    categories = orders.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()
    context = {"PRD000000", "PRD000005"}          # CAT0 et CAT0
    context_categories = sorted({categories[x] for x in context})
    assert context_categories == ["CAT0"]
    scores = core.candidate_scores(context, context_categories, cooccurrence,
                                   popularity, category_popularity)
    scored = set(scores["popularite_categorie_contexte"])
    off_category = {p for p, c in categories.items() if c != "CAT0"}
    assert not (scored & off_category), (
        "le generateur categorie a score des produits hors des categories du contexte")


# --------------------------------------------------------------- garantie 3


def test_masked_product_is_absent_from_context_and_recommendations():
    orders = _toy_orders()
    cooccurrence, popularity, category_popularity, tiebreak = _state(orders)
    categories = orders.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()
    checked = 0
    for _, group in orders.groupby("order_id"):
        items = list(dict.fromkeys(group.produit_key))
        target = core.masked_target(items)
        context = set(items) - {target}
        assert target not in context
        scores = core.score_all(context, sorted({categories[x] for x in context}),
                                cooccurrence, popularity, category_popularity, tiebreak)
        for name, values in scores.items():
            top = core.rank(values, context, popularity, tiebreak, 20)
            assert not (set(top) & context), name + " recommande un article du contexte"
            assert len(top) == len(set(top)), name + " contient un doublon"
        checked += 1
        if checked >= 40:
            break
    assert checked == 40


# --------------------------------------------------------------- garantie 4


def test_ties_do_not_favour_low_identifiers():
    """Garantie 4 : a scores egaux et popularites egales, le Top-k ne doit pas
    etre le prefixe lexical du catalogue."""
    products = ["PRD%06d" % i for i in range(300)]
    tiebreak = core.tiebreak_order(products)
    scores = Counter({p: 1.0 for p in products})
    popularity = Counter({p: 1 for p in products})
    top = core.rank(scores, set(), popularity, tiebreak, 10)
    assert top != products[:10], "le departage suit l'ordre lexical"
    lexical_rank = [products.index(p) for p in top]
    assert np.mean(lexical_rank) > 30, (
        "le Top-10 des ex aequo reste concentre sur les identifiants bas")


def test_tiebreak_permutation_is_not_the_lexical_order():
    products = ["PRD%06d" % i for i in range(300)]
    tiebreak = core.tiebreak_order(products)
    assert sorted(tiebreak.values()) == list(range(300))
    positions = [tiebreak[p] for p in products]
    assert abs(np.corrcoef(np.arange(300), positions)[0, 1]) < .2


def test_rank_refuses_products_missing_from_the_tiebreak_table():
    tiebreak = core.tiebreak_order(["PRD000000", "PRD000001"])
    with pytest.raises(KeyError):
        core.rank(Counter({"PRD000009": 1.0}), set(), Counter({"PRD000009": 1}), tiebreak, 5)


# --------------------------------------------------------------- garantie 5


def _evaluate(orders, model, targets=None) -> float:
    """NDCG@10 moyen. `targets` fige la cible par commande, ce qui permet de
    comparer deux etiquetages sur EXACTEMENT le meme probleme."""
    cooccurrence, popularity, category_popularity, tiebreak = _state(orders)
    categories = orders.drop_duplicates("produit_key").set_index("produit_key").categorie.to_dict()
    values = []
    for order_id, group in orders.groupby("order_id"):
        items = list(dict.fromkeys(group.produit_key))
        target = targets[order_id] if targets else core.masked_target(items)
        context = set(items) - {target}
        scores = core.score_all(context, sorted({categories[x] for x in context}),
                                cooccurrence, popularity, category_popularity, tiebreak)
        top = core.rank(scores[model], context, popularity, tiebreak, 20)
        values.append(core.evaluate_unit(top, target)["ndcg@10"])
    return float(np.mean(values))


def _original_targets(orders):
    return {order_id: core.masked_target(list(dict.fromkeys(group.produit_key)))
            for order_id, group in orders.groupby("order_id")}


def test_metrics_are_stable_under_identifier_permutation():
    """Garantie 5 : renommer les produits ne doit pas deplacer la metrique.

    Le renommage inverse l'ordre lexical. La cible de chaque commande est
    transportee par la meme bijection, de sorte que le probleme evalue reste
    identique : seuls les noms changent.
    """
    orders = _toy_orders()
    products = sorted(orders.produit_key.unique())
    mapping = dict(zip(products, reversed(products)))
    targets = _original_targets(orders)
    relabelled = orders.assign(produit_key=orders.produit_key.map(mapping))
    relabelled_targets = {order: mapping[item] for order, item in targets.items()}

    for model in ("cooccurrence_item_item", "popularite_globale", "rrf_contexte"):
        before = _evaluate(orders, model, targets)
        after = _evaluate(relabelled, model, relabelled_targets)
        assert abs(before - after) < .01, (
            model + " : metrique sensible au renommage ("
            + str(before) + " -> " + str(after) + ")")


def test_lexical_tiebreak_would_be_detected_by_the_permutation_test():
    """Controle de sensibilite : la garantie 5 doit pouvoir echouer.

    Meme permutation, mais departage lexical. Comme la cible du protocole est
    l'article lexicalement premier du panier, l'ecart doit alors etre nettement
    plus grand, ce qui prouve que le test precedent n'est pas vide.
    """
    orders = _toy_orders()
    products = sorted(orders.produit_key.unique())
    mapping = dict(zip(products, reversed(products)))
    targets = _original_targets(orders)
    relabelled = orders.assign(produit_key=orders.produit_key.map(mapping))
    relabelled_targets = {order: mapping[item] for order, item in targets.items()}

    def evaluate_lexical(frame, order_targets) -> float:
        cooccurrence, popularity, category_popularity = core.train_statistics(frame)
        table = {p: index for index, p in enumerate(sorted(frame.produit_key.unique()))}
        categories = (frame.drop_duplicates("produit_key")
                      .set_index("produit_key").categorie.to_dict())
        values = []
        for order_id, group in frame.groupby("order_id"):
            items = list(dict.fromkeys(group.produit_key))
            target = order_targets[order_id]
            context = set(items) - {target}
            scores = core.candidate_scores(context, sorted({categories[x] for x in context}),
                                           cooccurrence, popularity, category_popularity)
            pool = scores["popularite_globale"]
            ordered = sorted((y for y, v in pool.items() if v > 0 and y not in context),
                             key=lambda y: (-pool[y], table[y]))[:20]
            values.append(core.evaluate_unit(ordered, target)["ndcg@10"])
        return float(np.mean(values))

    gap_lexical = abs(evaluate_lexical(orders, targets)
                      - evaluate_lexical(relabelled, relabelled_targets))
    gap_neutral = abs(_evaluate(orders, "popularite_globale", targets)
                      - _evaluate(relabelled, "popularite_globale", relabelled_targets))
    assert gap_lexical > gap_neutral, (
        "le controle de sensibilite n'a pas detecte le biais lexical (lexical="
        + str(gap_lexical) + ", neutre=" + str(gap_neutral) + ")")


# --------------------------------------------------------------- garantie 6


def test_training_statistics_never_see_post_cutoff_orders():
    orders = _toy_orders()
    cutoff = orders.date_commande.quantile(.6)
    train = orders[orders.date_commande < cutoff]
    future = orders[orders.date_commande >= cutoff]
    only_future = set(future.produit_key) - set(train.produit_key)
    _, popularity, _ = core.train_statistics(train)
    assert not (only_future & set(popularity)), "des produits posterieurs au cutoff sont appris"
    assert train.date_commande.max() < future.date_commande.min()


def test_published_windows_declare_a_strictly_prior_training_set():
    for row in _honest()["controles_temporels"]:
        assert row["train_strictly_before_test"] is True
        assert row["n_train_orders"] > 0
        assert row["n_test_orders"] > 0


# ------------------------------------------------- statut metier et invalidation


def test_official_status_is_none_validated():
    status = _honest()["statut_metier"]
    assert status["basket_complement_model"] == "none_validated"
    assert status["basket_complement_baseline"] == "popularite_globale"
    assert status["reason"] == "no_complementarity_signal"
    assert _honest()["modele_promu"] is None


def test_every_challenger_fails_the_promotion_gate():
    for name, decision in _honest()["decisions"].items():
        assert decision["promoted"] is False, name


def test_invalidated_metrics_are_labelled_and_preserved():
    invalid = _honest()["resultats_invalides"]
    assert invalid["leave_one_item_out_F2_F4"]["status"] == "invalidated_due_to_target_category_leakage"
    assert invalid["leave_one_item_out_F2_F4"]["ndcg@10"] == pytest.approx(0.21264, abs=1e-5)
    legacy = invalid["legacy_end_to_end"]
    assert legacy["status"] == "invalidated_due_to_in_sample_evaluation_without_temporal_split"
    assert legacy["ndcg@10"] == pytest.approx(0.04846, abs=1e-5)
    archive = json.loads((RANKING / "invalidated" / "INVALIDATION.json").read_text(encoding="utf-8"))
    assert archive["status"] == "invalidated_due_to_target_category_leakage"
    assert len(archive["archived_files"]) >= 8


def test_corrected_paths_all_import_the_shared_scoring_core():
    for name in ("complement_end_to_end.py", "complement_candidate_pilot.py",
                 "complement_honest_baseline.py"):
        path = PROJECT_ROOT / "src" / "experiments" / name
        assert "from src.recsys.complement import" in path.read_text(encoding="utf-8"), name
        assert ".eq(target)" not in _executable_source(path), name


def test_candidate_gate_collapses_without_the_leaked_category():
    payload = json.loads((RANKING / "complement_candidate_metadata.json").read_text(encoding="utf-8"))
    assert payload["candidate_gate_ge_050"] is False
    for value in payload["union_recall_at50"][1:]:
        assert value < .50
    assert payload["leakage_correction"]["previous_union_recall_at50"][3] > .90
