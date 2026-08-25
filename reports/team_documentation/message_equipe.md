# Message pour l'équipe

Texte court, prêt à être copié dans une conversation d'équipe.

---

Bonjour à tous,

Le projet prévision / tarification / recommandation est terminé. Voici
l'essentiel.

**Ce qui a été fait**

Quatre itérations, un audit indépendant qui a détecté et corrigé deux fuites
de cible, puis une contre-expertise statistique menée avec du code entièrement
réécrit. Le tout est servi par une API et une console web en français,
déployées sur un service dédié.

**Modèles retenus**

- Prévision 30 jours : `LightGBM_direct_per_horizon` — WAPE macro 0,25831,
  biais −0,02589
- Prévision quotidienne : `CrostonOptimized`
- Recommandation achat : `CatBoostRanker` — gain NDCG@10 +8,57 %
- Recommandation panier : `pointwise_conversion` — gain NDCG@10 +7,70 %
- Recommandation consultation : exploratoire, **non promue** (gain non
  significatif après vérification indépendante)
- Tarification : `baseline_mediane_produit` — aucun modèle d'apprentissage
  n'a battu cette référence

**Points d'entrée**

`/` console web, `/docs` documentation, `/health`, `/metadata`, `/metrics`,
`/forecast`, `/recommendations`, `/recommendations/cart`,
`/pricing/simulation`.

**Trois limites à garder en tête**

1. Les données sont **synthétiques**. Aucun chiffre n'est une performance
   commerciale réelle.
2. La tarification est une **simulation**. Aucun effet causal n'est estimé et
   aucun prix optimal n'est calculé : la remise et l'identité produit sont
   confondues dans cette expérience, ce qui interdit toute lecture causale.
3. Une WAPE de 0,25831 **n'est pas** une exactitude de 90 %. La demande est
   très intermittente, ce qui gonfle mécaniquement l'erreur relative.

**Ce qui reste à faire**

Rejouer le protocole sur données réelles, conduire un test A/B pour valider
les gains de recommandation en ligne, et ajouter l'authentification avant tout
usage au-delà de la démonstration.

**Statut : démonstration académique, pas un service de production.**

Le rapport complet est disponible dans la documentation d'équipe du dépôt.
