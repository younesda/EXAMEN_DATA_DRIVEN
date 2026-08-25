"""Métriques V1 figées — rapports data science (aucune écriture Supabase)."""

MODELS = {
    "forecasting": {
        "id": "forecasting",
        "name": "Forecasting demande",
        "code": "AutoETS + Naive",
        "status": "V1 validée",
        "status_tone": "ok",
        "usage": "Planification cumulée 7 / 14 / 30 jours par produit",
        "interdit": "Prévision exacte au jour le jour",
        "wape_30": 27.72,
        "wape_7": 46.2,
        "wape_daily": 109.0,
        "horizon_90": "Disponible, expérimental",
        "v2_target": "WAPE 30j ≤ 26,5 %",
        "note": (
            "Fiable pour des volumes agrégés à 30 jours (commandes fournisseurs, budget). "
            "~50 % de jours sans vente : la demande est intermittente."
        ),
    },
    "pricing": {
        "id": "pricing",
        "name": "Pricing dynamique",
        "code": "Simulateur de remises",
        "status": "V1 exploratoire",
        "status_tone": "warn",
        "usage": "Simulation sous plancher de marge 5 %, validation humaine obligatoire",
        "interdit": "Application automatique des remises / promesse de prix optimal",
        "simulations": 288,
        "repartition": {"0%": 240, "5%": 29, "10%": 17, "15%": 2},
        "wape_qty": 107.1,
        "high_confidence": 0,
        "v2_target": "WAPE quantité < 100 % · biais ≤ 10 %",
        "note": (
            "Le prix catalogue n'a jamais varié. Seules les promotions ponctuelles "
            "offrent un signal. Résultats observationnels, pas causaux."
        ),
    },
    "recsys": {
        "id": "recsys",
        "name": "Recommandation",
        "code": "Popularité globale",
        "status": "V1 baseline",
        "status_tone": "info",
        "usage": "Bloc générique « Produits populaires » (accueil, catégorie)",
        "interdit": "Présenter la reco comme personnalisée",
        "recall10": 7.59,
        "ndcg10": 4.41,
        "coverage": 5.42,
        "fallback": "Popularité récente",
        "v2_target": "Recall@10 ≥ 8 % · NDCG@10 ≥ 4,7 % · couverture ≥ 10 %",
        "note": (
            "La personnalisation testée n'a pas battu la popularité de façon stable. "
            "Tous les clients d'un même segment reçoivent la même liste."
        ),
    },
}

ACTIVITY = [
    {"t": "il y a 2 min", "msg": "Forecast AutoETS — recalcul horizon 30j", "ok": True},
    {"t": "il y a 18 min", "msg": "Garde-fou pricing : 0 simulation sous le coût", "ok": True},
    {"t": "il y a 1 h", "msg": "Reco popularité — couverture catalogue 5,42 %", "ok": False},
    {"t": "il y a 3 h", "msg": "156 tests anti-fuite temporelle : tous verts", "ok": True},
    {"t": "hier", "msg": "Aucun modèle déployé en production (validation métier)", "ok": True},
]
