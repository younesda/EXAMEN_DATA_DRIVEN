/* Outils métier — 3 menus + cache local instantané + refresh API */
(function () {
  let ML = null;
  let loading = false;
  const ML_VIEWS = new Set(["ml-forecast", "ml-pricing", "ml-reco"]);
  const CHART_IDS = [
    "chart-ml-wape", "chart-ml-windows", "chart-ml-cat",
    "chart-ml-abc", "chart-ml-ecarts", "chart-ml-pop",
    "chart-ml-pricing-scores", "chart-ml-reco-gains",
  ];

  function mlOpen(title, comment, rows) {
    if (typeof openDetail !== "function") return;
    openDetail({
      title,
      comment: comment || `Lecture métier de « ${title} ». Les chiffres ci-dessous aident à décider.`,
      rows: rows || [],
    });
  }

  function bindMlChart(id, handler) {
    if (typeof bindDrill !== "function") return;
    bindDrill(id, handler);
    setTimeout(() => bindDrill(id, handler), 80);
    setTimeout(() => {
      bindDrill(id, handler);
      if (typeof rebindAllDrills === "function") rebindAllDrills();
    }, 250);
  }

  function fmtPct(v) {
    if (v == null || Number.isNaN(Number(v))) return "—";
    return `${Number(v).toFixed(1)} %`;
  }

  function hasData(d) {
    const t = d?.tables || {};
    return (t.forecast && t.forecast.length) || (t.pricing && t.pricing.length) || (t.reco && t.reco.length);
  }

  function isMlView() {
    return ML_VIEWS.has(typeof CURRENT_VIEW !== "undefined" ? CURRENT_VIEW : "");
  }

  function forceResizeMl() {
    CHART_IDS.forEach((id) => {
      if (typeof charts !== "undefined" && charts[id]) {
        try { charts[id].resize(); } catch (_) { /* ignore */ }
      }
    });
    if (typeof resizeAll === "function") resizeAll();
  }

  const METIER_COPY = {
    forecast: {
      name: "Prévision des ventes",
      subtitle: "Combien commander sur 7 et 30 jours",
      status: "Prêt pour la planification",
      metric_label: "Erreur moyenne à 30 jours",
      metric_unit: "%",
      usage: "Estimer les volumes pour le stock et les commandes fournisseurs.",
      interdit: "Ce n’est pas un score de réussite. L’écart jour par jour reste souvent élevé.",
      note: "Plus l’erreur est basse, plus la prévision est utile pour commander.",
    },
    pricing: {
      name: "Simulation des prix",
      subtitle: "Scénarios prix / marge avant une promo",
      status: "Simulation — aucun prix modifié en magasin",
      metric_label: "Écart volume à 7 jours",
      metric_unit: "%",
      usage: "Comparer volume, CA et marge pour préparer une décision prix.",
      interdit: "Rien n’est appliqué automatiquement. Une baisse de prix ne garantit pas plus de ventes.",
      note: "CA et marge affichés sont calculés à partir du volume et du prix simulés.",
    },
    reco: {
      name: "Mise en avant produits",
      subtitle: "Mieux ordonner les produits à pousser",
      status: "Listes validées · sinon best-sellers",
      metric_label: "Gain d’ordre (achat)",
      metric_unit: "%",
      usage: "Réordonner une vitrine ou une liste courte pour mieux coller aux achats.",
      interdit: "Une piste encore en test n’est jamais proposée seule sur le site.",
      note: "Le gain dit si l’ordre de la liste est meilleur, pas un taux de « bonnes » réponses.",
    },
  };

  function heroCard(m) {
    if (!m) return "";
    const score = m.metric_value != null
      ? (m.id === "forecast" || m.id === "pricing"
        ? Math.max(0, 100 - Number(m.metric_value))
        : Math.min(100, Number(m.metric_value) || 50))
      : 50;
    const metric = m.metric_value != null
      ? `${m.metric_label} : ${Number(m.metric_value).toFixed(1)}${m.metric_unit || ""}`
      : m.metric_label;
    return `<div class="ml-hero-inner">
      <div class="tone">${m.status}</div>
      <h2>${m.name}</h2>
      <p class="chart-hint">${m.subtitle || ""}</p>
      <div class="ring-wrap">${ringSvg(score)}<div><b>${metric}</b></div></div>
      <div class="ml-hero-grid">
        <p><strong>À quoi ça sert</strong><br/>${m.usage}</p>
        <p><strong>Attention</strong><br/>${m.interdit}</p>
      </div>
      <p class="chart-hint" style="margin-top:10px">${m.note || ""}</p>
    </div>`;
  }

  function cardById(d, id) {
    const raw = (d.cards || []).find((c) => c.id === id) || {};
    const copy = METIER_COPY[id] || {};
    return {
      ...raw,
      ...copy,
      id,
      metric_value: raw.metric_value != null ? raw.metric_value : copy.metric_value,
    };
  }

  function serviceLine(d) {
    const s = d.service || {};
    const jeu = s.statut_donnees === "synthetic_academic_experiment" ? "jeu d’essai" : "données live";
    return `Indicateurs à jour pour l’équipe commerciale · ${jeu}`;
  }

  function renderForecast(d) {
    const k = d.kpis || {};
    const v = d.validation?.forecast || {};
    if (el("ml-service-meta-fc")) el("ml-service-meta-fc").textContent = serviceLine(d);
    if (el("kpi-ml-forecast")) {
      el("kpi-ml-forecast").innerHTML = [
        kpiCard("hero", "Erreur à 30 j", fmtPct(k.wape_30), null),
        kpiCard("", "Erreur totale", fmtPct(k.wape30_micro), null),
        kpiCard("", "Erreur à 7 j", fmtPct(k.wape_7), null),
        kpiCard("", "Erreur au jour", fmtPct(k.wape_day), null),
      ].join("");
    }
    if (el("card-ml-forecast")) el("card-ml-forecast").innerHTML = heroCard(cardById(d, "forecast"));

    const tip = { ...TIP, valueFormatter: (v) => (typeof v === "number" ? v.toFixed(1) : v) };
    const c = d.charts || {};
    const ph = c.precision_horizons || { labels: [], values: [] };
    chart("chart-ml-wape", {
      tooltip: { trigger: "axis", ...tip },
      grid: { left: 48, right: 16, top: 28, bottom: 36 },
      xAxis: { type: "category", data: ph.labels, axisLabel: { color: AXIS } },
      yAxis: { type: "value", name: "% erreur", nameTextStyle: { color: AXIS }, splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS } },
      series: [{
        type: "bar", barWidth: 40,
        data: (ph.values || []).map((val, i) => ({
          value: val,
          itemStyle: { color: ["#053f24", "#0d7a3e", "#14a44d"][i] || "#053f24", borderRadius: [8, 8, 0, 0] },
        })),
        label: { show: true, position: "top", formatter: (p) => `${Number(p.value).toFixed(1)} %`, color: AXIS },
      }],
    });
    bindMlChart("chart-ml-wape", (p) => {
      const lab = (ph.labels || [])[p.dataIndex] || "Horizon";
      mlOpen(lab, `Erreur de prévision sur « ${lab} » : ${fmtPct(p.value)}. Plus bas = mieux pour commander.`, [
        ["Horizon", lab], ["Erreur", fmtPct(p.value)],
      ]);
    });

    const w = c.fenetres || { labels: [], wape_30: [], wape_7: [] };
    chart("chart-ml-windows", {
      tooltip: { trigger: "axis", ...tip },
      legend: { bottom: 0, textStyle: { color: AXIS } },
      grid: { left: 48, right: 16, top: 16, bottom: 40 },
      xAxis: { type: "category", data: w.labels, axisLabel: { color: AXIS } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS } },
      series: [
        { name: "Erreur 30 j", type: "line", smooth: true, data: w.wape_30, itemStyle: { color: "#053f24" }, areaStyle: { color: "rgba(5,63,36,0.12)" } },
        { name: "Erreur 7 j", type: "line", smooth: true, data: w.wape_7, itemStyle: { color: "#14a44d" } },
      ],
    });
    bindMlChart("chart-ml-windows", (p) => {
      const lab = (w.labels || [])[p.dataIndex] || "Période";
      mlOpen(`Contrôle · ${lab}`, `Erreur mesurée sur la période ${lab}.`, [
        ["Période", lab],
        ["Série", p.seriesName || "—"],
        ["Erreur", fmtPct(p.value)],
      ]);
    });

    const cat = c.reel_vs_prevu_cat || { labels: [], reel: [], prevu: [] };
    chart("chart-ml-cat", {
      tooltip: { trigger: "axis", ...tip },
      legend: { bottom: 0, textStyle: { color: AXIS } },
      grid: { left: 48, right: 12, top: 12, bottom: 72 },
      xAxis: { type: "category", data: cat.labels, axisLabel: { color: AXIS, rotate: 18, fontSize: 10 } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (x) => compact(x) } },
      series: [
        { name: "Réel", type: "bar", data: cat.reel, itemStyle: { color: "#053f24", borderRadius: [6, 6, 0, 0] } },
        { name: "Prévu", type: "bar", data: cat.prevu, itemStyle: { color: "#14a44d", borderRadius: [6, 6, 0, 0] } },
      ],
    });
    bindMlChart("chart-ml-cat", (p) => {
      const lab = (cat.labels || [])[p.dataIndex] || "Catégorie";
      const i = p.dataIndex;
      mlOpen(lab, `Réel vs prévu sur 30 j pour « ${lab} ».`, [
        ["Catégorie", lab],
        ["Réel", compact((cat.reel || [])[i])],
        ["Prévu", compact((cat.prevu || [])[i])],
      ]);
    });

    const ec = c.ecarts_produits || { labels: [], reel: [], prevu: [] };
    chart("chart-ml-ecarts", {
      tooltip: { trigger: "axis", ...tip },
      legend: { bottom: 0, textStyle: { color: AXIS } },
      grid: { left: 110, right: 16, top: 8, bottom: 40 },
      yAxis: { type: "category", data: [...(ec.labels || [])].reverse(), axisLabel: { color: AXIS, fontSize: 10 } },
      xAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS } },
      series: [
        { name: "Réel", type: "bar", data: [...(ec.reel || [])].reverse(), itemStyle: { color: "#053f24", borderRadius: [0, 6, 6, 0] } },
        { name: "Prévu", type: "bar", data: [...(ec.prevu || [])].reverse(), itemStyle: { color: "#14a44d", borderRadius: [0, 6, 6, 0] } },
      ],
    });
    bindMlChart("chart-ml-ecarts", (p) => {
      const labs = [...(ec.labels || [])].reverse();
      const lab = labs[p.dataIndex] || "Produit";
      mlOpen(lab, `Écart à surveiller sur « ${lab} ».`, [
        ["Produit", lab],
        ["Série", p.seriesName || "—"],
        ["Valeur", compact(p.value)],
      ]);
    });

    const wins = d.tables?.forecast_windows || v.windows || [];
    const fm = v.fenetres || {};
    if (el("ml-windows-meta")) {
      el("ml-windows-meta").textContent = `${fm.evaluees || wins.length} périodes contrôlées · planif OK : ${fm.victoires_planif ?? "—"} · jour OK : ${fm.victoires_quotidien ?? "—"}`;
    }
    if (el("ml-windows-table")) {
      el("ml-windows-table").innerHTML = !wins.length
        ? `<p class="chart-hint" style="padding:12px">Fenêtres indisponibles.</p>`
        : `<table><thead><tr>
          <th>Fenêtre</th><th>Début</th><th>Erreur jour</th><th>Erreur 7 j</th><th>Erreur 30 j</th><th>Biais</th>
        </tr></thead><tbody>${wins.map((r) => `<tr>
          <td>${r.fenetre}</td><td>${r.debut || "—"}</td>
          <td>${fmtPct(r.wape_day)}</td><td>${fmtPct(r.wape_7)}</td>
          <td>${fmtPct(r.wape_30)}</td><td>${fmtPct(r.biais)}</td>
        </tr>`).join("")}</tbody></table>`;
    }

    const f = d.tables?.forecast || [];
    if (el("ml-forecast-meta")) el("ml-forecast-meta").textContent = `${f.length} produits · /forecast/produits`;
    if (el("ml-forecast-table")) {
      el("ml-forecast-table").innerHTML = !f.length
        ? `<p class="chart-hint" style="padding:12px">Aucune donnée prévision.</p>`
        : `<table><thead><tr>
          <th>Produit</th><th>Catégorie</th><th>Réel 30j</th><th>Prévu 30j</th><th>Écart</th>
        </tr></thead><tbody>${f.map((r) => `<tr>
          <td>${r.produit}</td><td>${r.categorie || "—"}</td>
          <td>${compact(r.reel)}</td><td>${Number(r.prevu || 0).toFixed(1)}</td>
          <td>${Number(r.ecart || 0).toFixed(1)}</td>
        </tr>`).join("")}</tbody></table>`;
    }
  }

  function renderPricing(d) {
    const k = d.kpis || {};
    const vp = d.validation?.pricing || {};
    if (el("ml-service-meta-pr")) el("ml-service-meta-pr").textContent = serviceLine(d);
    if (el("kpi-ml-pricing")) {
      const nProd = k.n_pricing || (d.tables?.pricing || []).length || 0;
      const nNul = d.stats?.volume_nul_pricing ?? 0;
      el("kpi-ml-pricing").innerHTML = [
        kpiCard("hero", "Écart volume 7 j", fmtPct(k.pricing_wape), null),
        kpiCard("", "Marge moyenne", fmtPct(k.marge_moyenne), null),
        kpiCard("", "Produits catalogue", count ? count(nProd) : compact(nProd), null),
        kpiCard("", "Sans volume", count ? count(nNul) : compact(nNul), null),
      ].join("");
    }
    if (el("card-ml-pricing")) el("card-ml-pricing").innerHTML = heroCard(cardById(d, "pricing"));

    const tip = { ...TIP, valueFormatter: (x) => (typeof x === "number" ? `${x.toFixed(1)} %` : x) };
    const ps = (d.charts || {}).pricing_targets || { labels: [], wape_micro: [], wape_macro: [] };
    chart("chart-ml-pricing-scores", {
      tooltip: { trigger: "axis", ...tip },
      legend: { bottom: 0, textStyle: { color: AXIS } },
      grid: { left: 48, right: 12, top: 16, bottom: 40 },
      xAxis: { type: "category", data: ps.labels, axisLabel: { color: AXIS } },
      yAxis: { type: "value", name: "%", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS } },
      series: [
        { name: "Erreur détail", type: "bar", data: ps.wape_micro, itemStyle: { color: "#053f24", borderRadius: [6, 6, 0, 0] } },
        { name: "Erreur globale", type: "bar", data: ps.wape_macro, itemStyle: { color: "#14a44d", borderRadius: [6, 6, 0, 0] } },
      ],
    });

    const abc = (d.charts || {}).abc || { labels: [], values: [] };
    donut("chart-ml-abc", (abc.labels || []).map((name, i) => ({ name, value: abc.values[i] || 0 })), (p) => {
      mlOpen(p.name, `Classe ABC « ${p.name} » : ${compact(p.value)} produits.`, [
        ["Classe", p.name], ["Produits", compact(p.value)],
      ]);
    });
    bindMlChart("chart-ml-pricing-scores", (p) => {
      const lab = (ps.labels || [])[p.dataIndex] || "Scénario";
      mlOpen(lab, `Qualité du scénario « ${lab} ».`, [
        ["Objectif", lab],
        ["Série", p.seriesName || "—"],
        ["Erreur", fmtPct(p.value)],
      ]);
    });

    const scores = d.tables?.pricing_scores || vp.targets || [];
    if (el("ml-pricing-scores-meta")) el("ml-pricing-scores-meta").textContent = `${scores.length} scénarios · référence médiane produit`;
    if (el("ml-pricing-scores-table")) {
      el("ml-pricing-scores-table").innerHTML = !scores.length
        ? `<p class="chart-hint" style="padding:12px">Scores indisponibles.</p>`
        : `<table><thead><tr>
          <th>Objectif</th><th>Erreur globale</th><th>Erreur détail</th><th>Biais</th><th>Statut</th>
        </tr></thead><tbody>${scores.map((r) => `<tr>
          <td>${r.cible}</td><td>${fmtPct(r.wape_macro)}</td><td>${fmtPct(r.wape_micro)}</td>
          <td>${fmtPct(r.biais)}</td><td>${r.statut === "simulation_only" || /simulat/i.test(String(r.statut || "")) ? "Simulation" : (r.statut || "—")}</td>
        </tr>`).join("")}</tbody></table>`;
    }

    const p = d.tables?.pricing || [];
    if (el("ml-pricing-meta")) el("ml-pricing-meta").textContent = `${p.length} produits · simulation (aucun prix modifié en magasin)`;
    if (el("ml-pricing-table")) {
      el("ml-pricing-table").innerHTML = !p.length
        ? `<p class="chart-hint" style="padding:12px">Aucune donnée prix.</p>`
        : `<table><thead><tr>
          <th>Produit</th><th>Catégorie</th><th>Classe</th><th>Prix</th><th>Marge</th>
        </tr></thead><tbody>${p.slice(0, 40).map((r) => `<tr>
          <td>${r.produit}</td><td>${r.categorie || "—"}</td><td>${r.classe || "—"}</td>
          <td>${money(r.prix || 0)}</td><td>${fmtPct(r.marge_pct)}</td>
        </tr>`).join("")}</tbody></table>`;
    }
  }

  function renderReco(d) {
    const k = d.kpis || {};
    const vr = d.validation?.recommendation || {};
    if (el("ml-service-meta-rc")) el("ml-service-meta-rc").textContent = serviceLine(d);
    if (el("kpi-ml-reco")) {
      el("kpi-ml-reco").innerHTML = [
        kpiCard("hero", "Gain d’ordre achat", fmtPct(k.ndcg_gain_achat), null),
        kpiCard("", "Couverture catalogue", fmtPct(k.coverage), null),
        kpiCard("", "Rappel top 10", fmtPct(k.recall10), null),
        kpiCard("", "Produits suivis", count ? count(k.n_reco || 0) : compact(k.n_reco || 0), null),
      ].join("");
    }
    if (el("card-ml-reco")) el("card-ml-reco").innerHTML = heroCard(cardById(d, "reco"));

    const tip = { ...TIP, valueFormatter: (x) => (typeof x === "number" ? `${x.toFixed(1)} %` : x) };
    const gains = (d.charts || {}).reco_gains || { labels: [], values: [], default: [] };
    chart("chart-ml-reco-gains", {
      tooltip: { trigger: "axis", ...tip },
      grid: { left: 48, right: 16, top: 24, bottom: 36 },
      xAxis: { type: "category", data: gains.labels, axisLabel: { color: AXIS } },
      yAxis: { type: "value", name: "Gain %", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS } },
      series: [{
        type: "bar", barWidth: 36,
        data: (gains.values || []).map((val, i) => ({
          value: val,
          itemStyle: {
            color: (gains.default || [])[i] ? "#14a44d" : "#94a3b8",
            borderRadius: [8, 8, 0, 0],
          },
        })),
        label: { show: true, position: "top", formatter: (p) => `${Number(p.value).toFixed(1)} %`, color: AXIS },
      }],
    });
    bindMlChart("chart-ml-reco-gains", (p) => {
      const lab = (gains.labels || [])[p.dataIndex] || "Usage";
      mlOpen(lab, `Gain d’ordre vs best-sellers pour « ${lab} » : ${fmtPct(p.value)}.`, [
        ["Usage", lab], ["Gain", fmtPct(p.value)],
      ]);
    });

    const tip2 = { ...TIP, valueFormatter: (x) => (typeof x === "number" ? x.toFixed(0) : x) };
    const pop = (d.charts || {}).populaires || { labels: [], values: [], recent: [] };
    chart("chart-ml-pop", {
      tooltip: { trigger: "axis", ...tip2 },
      legend: { bottom: 0, textStyle: { color: AXIS } },
      grid: { left: 40, right: 12, top: 12, bottom: 48 },
      xAxis: { type: "category", data: pop.labels, axisLabel: { color: AXIS } },
      yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS } },
      series: [
        { name: "Popularité globale", type: "bar", data: pop.values, itemStyle: { color: "#053f24", borderRadius: [6, 6, 0, 0] } },
        { name: "28 derniers jours", type: "bar", data: pop.recent, itemStyle: { color: "#14a44d", borderRadius: [6, 6, 0, 0] } },
      ],
    });
    bindMlChart("chart-ml-pop", (p) => {
      const lab = (pop.labels || [])[p.dataIndex] || "Produit";
      mlOpen(lab, `Popularité de « ${lab} ».`, [
        ["Produit", lab],
        ["Série", p.seriesName || "—"],
        ["Score", compact(p.value)],
      ]);
    });

    const roles = d.tables?.reco_roles || vr.roles || [];
    if (el("ml-reco-roles-meta")) el("ml-reco-roles-meta").textContent = `${roles.length} usages · secours = best-sellers`;
    if (el("ml-reco-roles-table")) {
      el("ml-reco-roles-table").innerHTML = !roles.length
        ? `<p class="chart-hint" style="padding:12px">Usages indisponibles.</p>`
        : `<table><thead><tr>
          <th>Usage</th><th>Méthode</th><th>Gain d’ordre</th><th>Fiabilité</th><th>Statut</th><th>Proposé par défaut ?</th><th>Sinon</th>
        </tr></thead><tbody>${roles.map((r) => {
          const statut = /explor|test/i.test(String(r.statut || "")) ? "En test"
            : /valid/i.test(String(r.statut || "")) ? "Validé pour le site"
            : (r.statut || "—");
          const methode = r.modele === "CatBoostRanker" ? "Classement avancé"
            : r.modele === "pointwise_conversion" ? "Conversion panier"
            : (r.modele || "—");
          return `<tr>
          <td>${r.role}</td><td>${methode}</td>
          <td>${fmtPct(r.gain_ndcg10)}</td>
          <td>${r.p_holm != null ? (Number(r.p_holm) < 0.05 ? "Fiable" : "À confirmer") : "—"}</td>
          <td>${statut}</td><td>${r.par_defaut === "oui" ? "Oui" : "Non"}</td>
          <td>Best-sellers</td>
        </tr>`;
        }).join("")}</tbody></table>`;
    }

    const r = d.tables?.reco || [];
    if (el("ml-reco-meta")) el("ml-reco-meta").textContent = `${r.length} produits · /recommendations/produits`;
    if (el("ml-reco-table")) {
      el("ml-reco-table").innerHTML = !r.length
        ? `<p class="chart-hint" style="padding:12px">Aucune donnée popularité.</p>`
        : `<table><thead><tr>
          <th>Rang</th><th>Produit</th><th>Catégorie</th><th>Popularité</th><th>28 j</th><th>Prix</th>
        </tr></thead><tbody>${r.slice(0, 40).map((row) => `<tr>
          <td>${row.rang ?? "—"}</td><td>${row.produit}</td><td>${row.categorie || "—"}</td>
          <td>${compact(row.pop)}</td><td>${compact(row.pop_28j)}</td><td>${money(row.prix || 0)}</td>
        </tr>`).join("")}</tbody></table>`;
    }
  }

  function paint(d) {
    if (!d || !hasData(d)) return;
    ML = d;
    window.ML_DATA = d;
    const view = typeof CURRENT_VIEW !== "undefined" ? CURRENT_VIEW : "";
    if (view === "ml-forecast" || !view || view === "dashboard") renderForecast(d);
    if (view === "ml-pricing") renderPricing(d);
    if (view === "ml-reco") renderReco(d);
    // Toujours préparer les 3 vues pour éviter écran vide au switch
    if (ML_VIEWS.has(view)) {
      renderForecast(d);
      renderPricing(d);
      renderReco(d);
    }
    requestAnimationFrame(() => {
      forceResizeMl();
      setTimeout(forceResizeMl, 60);
      setTimeout(() => {
        forceResizeMl();
        if (typeof rebindAllDrills === "function") rebindAllDrills();
      }, 200);
      setTimeout(() => {
        forceResizeMl();
        if (typeof rebindAllDrills === "function") rebindAllDrills();
      }, 300);
    });
  }

  async function loadCacheFirst() {
    try {
      const res = await fetch("/static/data/models_cache.json", { cache: "no-store" });
      if (!res.ok) return null;
      const data = await res.json();
      return hasData(data) ? data : null;
    } catch {
      return null;
    }
  }

  async function loadApi(force = false) {
    const url = force ? "/api/models?force=1" : "/api/models";
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  window.loadModelsLive = async function (force = false) {
    if (loading && !force) {
      if (ML) paint(ML);
      return;
    }

    // 1) Affiche tout de suite le cache local
    if (!ML) {
      const cached = await loadCacheFirst();
      if (cached) paint(cached);
    } else if (isMlView()) {
      paint(ML);
    }

    if (loading) return;
    loading = true;
    try {
      const live = await loadApi(force || !hasData(ML));
      if (hasData(live)) paint(live);
    } catch (err) {
      console.error("API modèles:", err);
      if (!ML) {
        const meta = el("ml-forecast-meta");
        if (meta) meta.textContent = "API lente — réessaie dans un instant";
      }
    } finally {
      loading = false;
    }
  };

  window.paintModelsView = function () {
    if (ML) paint(ML);
    else window.loadModelsLive(false);
  };

  // Précharge cache dès l’ouverture (immédiat)
  window.loadModelsLive(false);
})();
