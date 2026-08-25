/* Console V2 — application monopage sans dépendance externe.
   Routage par ancre, appels fetch, graphiques SVG dessinés à la main.
   Aucune trace d'exécution n'est jamais affichée à l'utilisateur. */
"use strict";

const VUE = document.getElementById("vue");
const PASTILLE = document.getElementById("pastille-api");

/* Render met le service en veille sur le plan gratuit : le premier appel peut
   demander une minute. On laisse donc un délai généreux et on prévient. */
const DELAI_MS = 75000;
const DELAI_AVERTISSEMENT_MS = 3500;

const etat = { metrics: null, catalogue: null, cleApi: sessionStorage.getItem("cle_api") || "" };

/* ------------------------------------------------------------------ outils */

const echappe = (valeur) => String(valeur ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const nombre = (valeur, decimales = 2) =>
  (valeur === null || valeur === undefined || Number.isNaN(valeur))
    ? "—"
    : Number(valeur).toLocaleString("fr-FR",
        { minimumFractionDigits: decimales, maximumFractionDigits: decimales });

const pourcent = (valeur, decimales = 2) =>
  (valeur === null || valeur === undefined) ? "—" : nombre(valeur * 100, decimales) + " %";

const fcfa = (valeur) => (valeur === null || valeur === undefined)
  ? "—" : Math.round(Number(valeur)).toLocaleString("fr-FR") + " FCFA";

const dateFr = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
};

/* ------------------------------------------------------------- client API */

async function appelApi(chemin, options = {}) {
  const controleur = new AbortController();
  const minuterie = setTimeout(() => controleur.abort(), DELAI_MS);
  const entetes = { Accept: "application/json" };
  if (options.body) entetes["Content-Type"] = "application/json";
  if (etat.cleApi) entetes["X-API-Key"] = etat.cleApi;
  try {
    const reponse = await fetch(chemin, {
      method: options.method || "GET",
      headers: entetes,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controleur.signal,
    });
    const texte = await reponse.text();
    let charge = null;
    try { charge = texte ? JSON.parse(texte) : null; } catch { charge = null; }
    if (!reponse.ok) {
      const err = (charge && charge.error) || {};
      throw {
        statut: reponse.status,
        code: err.code || "HTTP_" + reponse.status,
        message: err.message || messageParDefaut(reponse.status),
        details: err.details || {},
      };
    }
    return charge;
  } catch (erreur) {
    if (erreur && erreur.code) throw erreur;
    if (erreur && erreur.name === "AbortError") {
      throw { statut: 0, code: "TIMEOUT",
        message: "Le serveur met trop de temps à répondre. Il est peut-être en train de "
               + "sortir de veille : réessayez dans quelques secondes." };
    }
    throw { statut: 0, code: "RESEAU",
      message: "Impossible de joindre le serveur. Vérifiez votre connexion puis réessayez." };
  } finally {
    clearTimeout(minuterie);
  }
}

function messageParDefaut(statut) {
  if (statut === 401) return "Cette action nécessite une clé d'accès.";
  if (statut === 404) return "La ressource demandée n'existe pas.";
  if (statut === 503) return "Les modèles ne sont pas encore disponibles. Réessayez dans un instant.";
  if (statut >= 500) return "Le service a rencontré une erreur interne.";
  return "La requête n'a pas abouti.";
}

/* --------------------------------------------------------- blocs réutilisables */

const blocChargement = (texte = "Calcul en cours…") =>
  `<div class="etat"><p class="chargement"><span class="rotor" aria-hidden="true"></span>
   <span>${echappe(texte)}</span></p></div>`;

const blocVide = (texte) => `<div class="etat vide"><p>${echappe(texte)}</p></div>`;

function blocErreur(erreur, idRessai) {
  const aide = erreur.code === "INVALID_API_KEY"
    ? `<p>Renseignez la clé d'accès dans <a href="#/technique">État technique</a>.</p>` : "";
  const details = (erreur.details && Object.keys(erreur.details).length)
    ? `<p class="code">${echappe(JSON.stringify(erreur.details))}</p>` : "";
  return `<div class="etat erreur" role="alert">
    <h3>Cela n'a pas fonctionné</h3>
    <p>${echappe(erreur.message)}</p>
    ${aide}${details}
    <p class="code">Code : ${echappe(erreur.code)}</p>
    ${idRessai ? `<div class="actions"><button type="button" id="${idRessai}">Réessayer</button></div>` : ""}
  </div>`;
}

const avertissement = (titre, texte) =>
  `<p class="avertissement"><strong>${echappe(titre)}</strong> ${echappe(texte)}</p>`;

function badgeStatut(niveau, libelle) {
  const classe = niveau === "valide" ? "valide" : niveau === "exploratoire" ? "exploratoire" : "neutre";
  return `<span class="badge ${classe}">${echappe(libelle)}</span>`;
}

/* Courbe SVG dessinée sans bibliothèque : deux séries, axes simples. */
function grapheLignes(points, options = {}) {
  const L = 720, H = 260, mg = { h: 34, b: 40, g: 46, d: 12 };
  const largeur = L - mg.g - mg.d, hauteur = H - mg.h - mg.b;
  const series = options.series || [];
  const toutes = series.flatMap((s) => s.valeurs).filter((v) => v !== null && v !== undefined);
  const max = Math.max(1, ...toutes) * 1.15;
  const px = (i) => mg.g + (points.length <= 1 ? largeur / 2 : (i * largeur) / (points.length - 1));
  const py = (v) => mg.h + hauteur - (v / max) * hauteur;

  const grille = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const y = mg.h + hauteur - f * hauteur;
    return `<line x1="${mg.g}" y1="${y}" x2="${L - mg.d}" y2="${y}" stroke="#e6eaf0"/>
            <text x="${mg.g - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#55607a">${nombre(max * f, 1)}</text>`;
  }).join("");

  const pas = Math.max(1, Math.ceil(points.length / 6));
  const axeX = points.map((p, i) => (i % pas === 0 || i === points.length - 1)
    ? `<text x="${px(i)}" y="${H - 14}" text-anchor="middle" font-size="11" fill="#55607a">${echappe(p)}</text>` : "").join("");

  const traces = series.map((s) => {
    const d = s.valeurs.map((v, i) => (v === null || v === undefined) ? null : `${px(i)},${py(v)}`)
      .filter(Boolean).join(" ");
    if (!d) return "";
    const pointsCercles = s.valeurs.map((v, i) => (v === null || v === undefined) ? ""
      : `<circle cx="${px(i)}" cy="${py(v)}" r="3" fill="${s.couleur}"/>`).join("");
    return `<polyline points="${d}" fill="none" stroke="${s.couleur}" stroke-width="2.5"
             stroke-linejoin="round" stroke-dasharray="${s.pointille ? "6 4" : "0"}"/>${pointsCercles}`;
  }).join("");

  const legende = series.map((s) =>
    `<span><i class="pastille" style="background:${s.couleur}"></i>${echappe(s.nom)}</span>`).join("");

  return `<div class="graphe">
    <svg viewBox="0 0 ${L} ${H}" role="img" aria-label="${echappe(options.titre || "Graphique")}">
      ${grille}${axeX}${traces}
    </svg>
    <div class="legende">${legende}</div>
  </div>`;
}

function telechargeCsv(nomFichier, lignes) {
  const contenu = lignes.map((l) => l.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
  const lien = document.createElement("a");
  lien.href = URL.createObjectURL(new Blob(["﻿" + contenu], { type: "text/csv;charset=utf-8" }));
  lien.download = nomFichier;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
}

/* Encapsule un envoi de formulaire : anti double-clic, loader, restitution. */
function brancheEnvoi(idFormulaire, idBouton, idSortie, executer) {
  const formulaire = document.getElementById(idFormulaire);
  const bouton = document.getElementById(idBouton);
  const sortie = document.getElementById(idSortie);
  if (!formulaire) return;
  let enCours = false;

  formulaire.addEventListener("submit", async (evenement) => {
    evenement.preventDefault();
    if (enCours) return;
    enCours = true;
    bouton.disabled = true;
    const libelle = bouton.textContent;
    bouton.textContent = "Traitement…";
    sortie.innerHTML = blocChargement();
    const reveil = setTimeout(() => {
      sortie.innerHTML = blocChargement(
        "Le serveur sort peut-être de veille, cela peut prendre jusqu'à une minute…");
    }, DELAI_AVERTISSEMENT_MS);
    try {
      await executer(sortie);
    } catch (erreur) {
      sortie.innerHTML = blocErreur(erreur, idBouton + "-ressai");
      const ressai = document.getElementById(idBouton + "-ressai");
      if (ressai) ressai.addEventListener("click", () => formulaire.requestSubmit());
    } finally {
      clearTimeout(reveil);
      enCours = false;
      bouton.disabled = false;
      bouton.textContent = libelle;
    }
  });
}

/* Les valeurs saisies sont conservées : on ne réinitialise jamais le formulaire. */
async function chargeCatalogue() {
  if (etat.catalogue) return etat.catalogue;
  const reponse = await appelApi("/api/v1/catalog/products?limit=300");
  etat.catalogue = reponse.products;
  return etat.catalogue;
}

async function chargeMetriques() {
  if (etat.metrics) return etat.metrics;
  etat.metrics = await appelApi("/metrics");
  return etat.metrics;
}

function optionsProduits(produits, selection) {
  return produits.map((p) =>
    `<option value="${echappe(p.product_key)}"${p.product_key === selection ? " selected" : ""}>
      ${echappe(p.product_key)} — ${fcfa(p.catalog_price_xof)}</option>`).join("");
}

/* ------------------------------------------------------------------- pages */

async function pageAccueil() {
  VUE.innerHTML = `<h1>Console des modèles V2</h1>
    <p class="chapo">Trois modules issus d'un même jeu de données e-commerce synthétique :
    prévision de la demande, simulation de remise et recommandation de produits.
    Toutes les métriques affichées sont les références corrigées après audit de fuite.</p>
    <div id="modules">${blocChargement("Chargement des modules…")}</div>`;
  const cible = document.getElementById("modules");
  try {
    const metriques = await chargeMetriques();
    cible.innerHTML = `<div class="grille trois">` + metriques.domains.map((d) => `
      <article class="carte">
        <h3>${echappe(d.title)} ${badgeStatut(d.status_level, d.status_label)}</h3>
        <p class="chiffre">${d.headline.value === null || d.headline.value === undefined
            ? "—" : nombre(d.headline.value, 4)}
          <small>${echappe(d.headline.label)}</small></p>
        <p class="metrique aide"><strong>Modèle :</strong> ${echappe(d.model)}</p>
        <p class="metrique aide">${echappe(d.usage)}</p>
      </article>`).join("") + `</div>
      ${avertissement("Avertissement méthodologique.",
        "Données synthétiques, projet académique. La simulation de remise est exploratoire et "
        + "non causale. La recommandation repose sur une baseline de popularité, sans "
        + "personnalisation forte démontrée. Aucune décision n'est appliquée automatiquement.")}
      <h2>Aller plus loin</h2>
      <div class="grille deux">
        <article class="carte"><h3>Essayer les modules</h3>
          <ul class="liste-nue">
            <li><a href="#/prevision">Prévoir la demande d'un produit</a></li>
            <li><a href="#/pricing">Simuler une remise sous garde-fous</a></li>
            <li><a href="#/recommandation">Obtenir des recommandations</a></li>
          </ul></article>
        <article class="carte"><h3>Comprendre les résultats</h3>
          <ul class="liste-nue">
            <li><a href="#/performances">Performances et limites de chaque modèle</a></li>
            <li><a href="#/technique">État technique et modèles chargés</a></li>
            <li><a href="/docs">Documentation Swagger de l'API</a></li>
          </ul></article>
      </div>`;
  } catch (erreur) {
    cible.innerHTML = blocErreur(erreur, "accueil-ressai");
    const b = document.getElementById("accueil-ressai");
    if (b) b.addEventListener("click", pageAccueil);
  }
}

async function pagePerformances() {
  VUE.innerHTML = `<h1>Performances des modèles</h1>
    <p class="chapo">Chaque chiffre provient des artefacts officiels vérifiés au démarrage
    de l'API. Pour chaque métrique : ce qu'elle mesure, dans quel sens la lire, et ce
    qu'elle ne permet pas de conclure.</p>
    <div id="perfs">${blocChargement("Chargement des métriques…")}</div>`;
  const cible = document.getElementById("perfs");
  try {
    const m = await chargeMetriques();
    const carteMetrique = (mt) => `
      <div class="metrique">
        <div class="ligne"><span>${echappe(mt.label)}</span>
          <span class="val">${mt.value === null || mt.value === undefined ? "—" : nombre(mt.value, 5)}</span></div>
        <p class="aide">${echappe(mt.explanation)}</p>
        <p class="sens">${echappe(mt.better)}</p>
        <p class="aide"><em>Ne permet pas de conclure :</em> ${echappe(mt.caveat)}</p>
      </div>`;

    cible.innerHTML = `
      ${avertissement("Référence corrigée après audit.",
        "Les résultats antérieurs à l'audit ont été invalidés pour fuite de données et ne sont "
        + "jamais affichés ici. Données synthétiques — projet académique.")}
      <div class="grille deux">
        ${m.domains.map((d) => `
          <article class="carte">
            <h3>${echappe(d.title)} ${badgeStatut(d.status_level, d.status_label)}</h3>
            <p class="aide"><strong>Modèle :</strong> ${echappe(d.model)}
              ${d.secondary_model ? ` · <strong>Quotidien :</strong> ${echappe(d.secondary_model)}` : ""}</p>
            ${d.metrics ? d.metrics.map(carteMetrique).join("") : ""}
            ${(d.perimeters || []).map((p) => `
              <div class="metrique">
                <div class="ligne"><strong>${echappe(p.label)}</strong>
                  <span class="badge ${p.status === "none_validated" ? "bloque" : "neutre"}">${echappe(p.status)}</span></div>
                <p class="aide">${echappe(p.description)}</p>
                ${p.metrics.map((mt) => `<div class="ligne"><span>${echappe(mt.label)}</span>
                   <span class="val">${nombre(mt.value, 5)}</span></div>`).join("")}
              </div>`).join("")}
            ${d.limits && d.limits.length
              ? `<h3 style="margin-top:.8rem">Limites</h3><ul class="liste-nue">${
                  d.limits.map((l) => `<li>${echappe(l)}</li>`).join("")}</ul>` : ""}
          </article>`).join("")}
      </div>
      <h2>Périmètres de recommandation</h2>
      ${avertissement("Deux périmètres distincts.", m.perimeter_warning || "")}
      <h2>Historique invalidé</h2>
      <div class="grille deux">
        <article class="carte"><h3>Simulation de remise</h3>
          <p class="aide">${echappe(m.invalidated_history.pricing.note)}</p>
          <p><span class="badge bloque">${echappe(m.invalidated_history.pricing.status)}</span></p></article>
        <article class="carte"><h3>Complément panier</h3>
          <p class="aide">${echappe(m.invalidated_history.basket.note)}</p>
          <p><span class="badge bloque">${echappe(m.invalidated_history.basket.status)}</span></p></article>
      </div>`;
  } catch (erreur) {
    cible.innerHTML = blocErreur(erreur, "perf-ressai");
    const b = document.getElementById("perf-ressai");
    if (b) b.addEventListener("click", pagePerformances);
  }
}

async function pagePrevision() {
  VUE.innerHTML = `<h1>Prévision de la demande</h1>
    <p class="chapo">Consultation des prévisions du modèle validé
    <strong>LightGBM_direct_per_horizon</strong> sur la dernière fenêtre de backtest
    (cutoff au 1<sup>er</sup> juillet 2026). Ce sont des résultats mesurés, pas une
    inférence recalculée en direct.</p>
    <div class="grille deux">
      <section class="carte">
        <h3>Paramètres</h3>
        <form id="f-prevision">
          <div class="champ">
            <label for="p-produit">Produit <span class="indice">(triés par popularité)</span></label>
            <select id="p-produit" name="produit"><option>Chargement…</option></select>
          </div>
          <div class="champ">
            <label for="p-horizon">Horizon</label>
            <select id="p-horizon" name="horizon">
              <option value="7">7 jours</option>
              <option value="14">14 jours</option>
              <option value="30" selected>30 jours</option>
            </select>
          </div>
          <div class="actions">
            <button type="submit" id="p-lancer">Prévoir</button>
            <button type="button" class="secondaire" id="p-exemple">Charger un exemple</button>
          </div>
        </form>
      </section>
      <section id="p-sortie">${blocVide("Choisissez un produit et un horizon, puis lancez la prévision.")}</section>
    </div>
    <div id="p-detail"></div>`;

  const select = document.getElementById("p-produit");
  try {
    const produits = await chargeCatalogue();
    const avecPrevision = produits.filter((p) => p.has_forecast);
    select.innerHTML = optionsProduits(avecPrevision.length ? avecPrevision : produits);
  } catch (erreur) {
    select.innerHTML = `<option value="">Catalogue indisponible</option>`;
    document.getElementById("p-sortie").innerHTML = blocErreur(erreur);
    return;
  }

  document.getElementById("p-exemple").addEventListener("click", () => {
    select.selectedIndex = 0;
    document.getElementById("p-horizon").value = "30";
    document.getElementById("f-prevision").requestSubmit();
  });

  brancheEnvoi("f-prevision", "p-lancer", "p-sortie", async (sortie) => {
    const produit = select.value;
    const horizon = Number(document.getElementById("p-horizon").value);
    if (!produit) throw { code: "AUCUN_PRODUIT", message: "Sélectionnez d'abord un produit." };
    const r = await appelApi("/api/v1/forecast", {
      method: "POST", body: { product_key: produit, horizon_days: horizon },
    });
    sortie.innerHTML = `<div class="carte">
      <h3>Total prévu sur ${r.horizon_days} jours</h3>
      <p class="chiffre">${nombre(r.total_predicted_quantity, 1)}<small>unités — ${echappe(r.product_key)}</small></p>
      ${r.total_actual_quantity !== null && r.total_actual_quantity !== undefined
        ? `<p class="metrique aide"><strong>Réalisé observé :</strong>
           ${nombre(r.total_actual_quantity, 1)} unités sur la même fenêtre.</p>` : ""}
      <p class="metrique aide"><strong>Modèle :</strong> ${echappe(r.model_name)}<br>
        <strong>Nature :</strong> ${r.kind === "backtest_valide"
          ? "backtest validé, non recalculé en direct" : echappe(r.kind)}<br>
        <strong>Cutoff :</strong> ${dateFr(r.cutoff)}<br>
        <strong>Généré le :</strong> ${dateFr(r.generated_at)}</p>
      ${r.fallback_used ? avertissement("Repli utilisé.", r.fallback_reason || "") : ""}
      ${avertissement("Demande intermittente.",
        "Environ 66 % des jours sont sans vente. Une prévision journalière proche de zéro est "
        + "normale ; c'est le cumul sur l'horizon qui fait sens pour la planification.")}
    </div>`;

    const etiquettes = r.points.map((p) => dateFr(p.date).replace(/\s\d{4}$/, ""));
    const series = [{ nom: "Prévu", couleur: "#1f5fbf", valeurs: r.points.map((p) => p.predicted_quantity) }];
    if (r.points.some((p) => p.actual_quantity !== null && p.actual_quantity !== undefined)) {
      series.push({ nom: "Réalisé", couleur: "#10704a", pointille: true,
        valeurs: r.points.map((p) => p.actual_quantity) });
    }
    document.getElementById("p-detail").innerHTML = `
      <h2>Détail quotidien</h2>
      ${grapheLignes(etiquettes, { series, titre: "Prévision quotidienne" })}
      <div class="actions"><button type="button" class="secondaire" id="p-csv">Exporter en CSV</button></div>
      <div class="table-enveloppe" style="margin-top:.75rem">
        <table><caption class="sr-only">Détail quotidien de la prévision</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Prévu</th><th scope="col">Réalisé</th></tr></thead>
          <tbody>${r.points.map((p) => `<tr><td>${dateFr(p.date)}</td>
            <td class="num">${nombre(p.predicted_quantity, 2)}</td>
            <td class="num">${p.actual_quantity === null || p.actual_quantity === undefined
              ? "—" : nombre(p.actual_quantity, 2)}</td></tr>`).join("")}</tbody>
        </table>
      </div>`;
    document.getElementById("p-csv").addEventListener("click", () => {
      telechargeCsv(`prevision_${r.product_key}_${r.horizon_days}j.csv`,
        [["date", "quantite_prevue", "quantite_reelle"],
         ...r.points.map((p) => [p.date, p.predicted_quantity,
           p.actual_quantity === null || p.actual_quantity === undefined ? "" : p.actual_quantity])]);
    });
  });
}

async function pagePricing() {
  VUE.innerHTML = `<h1>Simulateur de remise</h1>
    <p class="chapo">Scénario exploratoire sous garde-fous. Le simulateur estime un volume
    attendu pour une remise donnée : il ne désigne aucun tarif à appliquer, et toute
    proposition exige une validation humaine.</p>
    ${avertissement("Scénario exploratoire — non causal.",
      "Le prix catalogue est fixe et les campagnes ne sont pas randomisées : aucun effet causal "
      + "ne peut être déduit. Prix jamais sous le coût, marge minimale de 5 %, remises limitées "
      + "au support historique observé.")}
    <div class="grille deux">
      <section class="carte">
        <h3>Paramètres</h3>
        <form id="f-pricing">
          <div class="champ">
            <label for="r-produit">Produit</label>
            <select id="r-produit"><option>Chargement…</option></select>
          </div>
          <div class="champ">
            <label id="lbl-remises">Remises à simuler
              <span class="indice">(uniquement celles observées pour ce produit)</span></label>
            <div class="cases" id="r-remises" role="group" aria-labelledby="lbl-remises"></div>
          </div>
          <div class="champ">
            <label for="r-date">Date de décision</label>
            <input type="date" id="r-date" value="2026-07-15">
          </div>
          <div class="champ">
            <label for="r-marge">Plancher de marge <span class="indice">(garde-fou réglementaire : 5 % minimum)</span></label>
            <select id="r-marge">
              <option value="0.05" selected>5 % (plancher officiel)</option>
              <option value="0.10">10 % (plus prudent)</option>
              <option value="0.20">20 % (très prudent)</option>
            </select>
          </div>
          <div class="actions">
            <button type="submit" id="r-lancer">Simuler</button>
            <button type="button" class="secondaire" id="r-exemple">Charger un exemple</button>
          </div>
        </form>
      </section>
      <section id="r-sortie">${blocVide("Choisissez un produit et une ou plusieurs remises.")}</section>
    </div>`;

  const select = document.getElementById("r-produit");
  const cases = document.getElementById("r-remises");
  let produits = [];
  try {
    produits = await chargeCatalogue();
    select.innerHTML = optionsProduits(produits);
  } catch (erreur) {
    select.innerHTML = `<option value="">Catalogue indisponible</option>`;
    document.getElementById("r-sortie").innerHTML = blocErreur(erreur);
    return;
  }

  const rafraichitRemises = () => {
    const produit = produits.find((p) => p.product_key === select.value);
    const remises = produit ? produit.supported_discounts_pct : [];
    cases.innerHTML = remises.length
      ? remises.map((d, i) => `<label><input type="checkbox" value="${d}"${i === 0 ? " checked" : ""}>
          ${nombre(d, 0)} %</label>`).join("")
      : `<p class="aide">Aucune remise historiquement observée pour ce produit.</p>`;
  };
  select.addEventListener("change", rafraichitRemises);
  rafraichitRemises();

  document.getElementById("r-exemple").addEventListener("click", () => {
    const riche = produits.find((p) => p.supported_discounts_pct.length >= 3) || produits[0];
    select.value = riche.product_key;
    rafraichitRemises();
    cases.querySelectorAll("input").forEach((c) => { c.checked = true; });
    document.getElementById("r-date").value = "2026-07-15";
    document.getElementById("f-pricing").requestSubmit();
  });

  brancheEnvoi("f-pricing", "r-lancer", "r-sortie", async (sortie) => {
    const remises = [...cases.querySelectorAll("input:checked")].map((c) => Number(c.value));
    if (!remises.length) {
      throw { code: "AUCUNE_REMISE", message: "Sélectionnez au moins une remise à simuler." };
    }
    const plancher = Number(document.getElementById("r-marge").value);
    const r = await appelApi("/api/v1/pricing/simulate", {
      method: "POST",
      body: {
        product_key: select.value,
        decision_date: document.getElementById("r-date").value,
        candidate_discounts_pct: remises,
        features: {},
        partial_results: true,
      },
    });

    const lignes = r.simulations.map((s) => {
      const sousPlancher = s.simulation_status !== "blocked" && s.margin_rate < plancher;
      const bloquee = s.simulation_status === "blocked" || sousPlancher;
      const motif = s.simulation_status === "blocked"
        ? s.blocked_reason
        : sousPlancher ? `Marge de ${pourcent(s.margin_rate)} sous le plancher choisi de ${pourcent(plancher, 0)}.` : "";
      return `<tr class="${bloquee ? "bloquee" : ""}">
        <td>${nombre(s.discount_pct, 0)} %</td>
        <td class="num">${fcfa(s.simulated_price_xof)}</td>
        <td class="num">${bloquee ? "—" : nombre(s.predicted_quantity, 2)}</td>
        <td class="num">${bloquee ? "—" : fcfa(s.expected_revenue_xof)}</td>
        <td class="num">${bloquee ? "—" : fcfa(s.expected_margin_xof)}</td>
        <td class="num">${pourcent(s.margin_rate)}</td>
        <td>${bloquee ? `<span class="badge bloque">Bloquée</span>` : `<span class="badge valide">Conforme</span>`}</td>
      </tr>${motif ? `<tr class="bloquee"><td colspan="7" class="aide">${echappe(motif)}</td></tr>` : ""}`;
    }).join("");

    const conformes = r.simulations.filter((s) => s.simulation_status !== "blocked"
      && s.margin_rate >= plancher);
    sortie.innerHTML = `<div class="carte">
      <h3>Résultat <span class="badge exploratoire">${echappe(r.model_status)}</span></h3>
      <p class="metrique aide"><strong>Produit :</strong> ${echappe(r.product_key)} ·
        <strong>Prix catalogue :</strong> ${fcfa(r.simulations[0]?.catalog_price_xof)} ·
        <strong>Coût :</strong> ${fcfa(r.simulations[0]?.cost_xof)}</p>
      <p class="metrique aide"><strong>Modèle de volume :</strong> ${echappe(r.model_name)} ·
        WAPE ${nombre(r.pricing_wape, 4)} · biais ${nombre(r.pricing_bias, 4)}</p>
      <p class="metrique aide"><strong>Niveau de confiance :</strong> modéré. La WAPE de
        ${nombre(r.pricing_wape, 3)} signifie une erreur moyenne d'environ
        ${pourcent(r.pricing_wape, 0)} sur la quantité : à lire comme un ordre de grandeur,
        pas comme une valeur exacte.</p>
      ${conformes.length === 0
        ? `<p class="etat erreur" role="alert">Aucune remise ne respecte les garde-fous
           pour ce produit. Aucune proposition n'est faite.</p>` : ""}
      <p class="metrique aide"><strong>Validation humaine requise.</strong>
        Application automatique : ${r.automatic_application_allowed ? "autorisée" : "interdite"}.
        Effet causal estimé : ${r.causal_effect_estimated ? "oui" : "non"}.</p>
    </div>
    <div class="table-enveloppe" style="margin-top:1rem">
      <table><caption class="sr-only">Scénarios de remise simulés</caption>
        <thead><tr><th scope="col">Remise</th><th scope="col">Prix après remise</th>
          <th scope="col">Quantité estimée</th><th scope="col">CA estimé</th>
          <th scope="col">Marge estimée</th><th scope="col">Taux de marge</th>
          <th scope="col">Garde-fous</th></tr></thead>
        <tbody>${lignes}</tbody>
      </table>
    </div>`;
  });
}

async function pageRecommandation() {
  VUE.innerHTML = `<h1>Recommandation de produits</h1>
    <p class="chapo">Baseline de popularité globale. Aucune personnalisation forte n'a été
    démontrée sur ces données : les résultats sont proches pour tous les visiteurs.</p>
    ${avertissement("Baseline de popularité.",
      "La sortie provient de la popularité globale du catalogue, pas d'un modèle personnalisé. "
      + "Aucun modèle de complément panier personnalisé n'a été validé.")}
    <div class="grille deux">
      <section class="carte">
        <h3>Paramètres</h3>
        <form id="f-reco">
          <div class="champ">
            <label for="c-mode">Contexte</label>
            <select id="c-mode">
              <option value="anonyme" selected>Visiteur anonyme</option>
              <option value="panier">Compléter un panier</option>
            </select>
          </div>
          <div class="champ" id="bloc-panier" hidden>
            <label for="c-panier">Produit déjà au panier</label>
            <select id="c-panier"><option>Chargement…</option></select>
          </div>
          <div class="champ">
            <label for="c-k">Nombre de recommandations</label>
            <select id="c-k">
              <option value="5">5</option><option value="10" selected>10</option>
              <option value="20">20</option>
            </select>
          </div>
          <div class="actions">
            <button type="submit" id="c-lancer">Recommander</button>
            <button type="button" class="secondaire" id="c-exemple">Charger un exemple</button>
          </div>
        </form>
      </section>
      <section id="c-sortie">${blocVide("Choisissez un contexte puis lancez la recommandation.")}</section>
    </div>`;

  const mode = document.getElementById("c-mode");
  const blocPanier = document.getElementById("bloc-panier");
  const selPanier = document.getElementById("c-panier");
  let produits = [];
  try {
    produits = await chargeCatalogue();
    selPanier.innerHTML = optionsProduits(produits);
  } catch (erreur) {
    document.getElementById("c-sortie").innerHTML = blocErreur(erreur);
    return;
  }
  const parCle = new Map(produits.map((p) => [p.product_key, p]));
  mode.addEventListener("change", () => { blocPanier.hidden = mode.value !== "panier"; });

  document.getElementById("c-exemple").addEventListener("click", () => {
    mode.value = "panier";
    blocPanier.hidden = false;
    selPanier.selectedIndex = 0;
    document.getElementById("c-k").value = "10";
    document.getElementById("f-reco").requestSubmit();
  });

  brancheEnvoi("f-reco", "c-lancer", "c-sortie", async (sortie) => {
    const k = Number(document.getElementById("c-k").value);
    const panier = mode.value === "panier";
    const r = panier
      ? await appelApi("/api/v1/recommendations/basket",
          { method: "POST", body: { product_keys: [selPanier.value], k } })
      : await appelApi("/api/v1/recommendations/general", { method: "POST", body: { k } });

    if (!r.recommendations.length) {
      sortie.innerHTML = blocVide("Aucune recommandation ne peut être produite pour ce contexte.");
      return;
    }
    const source = panier ? "Complément panier — repli sur la popularité globale"
                          : "Popularité globale";
    sortie.innerHTML = `<div class="carte">
      <h3>Origine de la sortie</h3>
      <p><span class="badge neutre">${echappe(source)}</span></p>
      <p class="metrique aide"><strong>Modèle :</strong> ${echappe(r.model_name)} ·
        <strong>Statut :</strong> ${echappe(r.model_status)}</p>
      <p class="metrique aide"><strong>Personnalisation validée :</strong>
        ${r.personalization_validated ? "oui" : "non"}.
        ${r.personalization_validated ? "" :
          "Les mêmes produits seront proposés à la plupart des visiteurs."}</p>
      ${r.fallback_used ? avertissement("Repli utilisé.",
        "Aucun modèle de complément personnalisé n'est validé : la popularité globale est "
        + "utilisée, en excluant les articles déjà présents au panier.") : ""}
      ${r.catalog_coverage_warning ? avertissement("Couverture catalogue limitée.",
        "Cette baseline concentre ses recommandations sur une petite partie du catalogue.") : ""}
    </div>
    <div class="table-enveloppe" style="margin-top:1rem">
      <table><caption class="sr-only">Produits recommandés</caption>
        <thead><tr><th scope="col">Rang</th><th scope="col">Produit</th>
          <th scope="col">Prix</th><th scope="col">Score</th><th scope="col">Motif</th></tr></thead>
        <tbody>${r.recommendations.map((item) => {
          const p = parCle.get(item.product_key);
          return `<tr><td>${item.rank}</td><td>${echappe(item.product_key)}</td>
            <td class="num">${p ? fcfa(p.catalog_price_xof) : "—"}</td>
            <td class="num">${nombre(item.score, 4)}</td>
            <td>Produit populaire du catalogue</td></tr>`;
        }).join("")}</tbody>
      </table>
    </div>`;
  });
}

async function pageTechnique() {
  VUE.innerHTML = `<h1>État technique</h1>
    <p class="chapo">Disponibilité de l'API, modèles chargés et limites connues.</p>
    <div id="t-sortie">${blocChargement("Interrogation de l'API…")}</div>`;
  const cible = document.getElementById("t-sortie");
  const debut = performance.now();
  try {
    const [version, pret, modeles] = await Promise.all([
      appelApi("/version"), appelApi("/ready"), appelApi("/models"),
    ]);
    const duree = Math.round(performance.now() - debut);
    cible.innerHTML = `
      <div class="grille deux">
        <article class="carte"><h3>API <span class="badge valide">disponible</span></h3>
          <p class="metrique aide"><strong>Version API :</strong> ${echappe(version.api_version)}<br>
            <strong>Version du bundle :</strong> ${echappe(version.bundle_version || "—")}<br>
            <strong>Commit :</strong> ${echappe(version.commit || "inconnu")}<br>
            <strong>Environnement :</strong> ${echappe(version.environment)}<br>
            <strong>Temps de réponse :</strong> ${duree} ms<br>
            <strong>Dernière vérification :</strong> ${new Date().toLocaleString("fr-FR")}</p>
        </article>
        <article class="carte"><h3>Contrôles au démarrage</h3>
          <ul class="liste-nue">${Object.entries(pret.checks).map(([nom, ok]) =>
            `<li>${echappe(nom)} : <span class="badge ${ok ? "valide" : "bloque"}">${ok ? "OK" : "absent"}</span></li>`
          ).join("")}</ul>
        </article>
      </div>
      <h2>Modèles</h2>
      <div class="table-enveloppe">
        <table><caption class="sr-only">Modèles exposés</caption>
          <thead><tr><th scope="col">Domaine</th><th scope="col">Modèle</th>
            <th scope="col">Statut</th><th scope="col">Exposé</th><th scope="col">Usage</th></tr></thead>
          <tbody>${modeles.models.map((m) => `<tr>
            <td>${echappe(m.domain)}</td><td>${echappe(m.name || "—")}</td>
            <td>${echappe(m.status)}</td>
            <td>${m.exposed ? "oui" : "non"}</td><td>${echappe(m.usage)}</td></tr>`).join("")}</tbody>
        </table>
      </div>
      <h2>Limites connues</h2>
      <ul class="liste-nue">
        <li>Données synthétiques : les résultats ne se transposent pas à un catalogue réel.</li>
        <li>La simulation de remise est observationnelle et non causale.</li>
        <li>Aucun modèle de recommandation personnalisé n'est validé.</li>
        <li>Le modèle sessionnel est déclaré non utilisable.</li>
        <li>Les prévisions proviennent d'un backtest validé, pas d'une inférence en direct.</li>
        <li>Sur l'hébergement gratuit, le premier appel après une période d'inactivité peut demander jusqu'à une minute.</li>
      </ul>
      <h2>Documentation</h2>
      <p><a href="/docs">Swagger</a> · <a href="/openapi.json">OpenAPI</a></p>
      <h2>Clé d'accès</h2>
      <p class="aide">Nécessaire uniquement si le déploiement en exige une.
        Elle reste dans votre navigateur et n'est jamais journalisée.</p>
      <form id="f-cle"><div class="champ">
        <label for="t-cle">Clé API</label>
        <input type="password" id="t-cle" value="${echappe(etat.cleApi)}" autocomplete="off">
      </div><div class="actions"><button type="submit" id="t-enregistrer">Enregistrer</button></div></form>`;
    document.getElementById("f-cle").addEventListener("submit", (e) => {
      e.preventDefault();
      etat.cleApi = document.getElementById("t-cle").value.trim();
      sessionStorage.setItem("cle_api", etat.cleApi);
      etat.metrics = null; etat.catalogue = null;
      pageTechnique();
    });
  } catch (erreur) {
    cible.innerHTML = blocErreur(erreur, "t-ressai");
    const b = document.getElementById("t-ressai");
    if (b) b.addEventListener("click", pageTechnique);
  }
}

/* ---------------------------------------------------------------- routage */

const ROUTES = {
  accueil: pageAccueil, performances: pagePerformances, prevision: pagePrevision,
  pricing: pagePricing, recommandation: pageRecommandation, technique: pageTechnique,
};

function routeActuelle() {
  const nom = (location.hash || "#/accueil").replace(/^#\//, "").split("?")[0];
  return ROUTES[nom] ? nom : "accueil";
}

async function affiche() {
  const nom = routeActuelle();
  document.querySelectorAll("nav.principal a").forEach((a) => {
    if (a.dataset.route === nom) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  VUE.innerHTML = blocChargement("Chargement…");
  try {
    await ROUTES[nom]();
  } catch (erreur) {
    VUE.innerHTML = blocErreur(erreur);
  }
  document.getElementById("contenu").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "instant" });
}

async function sondeApi() {
  try {
    const pret = await appelApi("/ready");
    const ok = pret.status === "ready";
    PASTILLE.className = "badge " + (ok ? "valide" : "exploratoire");
    PASTILLE.textContent = ok ? "API disponible" : "API dégradée";
  } catch {
    PASTILLE.className = "badge bloque";
    PASTILLE.textContent = "API injoignable";
  }
}

window.addEventListener("hashchange", affiche);
affiche();
sondeApi();
