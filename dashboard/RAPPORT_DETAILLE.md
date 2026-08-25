# Teranga BI — Rapport détaillé complet

**Projet** : Dashboard décisionnel ISM Master 2 Big Data  
**Application** : Teranga BI (Flask + warehouse Mozart / Supabase)  
**Login** : `admin` / `teranga2026` · **Port** : `5055`  
**Date** : 25 août 2026

---

## 1. Pourquoi ce dashboard ?

Teranga BI sert à **décider** sur les ventes e-commerce (jeu **Mozart**, XOF) :

| Besoin métier | Comment le dashboard répond |
|---------------|----------------------------|
| Voir la santé commerciale | KPI CA, marge, panier, conversion |
| Comprendre *où* ça marche | Régions, catégories, segments, appareils |
| Agir sur le stock | Alertes rupture / faible + couverture |
| Segmenter les clients | VIP / Loyaux / Inactifs / Churn (comportement réel) |
| Planifier commandes / prix / vitrine | 3 outils métier (API data science) |
| Partager une analyse | Export Excel + HTML par menu |
| Explorer un point précis | Clic → modale commentée + filtre |

---

## 2. Lancer l’application

```bash
cd dashboard
python app.py
```

Ouvrir **http://127.0.0.1:5055** · attendre `Warm-up OK` · **Ctrl+F5** après une mise à jour JS/CSS.

| Identifiant | Valeur |
|-------------|--------|
| Utilisateur | `admin` |
| Mot de passe | `teranga2026` |

---

## 3. Architecture (comment ça marche)

| Couche | Fichiers | Rôle |
|--------|----------|------|
| UI | `templates/app.html`, `static/css/app.css` | Menus, filtres, panneaux |
| Front JS | `app.js`, `filters-patch.js`, `app-tail.js`, `models-live.js`, `export.js` | Charts, tableaux, modales, ML, exports |
| API | `app.py` | Auth, `/api/dashboard`, `/api/models`, warm-up |
| Données | `data_service.py` | Warehouse, filtres, KPI, statuts clients |
| Modèles | `ml_live.py` + `models_cache.json` | Prévisions / prix / reco |

**Pourquoi un warm-up au démarrage ?** Pour que le premier écran soit déjà chaud (warehouse + payloads + modèles), sans attendre un long premier clic.

**Pourquoi plusieurs fichiers JS ?** Séparation claire : rendu de base → filtres/tableaux → modales → ML → exports, sans tout mélanger.

---

## 4. Menus Analyse — fonctionnalités

### 4.1 Dashboard

**Pourquoi** : vue d’ensemble immédiate.  
**Contenu** : KPI globaux, CA dans le temps, catégories, funnel, segments.  
**Filtres** : année, mois, région.

### 4.2 Ventes & rentabilité

**Pourquoi** : suivre le CA, la promo et la marge.  
**Contenu** : régions, promo vs plein tarif, CA/unités, rentabilité, tableau des lignes.  
**Filtres** : année, mois, week-end, promo, statut, catégorie, produit, région, recherche.  
**Clic** : barre / donut / ligne → modale + option « Explorer ».

### 4.3 Produits & catégories

**Pourquoi** : savoir quels produits / catégories tirent le CA.  
**Cumul « toutes années »** : on additionne les comptes **par année** (ex. 235 + 300 = **535**), pas l’union unique — pour coller au volume d’activité multi-années.

### 4.4 Clients & parcours

**Pourquoi** : ne pas traiter tous les clients pareil.

| Statut | Définition (comportement d’achat) | Action typique |
|--------|-----------------------------------|----------------|
| **VIP** | Très fréquents (≥ 1,5 cmd/mois **ou** ≤ 14 j entre commandes) | Choyer / conserver |
| **Loyaux** | Réguliers, moins fréquents que les VIP | Fidéliser |
| **Inactifs** | 6 mois → **moins de 2 ans** sans achat | Relancer |
| **Churn** | **≥ 2 ans** sans achat | Analysés comme partis |

**Clients uniques** = VIP + Loyaux + Inactifs + Churn.  
**Cumul client × année** (ex. **9934**) = autre métrique (une fois le client par année) ; affiché en note sous les KPI.

**Fréquence** = commandes ÷ mois entre 1re et dernière commande.

**Export** : bouton **Excel** sur chaque panneau (VIP / Loyaux / Inactifs / Churn).

**Filtres** : année, mois, région, segment Mozart, âge, client, appareil, source, recherche.  
*(Pas de case « VIP uniquement » : les 4 panneaux séparent déjà les statuts.)*

### 4.5 Stock

**Pourquoi** : anticiper rupture et réassort.  
**Contenu** : alertes cliquables (modale action) + tableau stock.  
**Filtres** : catégorie, marque, produit, niveau.

---

## 5. Outils métier (3 menus)

Langage **commercial** (pas de jargon MLOps dans l’UI).

| Menu | Pourquoi | KPI | Graphiques / tableaux |
|------|----------|-----|------------------------|
| **Prévisions ventes** | Estimer volumes 7 / 30 j pour commander | Erreurs (plus bas = mieux) | Horizons, fenêtres, réel vs prévu, écarts produits |
| **Simulation prix** | Tester un scénario avant promo | Écart volume, marge, catalogue | Scores, ABC, scénarios, catalogue |
| **Recommandation** | Ordre de mise en avant | Gain d’ordre, couverture | Gains, popularité / best-sellers, usages |

**Comment** : cache JSON au chargement → affichage immédiat, puis refresh API Render via `/api/models`.

---

## 6. Filtres — règles

| Règle | Pourquoi |
|-------|----------|
| Chaque menu n’envoie **que ses** filtres | Évite de « polluer » une vue avec un filtre d’une autre |
| Année / mois explicites | Périmètre clair (pas de « 30 j » ambigu côté filtre global) |
| Cascades catégorie→produits, région/segment→clients | Listes utilisables |
| Changement = maj **immédiate** | Fluidité métier |
| Cache payload + index par année | Perf sur gros volumes |

---

## 7. Modales (drill-down)

**Comment** : clic sur graphique, liste, ligne tableau ou alerte stock.  
**Contenu** : commentaire métier, écart vs référence, bouton Explorer, export détail.  
**Pourquoi la délégation d’événements** : les tableaux sont re-peints souvent ; la délégation évite les clics « morts ».

---

## 8. Exports

| Format | Contenu | Pourquoi |
|--------|---------|----------|
| **Excel** | Titre Teranga, méta, barre KPI, tableau figé + filtres, feuille Filtres | Partage / analyse Excel |
| **HTML** | Rapport autonome + graphiques Chart.js | Présentation sans login |
| **Excel VIP / Loyaux / Inactifs / Churn** | Une liste ciblée | Campagnes / relances |

Un export = **le menu actif** (pas un dump global).

---

## 9. Affichage multi-écrans (responsive)

| Largeur | Comportement |
|---------|----------------|
| **Desktop (> 1100 px)** | Sidebar fixe à gauche · seul le contenu principal scroll |
| **Tablette (≤ 1100 px)** | Menu en haut, navigation en pastilles · grilles en 1 colonne |
| **Mobile (≤ 720 px)** | Filtres empilés · tableaux scrollables horizontalement · modale plein largeur |
| **Très petit (≤ 420 px)** | Typo / boutons densifiés |

**Pourquoi sidebar fixe sur desktop** : le menu reste toujours visible pendant qu’on lit les analyses.

Respect de `prefers-reduced-motion` et meilleure zone tactile (`hover: none`).

---

## 10. API

| Route | Rôle |
|-------|------|
| `GET /api/dashboard` | KPI + agrégats + options filtres |
| `GET /api/refresh` | Recharge warehouse |
| `GET /api/export/lignes` | Lignes détail ventes (plafond ~20k) |
| `GET /api/models` | Forecast / pricing / reco |

---

## 11. Ordres de grandeur Mozart (sans filtre)

- ~**84 k** lignes ventes · CA ~**11–12 Md F** · marge ~**24 %** · conversion ~**20 %**
- Produits cumul années : **535** · Clients cumul (client×année) : **9934**
- Filtres trop stricts → 0 ligne : **normal**

---

## 12. Fichiers clés

| Fichier | Rôle |
|---------|------|
| `app.py` | Routes, auth, warm-up |
| `data_service.py` | Warehouse, filtres, KPI, classification clients |
| `ml_live.py` | API modèles + textes métier |
| `static/js/app.js` | UI, charts, load |
| `static/js/filters-patch.js` | Filtres, tableaux |
| `static/js/app-tail.js` | Modales |
| `static/js/models-live.js` | 3 menus outils métier |
| `static/js/export.js` | Excel + HTML |
| `static/css/app.css` | Design + responsive |
| `README.md` | Doc projet / installation |

---

## 13. Checklist de validation rapide

1. Login → dashboard chargé (warm-up OK).  
2. Chaque menu : filtres + graphiques + tableau.  
3. Clic graph / ligne → modale.  
4. Clients : 4 KPI + 4 panneaux + Excel.  
5. Churn = **2 ans** ; VIP ≠ Loyaux.  
6. Export Excel/HTML du menu courant.  
7. Redimensionner la fenêtre (desktop / tablette / mobile).  
