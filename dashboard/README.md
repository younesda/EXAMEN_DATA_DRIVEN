# Teranga BI — Dashboard e-commerce (ISM Master 2 Big Data)

Application web de **Business Intelligence** pour le projet **data-driven pricing & recommandation** sur le jeu de données **Mozart** (e-commerce Sénégal, monnaie XOF).

## Sommaire

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Installation & lancement](#installation--lancement)
4. [Authentification](#authentification)
5. [Structure du warehouse](#structure-du-warehouse)
6. [Menus & contenu analytique](#menus--contenu-analytique)
7. [Responsive (tous écrans)](#responsive-tous-écrans)
8. [Filtres par vue](#filtres-par-vue)
9. [KPI calculés](#kpi-calculés)
10. [Résultats chiffrés & interprétation](#résultats-chiffrés--interprétation)
11. [Drill-down (clic graph / tableau)](#drill-down-clic-graph--tableau)
12. [Export Excel & PDF](#export-excel--pdf)
13. [API REST](#api-rest)
14. [Fichiers du projet](#fichiers-du-projet)
15. [Dépannage](#dépannage)

> Rapport fonctionnel détaillé (pourquoi / comment) : **`RAPPORT_DETAILLE.md`**.

---

## Vue d'ensemble

| Élément | Description |
|---------|-------------|
| **Backend** | Flask + `data_service.py` (agrégations BI) |
| **Frontend** | HTML/CSS/JS + **ECharts 5** (graphiques interactifs) |
| **Base** | Supabase PostgreSQL (schéma en étoile) via `DATABASE_URL` |
| **Fallback** | Mode démo si connexion impossible ou warehouse vide (RLS) |
| **ML** | 3 menus **Outils métier** (`ml_live.py` + cache) — prévisions, simulation prix, recommandation |

Le dashboard est organisé en **vues Analyse** + **3 outils métier**, chacune avec **filtres contextualisés** et **export dédié**.

---

## Architecture

```
┌─────────────┐     GET /api/dashboard?filtres     ┌──────────────────┐
│  app.html   │ ◄──────────────────────────────── │     app.py       │
│  app.js     │     JSON (KPI, séries, options)    │  (Flask routes)  │
│  app.css    │                                    └────────┬─────────┘
└─────────────┘                                             │
                                                            ▼
                                                   ┌──────────────────┐
                                                   │  data_service.py │
                                                   │  cache warehouse │
                                                   │  filtres + KPI   │
                                                   └────────┬─────────┘
                                                            │
                              ┌─────────────────────────────┴─────────────────────────────┐
                              ▼                                                           ▼
                    Supabase PostgreSQL                                         Mode démo synthétique
                    (dim_*, fact_*)                                             (_load_warehouse_demo)
```

**Flux de données :**

1. Au premier appel, `ensure_warehouse()` charge les tables dimension/fait en mémoire (cache).
2. `parse_filters()` traduit les query params HTTP en filtres métier.
3. `filter_ventes()` / `filter_stock()` réduisent les lignes.
4. `_assemble_from_warehouse()` calcule KPI, séries temporelles, agrégats région/catégorie/segment.
5. Le frontend `render()` met à jour cartes KPI, graphiques ECharts et tableaux.

`/api/refresh` force le rechargement du cache warehouse depuis Postgres.

---

## Installation & lancement

### Prérequis

- Python 3.10+
- Accès réseau au pooler Supabase (variable `DATABASE_URL`)

### Étapes

```bash
cd dashboard
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # puis renseigner DATABASE_URL
python app.py
```

Ouvrir **http://127.0.0.1:5055**

### Variables d'environnement (`.env`)

| Variable | Rôle |
|----------|------|
| `DATABASE_URL` | Connexion Postgres Supabase (pooler, schéma public) |
| `ADMIN_USER` | Login dashboard (défaut : `admin`) |
| `ADMIN_PASSWORD` | Mot de passe (défaut : `teranga2026`) |
| `FLASK_SECRET_KEY` | Clé session Flask |

---

## Authentification

- Route `/login` — formulaire simple session Flask.
- Routes `/` et `/api/*` protégées par `@login_required`.
- Identifiants démo : **admin / teranga2026** (configurables via `.env`).

---

## Structure du warehouse

Schéma **en étoile** (jeu Mozart) :

| Table | Rôle |
|-------|------|
| `dim_produit` | Produits, catégories, marques, prix catalogue |
| `dim_client` | Clients, région, segment, âge, appareil, source trafic |
| `dim_date` | Calendrier (année, mois, week-end…) |
| `dim_promotion` | Promotions actives |
| `fact_ventes` | Lignes de commande (montant net XOF, quantité, statut, clés étrangères) |
| `fact_evenements_web` | Funnel (view, add_to_cart, purchase) |
| `fact_stock` | Niveaux de stock par produit |

La connexion directe Postgres contourne les restrictions **RLS** Supabase côté API REST.

---

## Menus & contenu analytique

### 1. Dashboard (vue globale)

- **KPI** : CA net, marge brute, commandes, panier moyen
- **Graphiques** : évolution CA (30j / mensuel / annuel + compare N-1), donut catégories, funnel e-commerce, segments clients
- **Filtres** : période, année, mois, région

### 2. Ventes & rentabilité

- **KPI** : CA, unités, part promo, conversion
- **Graphiques** : CA par région, promo vs plein tarif, CA & unités mensuels, waterfall rentabilité
- **Tableau** : 12 dernières commandes (recherche texte)
- **Filtres** : période, année, mois, week-end, promo, statut, région, recherche commande

### 3. Produits & catégories

- **KPI** : nombre produits, catégories, promos actives, multi-produits
- **Graphiques** : barres CA par catégorie, part promotions
- **Filtres** : catégorie, marque, produit, promo

### 4. Clients & parcours

- **KPI** : clients uniques, VIP, loyaux, inactifs, churn (≥ 2 ans)
- **VIP** : achats très fréquents (≥ 1,5 cmd/mois ou ≤ 14 j entre cmd)
- **Loyaux** : réguliers, moins fréquents que les VIP
- **Inactifs** : 6 mois – 2 ans sans achat
- **Churn** : ≥ 2 ans sans achat (partis)
- 4 panneaux + Excel dédié par statut
- **Graphiques** : appareils, sources trafic, barres région, jauges abandon
- **Filtres** : année, mois, région, segment, âge, client, appareil, source, recherche

### 5. Stock & réappro

- **KPI** : rotation, couverture (jours), rupture %, qualité données
- **Liste** : alertes stock (produits sous seuil) — clic → modale
- **Filtres** : catégorie, marque, produit, niveau stock

### 6. Outils métier (3 menus)

| Menu | Rôle |
|------|------|
| Prévisions ventes | Erreurs de prévision 7/30 j, réel vs prévu |
| Simulation prix | Scénarios volume / marge (rien publié en magasin) |
| Recommandation | Ordre de mise en avant vs best-sellers |

Cache local + API Render. Voir `RAPPORT_DETAILLE.md` pour le détail.

---

## Responsive (tous écrans)

| Écran | Comportement |
|-------|----------------|
| Desktop | Sidebar fixe · contenu seul scroll |
| Tablette (≤ 1100 px) | Menu en bandeau · 1 colonne |
| Mobile (≤ 720 px) | Filtres empilés · tableaux scroll H · modale large |
| Très petit | Densité typo / boutons adaptée |

---

## Filtres par vue

Chaque vue affiche un bloc **filter-shell** :

- Grille de champs avec libellés (select + recherche ventes)
- **Rafraîchir** (icône ↻) — recharge le warehouse depuis Postgres (`/api/refresh`) et relance les graphiques avec animation

Les filtres actifs sont synchronisés entre vues pour une même clé (ex. `region` partagée Dashboard / Ventes / Clients).

| Clé filtre | Exemples de valeurs |
|------------|-------------------|
| `periode` | `30d`, `3m`, `6m`, `1y` |
| `annee`, `mois` | Valeurs issues de `dim_date` |
| `region` | Dakar, Thiès, … |
| `categorie`, `marque`, `produit` | Dimensions produit |
| `segment`, `age`, `appareil`, `source_trafic` | Dimensions client |
| `weekend` | `semaine`, `weekend` |
| `promo` | `oui`, `non` |
| `statut` | Statuts commande |
| `stock_level` | `rupture`, `faible`, `ok` |
| `q` | Recherche texte commandes (vue Ventes) |

Le bandeau header affiche : date du jour · source données (Supabase live / démo) · nombre de filtres actifs · lignes ventes filtrées.

---

## KPI calculés

Principaux indicateurs (`data_service.py` → clé `kpis` du JSON) :

| KPI | Formule / source |
|-----|------------------|
| CA net | Somme `montant_net_xof` ventes filtrées |
| Marge brute | CA − coût produits ; `margin_pct` = marge / CA |
| Commandes | Commandes distinctes (`order_id`) |
| Panier moyen | CA / commandes |
| Conversion | Achats funnel / sessions |
| Abandon panier | (Paniers − Commandes) / Paniers |
| Part promo | CA avec `promo_key` / CA total |
| CLV moyen | CA / acheteurs uniques |
| Rotation stock | Ventes / stock moyen (approx.) |
| Qualité données | Complétude clés & dimensions |

Deltas (`ca_delta`, `orders_delta`, …) : comparaison mois courant vs mois précédent.

---

## Résultats chiffrés & interprétation

Chiffres issus du warehouse **Supabase live** (jeu Mozart, sans filtre, ~80 130 lignes `fact_ventes`).

### Synthèse globale

| Indicateur | Valeur | Pourquoi c'est important |
|------------|--------|---------------------------|
| **CA net** | **11,78 Md F** | Volume d'activité e-commerce sur la période ; base de toute analyse pricing/reco |
| **Marge brute** | **23,9 %** (~2,81 Md F) | Santé économique : chaque point de marge perdu sur promo pricing impacte ~118 M F |
| **Commandes** | **47 368** | Fréquence d'achat ; panier moyen = CA / commandes |
| **Panier moyen** | **~249 K F** | Levier CLV ; comparer par région/segment pour cibler les campagnes |
| **Unités vendues** | **147 034** | Demande physique ; alimente forecasting et rotation stock |
| **Part promo** | **14,0 %** | Part du CA sous promotion — modèle pricing V1 encore faible (WAPE qty ~107 %) |
| **Conversion** | **~20,0 %** | 84 319 achats / 422 303 sessions — performance marketing/UX |
| **Abandon panier** | **~27,2 %** | (115 818 paniers − 84 319 commandes) / paniers — levier UX & relance |
| **Paniers multi-produits** | **45,1 %** | Potentiel cross-sell ; le recsys V1 (Recall@10 ~7,6 %) peut encore progresser |
| **CLV proxy / acheteurs** | **~249 K F** | CA / acheteurs uniques |
| **CA segment VIP** | **7,8 %** | Les VIP ne dominent pas le CA : base client relativement homogène |
| **Rotation stock** | **3,48×** | Stock vendu ~3,5 fois sur la période — réapprovisionnement actif |
| **Rupture** | **0 %** | Pas de produit à stock zéro au moment du snapshot |
| **Qualité données** | **100 %** | Clés produit/client/date complètes → KPI fiables |

### Funnel e-commerce

| Étape | Volume | Interprétation |
|-------|--------|----------------|
| Sessions | 422 303 | Trafic total |
| Paniers | 115 818 | 27,4 % des sessions créent un panier |
| Commandes | 84 319 | 72,8 % des paniers convertissent ; 20,0 % des sessions achètent |

**Insight :** l'abandon se situe surtout **avant** le panier (trafic → panier) et **entre** panier et paiement. Deux leviers distincts : acquisition/UX fiche produit vs checkout.

### Top catégories (CA)

| Catégorie | CA (ordre de grandeur) | Part estimée |
|-----------|------------------------|--------------|
| Électronique & High-Tech | 5,74 Md F | ~49 % |
| Téléphonie & Accessoires | 3,53 Md F | ~30 % |
| Maison & Cuisine | 718 M F | ~6 % |
| Mode & Vêtements | 442 M F | ~4 % |
| Bébé & Enfant | 414 M F | ~4 % |

**Insight :** deux catégories concentrent **~79 %** du CA. Le pricing dynamique et le stock critique doivent prioriser ce duo.

### Segments clients

| Segment | CA | Clients (acheteurs) |
|---------|-----|---------------------|
| Nouveau | 4,12 Md F | 1 739 |
| Occasionnel | 4,15 Md F | 1 781 |
| Régulier | 2,59 Md F | 1 090 |

**Insight :** les nouveaux et occasionnels génèrent plus de CA que les réguliers (plus nombreux ou paniers plus élevés). Fidélisation = enjeu stratégique.

### Régions (extrait)

| Région | CA (sans filtre) |
|--------|------------------|
| Touba | ~1,22 Md F |
| Diourbel | ~1,20 Md F |
| Saint-Louis | ~1,20 Md F |
| **Dakar** (filtre seul) | **~1,16 Md F** · 7 927 lignes · 4 675 commandes |

**Insight :** le CA est **géographiquement dispersé** au-delà de Dakar — logistique multi-hub justifiée.

### Exemple filtre : Dakar seule

- CA **1,16 Md F** (≈ 10 % du total national)
- **4 675** commandes → panier moyen local ~248 K F (proche du global)

### Modèles V1 — lecture métier

| Modèle | Métrique | Valeur | Conclusion |
|--------|----------|--------|------------|
| Forecasting | WAPE 30j | 27,72 % | Utilisable pour agrégats 7/14/30 j, pas au jour le jour |
| Pricing | WAPE qty | 107,1 % | Signal promo faible ; pas d'automatisation |
| Recsys | Recall@10 | 7,59 % | Baseline popularité ; personnalisation V2 nécessaire |

**Pourquoi séparer BI et Modèles ?** Le dashboard live reflète le **réel warehouse** ; la page Modèles affiche des **métriques offline figées** (rapports data science) sans les mélanger aux KPI opérationnels.

---

## Drill-down (clic graph / tableau)

Interaction **clic → modal de détail** avec **commentaire analytique** (part du CA, interprétation métier, lien avec les KPI globaux) :

| Zone cliquable | Comportement |
|----------------|--------------|
| Barres CA (Dashboard) | Détail période + bouton filtrer année/mois |
| Donuts catégorie / segment | Détail + filtrer catégorie ou segment |
| Barres région | Détail + filtrer région |
| Donut promo | Filtrer avec/sans promo |
| Lignes tableau commandes | Fiche commande (ID, produit, région, montant, statut) |
| Listes statistiques | Même drill que les graphiques associés |
| Alertes stock | Filtrer par produit |

Le modal propose **Explorer avec ce filtre** quand un filtrage métier est possible ; **Échap** ou clic backdrop ferme le modal.

**Animations UI :** entrée des KPI et panneaux, modal animé, rotation de l'icône Rafraîchir, fond glassmorphism en mouvement léger.

Graphiques : dégradés vert, ombres, animation ECharts, curseur pointer.

### Analyse objectif dans la modale (graphique CA)

Quand vous cliquez sur une barre du graphique **Evolution du CA** :

| Mode | Référence comparée |
|------|-------------------|
| **Comparer N-1** coché | Barre N-1 (sombre) — objectif = même période année précédente simulée |
| **Comparer N-1** décoché | Période précédente (jour/mois/année selon la vue) |
| Premier point de la série | Moyenne sur la période affichée |

La modale affiche :
- **Objectif atteint** (badge vert) ou **Manque X F** (badge rouge)
- Référence, écart, variation %, **reste à combler** si non atteint
- Commentaire explicatif en français

Même logique sur catégories (vs moyenne), régions, segments, funnel (vs étape précédente), commandes (vs panier moyen ~249 K F).

---

## Export Excel & HTML (par menu)

Boutons **Excel** et **HTML** dans le header. Chaque menu exporte **son** contenu (pas un export global unique).

### Excel (présentation type image rapport)

Fichier `.xlsx` ExcelJS, feuille principale :

1. Titre **Teranga BI — Données de l'analyse**
2. Ligne méta : date · source · vue active
3. **Barre KPI** vert foncé (CA, commandes, unités, panier, marge, lignes…)
4. **Tableau détail** colonnes en majuscules + lignes zebra + filtre auto Excel
5. Feuille **Filtres** (filtres actifs)

| Menu | Contenu Excel |
|------|----------------|
| Dashboard / Ventes | Lignes vente : ID, COMMANDE, DATE, PRODUIT, CATEGORIE, QTE, PRIX, MONTANT, STATUT |
| Produits | Produit, catégorie, marque, commandes, qté, CA, lignes |
| Clients | Client, région, segment, âge, dates, commandes, **fréq. cmd/mois**, CA (+ feuille VIP) |
| Stock | Produit, catégorie, marque, stock, niveau, prix |
| Prévisions | Produits (réel/prévu/écart) + périodes de contrôle |
| Simulation prix | Catalogue prix/marge + scénarios |
| Recommandation | Popularité + usages validés |

### HTML (présentation classée)

Rapport `.html` autonome (Chart.js CDN) :

- Logo Teranga + badge **DONNÉES COMPLÈTES / FILTRÉES**
- Section **Indicateurs clés**
- **Rapport analytique** + encadré info (date, source, vue, nb lignes, chips filtres)
- **Visualisations graphiques** (2 charts interactifs, hover)
- Section **Données de l'analyse** (tableau détaillé)

Fichiers générés côté navigateur (`static/js/export.js`).

---

## Chargement optimal

| Moment | Action |
|--------|--------|
| Démarrage `python app.py` | Warm-up warehouse + payload toutes années + modèles API |
| Login réussi | Même précharge avant redirection |
| Ouverture dashboard | `load()` dashboard + `loadModelsLive()` en parallèle (cache JSON instantané) |
| Changement de menu | Pas de reload API — resize charts + paint ML |
| Filtres | Load immédiat (AbortController annule les requêtes obsolètes) |

CDN allégés : ECharts + ExcelJS uniquement (plus de SheetJS/jsPDF inutilisés).

---

## API REST

| Route | Méthode | Description |
|-------|---------|-------------|
| `/login` | GET/POST | Authentification |
| `/logout` | GET | Déconnexion |
| `/` | GET | Shell HTML dashboard |
| `/api/dashboard` | GET | Payload BI (filtres = query string) |
| `/api/refresh` | GET | Idem + `force=True` sur cache warehouse |

Exemple :

```
GET /api/dashboard?region=Dakar&annee=2024
```

Réponse JSON (extrait) :

```json
{
  "source": "supabase",
  "filtered_rows": 6182,
  "active_filters": { "region": "Dakar", "annee": "2024" },
  "filter_options": { "regions": ["Dakar", "..."], ... },
  "kpis": { "ca": 890000000, "margin_pct": 23.9, ... },
  "timeseries": { "labels": ["2024-01", ...], "values": [...] },
  "categories": [{ "name": "...", "value": ..., "delta": ... }],
  "regions": [...],
  "segments": [...],
  "funnel": { "view": ..., "add_to_cart": ..., "purchase": ... },
  "recent": [{ "id": "...", "produit": "...", ... }],
  "models": { ... },
  "mlops": { "checks": [...], "roadmap": [...] }
}
```

---

## Modèles Data Science (page séparée)

Les modèles **ne sont pas recalculés** à chaque requête dashboard. Les métriques V1 proviennent de `ml_meta.py` :

| Modèle | Métrique clé | Usage autorisé |
|--------|--------------|----------------|
| Forecasting | WAPE 30j ≈ 27,7 % | Planification agrégée 7/14/30 j |
| Pricing | WAPE qty ≈ 107 % | Simulation sous garde-fou marge |
| Recsys | Recall@10 ≈ 7,6 % | Bloc « produits populaires » |

Aucun modèle n'est déployé en production automatique — validation métier requise.

---

## Fichiers du projet

```
dashboard/
├── app.py                 # Routes Flask, auth, API
├── data_service.py        # Warehouse, filtres, agrégations KPI
├── ml_meta.py             # Métadonnées modèles V1 + journal MLOps
├── requirements.txt
├── .env.example
├── ouvrir_lecture.sql     # Script SQL utile Supabase
├── templates/
│   ├── app.html           # Structure 6 vues + modal drill-down
│   └── login.html
└── static/
    ├── css/
    │   ├── app.css        # Glassmorphism, filtres, KPI, modal
    │   └── login.css
    └── js/
        ├── app.js         # ECharts, filtres, render, drill-down
        ├── app-tail.js        # Modales enrichies, objectifs, animations
        └── export.js          # Export Excel + PDF
```

---

## Dépannage

| Symptôme | Cause probable | Action |
|----------|----------------|--------|
| « Mode démonstration » | `DATABASE_URL` absent ou erreur connexion | Vérifier `.env`, tester pooler Supabase |
| « Warehouse 0 ligne » | RLS ou tables vides | Utiliser connexion Postgres directe ; voir `ouvrir_lecture.sql` |
| Filtres vides | Cache sans dimensions | `/api/refresh` ou redémarrer l'app |
| Graphiques vides | Erreur JS | Console navigateur ; vérifier CDN ECharts |
| OneDrive bloque `app.js` | Sync fichier ouvert | Fermer l'éditeur ou pauser sync ; `app-tail.js` compense partiellement |

---

## Contexte académique

**Teranga BI** — Projet ISM Master 2 Big Data  
Thème : pricing data-driven, recommandation e-commerce, gouvernance MLOps  
Données : warehouse Mozart (Supabase) · **80 130** lignes ventes · CA **11,78 Md F** · marge **23,9 %** · conversion **~20 %**
