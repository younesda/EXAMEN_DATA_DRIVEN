# 06 — Tests de l'interface

Playwright n'est pas installé sur ce poste. Les tests ont été conduits par
**pilotage réel d'un navigateur** (DOM, exécution JavaScript, mesures de mise en
page) contre l'API locale, complétés par des tests d'intégration HTTP.

## Captures d'écran : non disponibles

Le panneau navigateur de cet environnement ne composite pas d'images : toute
tentative de capture échoue (« the Browser pane is not displayed »). **Aucune
capture desktop ou mobile n'a donc pu être produite.** Je ne les présente pas
comme livrées.

Substitut fourni : mesures de mise en page à trois largeurs et extraction du
contenu rendu, ci-dessous. Pour produire les captures vous-même :

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8013
```
puis ouvrir `http://127.0.0.1:8013/` et capturer en 375 px et 1280 px.

## Navigation

Les six routes ont été visitées et rendues sans erreur console
(`read_console_messages` : aucun message d'erreur).

| Route | Rendu vérifié |
|---|---|
| `#/accueil` | 3 cartes de module, métriques, avertissement méthodologique |
| `#/performances` | métriques par domaine, sens de lecture, limites, historique invalidé |
| `#/prevision` | catalogue de 300 produits, formulaire, résultat, graphique, tableau |
| `#/pricing` | remises supportées par produit, tableau de scénarios |
| `#/recommandation` | Top-10, origine de la sortie, avertissements |
| `#/technique` | version, contrôles, modèles, limites, champ clé |

## Affichage mobile et desktop

| Largeur | Grilles | Débordement horizontal |
|---|---|---|
| 375 px | 1 colonne | **aucun** |
| 500 px | 1 colonne | **aucun** |
| 1280 px | 3 colonnes (accueil), 2 colonnes (formulaires) | **aucun** |

La navigation défile horizontalement sur mobile (`nav_scrollable: true`) ; la
page elle-même ne défile jamais latéralement.

## Formulaires et résultats

**Prévision** — « Charger un exemple » déclenche une prévision complète :

```
Total prévu sur 30 jours : 65,7 unités — PRD000127
Réalisé observé : 65,0 unités sur la même fenêtre
Modèle : LightGBM_direct_per_horizon
Nature : backtest validé, non recalculé en direct
Cutoff : 01 juil. 2026
```

Graphique SVG présent, tableau de 30 lignes, bouton d'export CSV opérationnel.
L'avertissement sur la demande intermittente est affiché.

**Simulateur de remise** — sur PRD000127, quatre remises supportées :

| Remise | Prix après remise | Quantité | Marge | Garde-fous |
|---|---|---|---|---|
| 0 % | 4 840 FCFA | 2,97 | 12,42 % | **Conforme** |
| 10 % | 4 356 FCFA | — | 2,69 % | **Bloquée** — marge sous le plancher de 5 % |
| 15 % | 4 114 FCFA | — | −3,04 % | **Bloquée** — prix sous le coût |
| 25 % | 3 630 FCFA | — | −16,78 % | **Bloquée** — prix sous le coût |

Chaque blocage est expliqué en français sous la ligne concernée, et les
scénarios valides restent affichés. Le statut `exploratory_non_causal`, le
niveau de confiance et l'obligation de validation humaine sont visibles.

**Recommandation** — mode panier sur PRD000127 : 10 produits, l'article du
contexte est exclu. Affiché : « Complément panier — repli sur la popularité
globale », « Personnalisation validée : non », et l'avertissement de couverture
catalogue.

## Textes méthodologiques présents

- « Données synthétiques — projet académique » (pied de page, toutes les pages)
- « Référence corrigée après audit » (page Performances)
- « Usage supervisé uniquement » / « Validation humaine requise » (pricing)
- « Aucune personnalisation forte n'est démontrée » (recommandation)
- « backtest validé, non recalculé en direct » (prévision)

## Absence d'anciennes métriques invalidées

Balayage du texte rendu de toutes les pages pour 0,4164 · 0,437 · 0,213 ·
0,1006 · 0,0485 → **aucune occurrence**. Vérifié aussi par test automatisé sur
les trois fichiers statiques.

Le terme « prix optimal » n'apparaît nulle part, même sous forme niée : la
formulation a été retirée pour qu'aucun extrait d'écran ne puisse le montrer
hors contexte.

## Liens Swagger

`/docs` et `/openapi.json` répondent 200 et sont liés depuis le pied de page et
la page État technique.

## États gérés

| État | Traitement |
|---|---|
| Chargement | loader animé, respecte `prefers-reduced-motion` |
| Cold start | au-delà de 3,5 s, message « le serveur sort peut-être de veille » |
| Vide | message explicite, jamais un tableau vide |
| Erreur | message français, code stable, bouton Réessayer, saisie conservée |
| Double clic | verrou logiciel + bouton désactivé |
| Trace d'exécution | jamais affichée ; vérifié par test |
