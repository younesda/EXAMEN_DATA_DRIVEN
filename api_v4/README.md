# API produit V4 — pricing et recommandation (experimentation academique)

Service de scoring academique sur donnees synthetiques
(`synthetic_academic_experiment`), distinct de l'interface V2 (`api/`).
Documentation complete : `reports/v4_training/08_documentation_produit.md`.

## Lancement local

```bash
python -m uvicorn api_v4.main:app --host 127.0.0.1 --port 8099
```

Puis `http://127.0.0.1:8099/docs` pour la documentation interactive.

## Regenerer les instantanes de catalogue (apres tout reentrainement)

```bash
python -m src.pipelines.finalize_v4_product
```

## Tests

```bash
python -m pytest api_v4/tests/test_api.py -q
```

## Endpoints

| Methode | Route | Role |
|---|---|---|
| GET | `/health` | etat du service et des modeles charges |
| GET | `/metadata` | fiche de statut consolidee de chaque modele |
| POST | `/recommendations` | recommandation d'achat (`CatBoostRanker`) |
| POST | `/recommendations/cart` | recommandation d'ajout panier (`pointwise_conversion`) |
| POST | `/pricing/simulation` | simulation pricing (baseline mediane produit) |
| GET | `/metrics` | compteurs operationnels (requetes, replis, erreurs) |
| GET | `/docs` | documentation interactive (Swagger, generee par FastAPI) |
