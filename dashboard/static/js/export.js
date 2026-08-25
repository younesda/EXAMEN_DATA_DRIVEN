/* Excel + HTML : un export par menu (lignes du tableau de la vue active) */
(function () {
  const C_GREEN = "FF053F24";
  const C_HEADER_BG = "FF053F24";
  const C_ALT = "FFEEF7F0";
  const C_WHITE = "FFFFFFFF";

  const FILTER_FR = {
    annee: "Année",
    mois: "Mois",
    weekend: "Semaine / week-end",
    promo: "Promotion",
    statut: "Statut",
    region: "Région",
    client: "Client",
    categorie: "Catégorie",
    marque: "Marque",
    produit: "Produit",
    segment: "Segment",
    age: "Âge",
    appareil: "Appareil",
    source_trafic: "Source trafic",
    stock_level: "Niveau stock",
    q: "Recherche",
  };

  const VIEW_LABEL = {
    dashboard: "Ventes",
    ventes: "Ventes",
    produits: "Produits",
    clients: "Clients",
    stock: "Stock",
    "ml-forecast": "Prévisions ventes",
    "ml-pricing": "Simulation prix",
    "ml-reco": "Recommandation",
  };

  function stamp() {
    return new Date().toISOString().slice(0, 10);
  }

  function currentView() {
    return typeof CURRENT_VIEW !== "undefined" ? CURRENT_VIEW : "dashboard";
  }

  function viewTitle(view) {
    return VIEW_LABEL[view] || view;
  }

  function filterLabel(key, val) {
    if (typeof labelForFilter === "function") return labelForFilter(key, val);
    if (key === "mois" && window.MOIS_FR) return MOIS_FR[Number(val)] || val;
    return val;
  }

  function filtersRows() {
    const f = DATA?.active_filters || {};
    return Object.keys(f).length
      ? Object.entries(f).map(([k, v]) => [FILTER_FR[k] || k, filterLabel(k, v)])
      : [["Filtres", "Aucun — données complètes"]];
  }

  function yieldUi() {
    return new Promise((r) => setTimeout(r, 0));
  }

  function thinBorder() {
    return {
      top: { style: "thin", color: { argb: "FFE0E0E0" } },
      left: { style: "thin", color: { argb: "FFE0E0E0" } },
      bottom: { style: "thin", color: { argb: "FFE0E0E0" } },
      right: { style: "thin", color: { argb: "FFE0E0E0" } },
    };
  }

  function styleHeader(ws, rowNum, cols) {
    const row = ws.getRow(rowNum);
    row.height = 24;
    for (let c = 1; c <= cols; c++) {
      const cell = row.getCell(c);
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: C_HEADER_BG } };
      cell.font = { bold: true, color: { argb: C_WHITE }, size: 11 };
      cell.alignment = { vertical: "middle", horizontal: "center", wrapText: true };
      cell.border = thinBorder();
    }
  }

  function styleDataRows(ws, startRow, endRow, cols) {
    for (let r = startRow; r <= endRow; r++) {
      const alt = (r - startRow) % 2 === 1;
      for (let c = 1; c <= cols; c++) {
        const cell = ws.getCell(r, c);
        if (alt) cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: C_ALT } };
        cell.border = thinBorder();
        cell.alignment = { vertical: "middle" };
      }
    }
  }

  function downloadBuffer(buffer, filename) {
    const blob = new Blob([buffer], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function downloadText(html, filename) {
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtNum(n) {
    return typeof compact === "function" ? compact(n) : n;
  }

  function statutLabel(s) {
    return (window.STATUT_FR && STATUT_FR[s]) || s;
  }

  function niveauLabel(s) {
    return (window.NIVEAU_FR && NIVEAU_FR[s]) || s;
  }

  async function fetchVentesRows() {
    const qs = typeof filterQuery === "function" ? filterQuery() : "";
    const url = qs ? `/api/export/lignes?${qs}` : "/api/export/lignes";
    const res = await fetch(url);
    if (!res.ok) throw new Error("Export serveur indisponible");
    return res.json();
  }

  /** Pack d’export propre à la vue active (feuilles + graphiques HTML). */
  async function buildExportPack(view) {
    const ml = window.ML_DATA || null;

    if (view === "produits") {
      const rows = DATA?.produits_detail || [];
      const top = [...rows].sort((a, b) => (b.ca || 0) - (a.ca || 0)).slice(0, 12);
      const cats = DATA?.categories || [];
      return {
        detailNote: "Tableau : chaque produit filtré (catégorie, marque, commandes, qté, CA, lignes).",
        sheets: [{
          name: "Produits",
          headers: ["Produit", "Catégorie", "Marque", "1re vente", "Dernière", "Commandes", "Qté vendue", "CA (F CFA)", "Lignes"],
          rows: rows.map((r) => [r.produit, r.categorie, r.marque, r.premiere || "—", r.derniere || "—", r.commandes, r.quantite, r.ca, r.lignes]),
        }],
        summary: [
          ["Produits", rows.length],
          ["CA total", rows.reduce((s, r) => s + (r.ca || 0), 0)],
        ],
        charts: [
          { id: "c1", title: "Top produits par CA", type: "bar", labels: top.map((r) => r.produit), values: top.map((r) => r.ca), unit: " F" },
          { id: "c2", title: "CA par catégorie", type: "doughnut", labels: cats.map((c) => c.name), values: cats.map((c) => c.value), unit: " F" },
        ],
      };
    }

    if (view === "clients") {
      const rows = DATA?.clients_detail || [];
      const top = [...rows].sort((a, b) => (b.ca || 0) - (a.ca || 0)).slice(0, 12);
      const segs = DATA?.segments || [];
      const vips = rows.filter((r) => r.statut_client === "vip" || r.vip);
      const loyaux = rows.filter((r) => r.statut_client === "loyal" || r.loyal);
      const inactifs = rows.filter((r) => r.statut_client === "inactif" || r.inactif);
      const churns = rows.filter((r) => r.statut_client === "churn" || r.churn || Number(r.jours_inactif) >= 730);
      const mapRow = (r) => [r.client, r.region, r.statut_client || "", r.age, r.premiere || "—", r.derniere || "—", r.jours_inactif, r.commandes, r.freq_mois, r.panier_moyen, r.ca || r.ca_historique || 0];
      const headers = ["Client", "Région", "Statut", "Âge", "1re achat", "Dernier", "Jours sans achat", "Commandes", "Fréq. cmd/mois", "Panier moy.", "CA (F CFA)"];
      return {
        detailNote: "VIP = très fréquents · Loyaux = réguliers · Inactifs = 6 mois–2 ans · Churn = ≥ 2 ans sans achat.",
        sheets: [
          { name: "VIP", headers, rows: vips.map(mapRow) },
          { name: "Loyaux", headers, rows: loyaux.map(mapRow) },
          { name: "Inactifs", headers, rows: inactifs.map(mapRow) },
          { name: "Churn", headers, rows: churns.map(mapRow) },
          {
            name: "Clients",
            headers,
            rows: rows.map(mapRow),
          },
        ],
        summary: [
          ["Clients (KPI)", DATA?.kpis?.clients],
          ["VIP", DATA?.kpis?.clients_vip ?? vips.length],
          ["Loyaux", DATA?.kpis?.clients_loyal ?? loyaux.length],
          ["Inactifs", DATA?.kpis?.clients_inactif ?? inactifs.length],
          ["Churn (≥ 2 ans)", DATA?.kpis?.clients_churn ?? churns.length],
          ["CA VIP %", DATA?.kpis?.ca_vip_share],
        ],
        charts: [
          { id: "c1", title: "Top clients par CA", type: "bar", labels: top.map((r) => r.client), values: top.map((r) => r.ca), unit: " F" },
          { id: "c2", title: "CA par segment Mozart", type: "doughnut", labels: segs.map((s) => s.name), values: segs.map((s) => s.value), unit: " F" },
        ],
      };
    }

    if (view === "stock") {
      const rows = DATA?.stock_detail || [];
      const byNiv = {};
      rows.forEach((r) => {
        const n = niveauLabel(r.niveau) || r.niveau || "?";
        byNiv[n] = (byNiv[n] || 0) + 1;
      });
      const low = [...rows].sort((a, b) => (a.stock || 0) - (b.stock || 0)).slice(0, 12);
      return {
        detailNote: "Tableau : chaque référence stock (niveau, quantité, prix catalogue).",
        sheets: [{
          name: "Stock",
          headers: ["Produit", "Catégorie", "Marque", "Stock", "Niveau", "Prix catalogue"],
          rows: rows.map((r) => [r.produit, r.categorie, r.marque, r.stock, niveauLabel(r.niveau), r.prix_catalogue || 0]),
        }],
        summary: [
          ["Références", rows.length],
          ["Ruptures", rows.filter((r) => r.niveau === "rupture").length],
        ],
        charts: [
          { id: "c1", title: "Répartition des niveaux", type: "doughnut", labels: Object.keys(byNiv), values: Object.values(byNiv), unit: "" },
          { id: "c2", title: "Stocks les plus bas", type: "bar", labels: low.map((r) => r.produit), values: low.map((r) => r.stock), unit: "" },
        ],
      };
    }

    if (view === "ml-forecast") {
      if (!ml) throw new Error("Données prévisions non chargées — ouvre le menu Prévisions puis réessaie.");
      const wins = ml.tables?.forecast_windows || ml.validation?.forecast?.windows || [];
      const prods = ml.tables?.forecast || [];
      const horizons = ml.charts?.precision_horizons || {};
      const top = prods.slice(0, 10);
      return {
        detailNote: "Tableaux : produits (réel / prévu / écart 30 j) et périodes de contrôle (erreurs).",
        sheets: [
          {
            name: "Détail produits",
            headers: ["Produit", "Catégorie", "Réel 30j", "Prévu 30j", "Écart"],
            rows: prods.map((r) => [r.produit, r.categorie || "", r.reel, r.prevu, r.ecart]),
          },
          {
            name: "Périodes contrôle",
            headers: ["Fenêtre", "Début", "Erreur jour", "Erreur 7 j", "Erreur 30 j", "Biais"],
            rows: wins.map((r) => [r.fenetre, r.debut || "", r.wape_day, r.wape_7, r.wape_30, r.biais]),
          },
        ],
        summary: [
          ["Produits écarts", prods.length],
          ["Périodes", wins.length],
          ["Erreur 30 j (%)", ml.kpis?.wape_30],
        ],
        charts: [
          {
            id: "c1", title: "Erreur selon l’horizon", type: "bar",
            labels: horizons.labels || ["Au jour", "7 j", "30 j"],
            values: horizons.values || [ml.kpis?.wape_day, ml.kpis?.wape_7, ml.kpis?.wape_30],
            unit: " %",
          },
          {
            id: "c2", title: "Plus gros écarts produits", type: "bar",
            labels: top.map((r) => r.produit),
            values: top.map((r) => Math.abs(Number(r.ecart) || 0)),
            unit: "",
          },
        ],
      };
    }

    if (view === "ml-pricing") {
      if (!ml) throw new Error("Données pricing non chargées — ouvre le menu Simulation prix puis réessaie.");
      const scores = ml.tables?.pricing_scores || ml.validation?.pricing?.targets || [];
      const prods = ml.tables?.pricing || [];
      const abc = ml.charts?.abc || { labels: [], values: [] };
      const ps = ml.charts?.pricing_targets || {};
      return {
        detailNote: "Tableaux : catalogue prix/marge par produit, et qualité des scénarios (erreurs). Simulation — aucun prix modifié en magasin.",
        sheets: [
          {
            name: "Catalogue prix",
            headers: ["Produit", "Catégorie", "Classe", "Prix", "Marge %"],
            rows: prods.map((r) => [r.produit, r.categorie || "", r.classe || "", r.prix || 0, r.marge_pct]),
          },
          {
            name: "Scénarios",
            headers: ["Objectif", "Erreur globale", "Erreur détail", "Biais", "Statut"],
            rows: scores.map((r) => [
              r.cible, r.wape_macro, r.wape_micro, r.biais,
              /simulat/i.test(String(r.statut || "")) ? "Simulation" : (r.statut || "—"),
            ]),
          },
        ],
        summary: [
          ["Produits", prods.length],
          ["Scénarios", scores.length],
          ["Écart volume 7 j (%)", ml.kpis?.pricing_wape],
          ["Marge moyenne (%)", ml.kpis?.marge_moyenne],
        ],
        charts: [
          {
            id: "c1", title: "Qualité des scénarios", type: "bar",
            labels: ps.labels || scores.map((r) => r.cible),
            datasets: [
              { label: "Erreur détail", data: ps.wape_micro || scores.map((r) => r.wape_micro) },
              { label: "Erreur globale", data: ps.wape_macro || scores.map((r) => r.wape_macro) },
            ],
            unit: " %",
          },
          {
            id: "c2", title: "Classes ABC", type: "doughnut",
            labels: abc.labels || [], values: abc.values || [], unit: "",
          },
        ],
      };
    }

    if (view === "ml-reco") {
      if (!ml) throw new Error("Données reco non chargées — ouvre le menu Recommandation puis réessaie.");
      const roles = ml.tables?.reco_roles || ml.validation?.recommendation?.roles || [];
      const prods = ml.tables?.reco || [];
      const gains = ml.charts?.reco_gains || {};
      const pop = ml.charts?.populaires || {};
      return {
        detailNote: "Tableaux : liste popularité (rang, produit, scores) et usages validés (gain d’ordre).",
        sheets: [
          {
            name: "Popularité",
            headers: ["Rang", "Produit", "Catégorie", "Popularité", "28 j", "Prix"],
            rows: prods.map((r) => [r.rang, r.produit, r.categorie || "", r.pop, r.pop_28j, r.prix || 0]),
          },
          {
            name: "Usages validés",
            headers: ["Usage", "Méthode", "Gain d’ordre", "Fiabilité", "Statut", "Par défaut"],
            rows: roles.map((r) => [r.role, r.modele, r.gain_ndcg10, r.p_holm, r.statut, r.par_defaut]),
          },
        ],
        summary: [
          ["Produits", prods.length],
          ["Usages", roles.length],
          ["Gain d’ordre (%)", ml.kpis?.ndcg_gain_achat],
          ["Couverture (%)", ml.kpis?.coverage],
        ],
        charts: [
          {
            id: "c1", title: "Gain d’ordre vs best-sellers", type: "bar",
            labels: gains.labels || roles.map((r) => r.role),
            values: gains.values || roles.map((r) => r.gain_ndcg10),
            unit: " %",
          },
          {
            id: "c2", title: "Best-sellers", type: "bar",
            labels: pop.labels || prods.slice(0, 10).map((r) => r.produit),
            datasets: [
              { label: "Popularité", data: pop.values || prods.slice(0, 10).map((r) => r.pop) },
              { label: "28 j", data: pop.recent || prods.slice(0, 10).map((r) => r.pop_28j) },
            ],
            unit: "",
          },
        ],
      };
    }

    /* dashboard / ventes */
    const pack = await fetchVentesRows();
    const rows = pack.lignes || [];
    const cats = (DATA?.categories || []).slice(0, 8);
    const ts = DATA?.timeseries || {};
    return {
      detailNote: "Tableau : chaque ligne de vente (ID, commande, date, produit, catégorie, qté, prix, montant, statut).",
      sheets: [{
        name: "Lignes ventes",
        headers: ["ID", "COMMANDE", "DATE", "PRODUIT", "CATEGORIE", "QTE", "PRIX", "MONTANT", "STATUT"],
        rows: rows.map((r) => [
          r.vente_id ?? "",
          r.id ?? "",
          r.date ?? "",
          r.produit ?? "",
          r.categorie ?? "",
          r.quantite ?? 0,
          r.prix_unitaire ?? 0,
          r.montant ?? 0,
          statutLabel(r.statut),
        ]),
      }],
      summary: [
        ["CA net (F CFA)", DATA?.kpis?.ca],
        ["Commandes", DATA?.kpis?.commandes],
        ["Unités", DATA?.kpis?.qty],
        ["Panier moyen", DATA?.kpis?.panier_moyen],
        ["Marge %", DATA?.kpis?.margin_pct],
        ["Lignes", pack.total ?? rows.length],
      ],
      charts: [
        {
          id: "c1", title: "Evolution CA — style Power BI", type: "line",
          labels: (ts.labels || []).slice(-12),
          values: (ts.values || []).slice(-12),
          unit: " F",
        },
        {
          id: "c2", title: "Répartition catégories — Top N", type: "doughnut",
          labels: cats.map((c) => c.name),
          values: cats.map((c) => c.value),
          unit: " F",
        },
      ],
      truncated: pack.truncated,
      total: pack.total,
    };
  }

  async function writeBrandedSheet(wb, view, pack, sheet, isPrimary) {
    const ws = wb.addWorksheet((sheet.name || "Détail").slice(0, 31));
    const headers = sheet.headers || [];
    const data = sheet.rows || [];
    const n = Math.max(headers.length, (pack.summary || []).length, 6);

    ws.columns = Array.from({ length: n }, (_, i) => ({
      width: i === 3 ? 34 : i < 2 ? 14 : 14,
    }));
    if (headers.length >= 4) ws.getColumn(4).width = 36;
    if (headers.length >= 5) ws.getColumn(5).width = 24;

    let rowPtr = 1;
    if (isPrimary) {
      ws.mergeCells(1, 1, 1, Math.min(n, 6));
      const title = ws.getCell(1, 1);
      title.value = "Teranga BI — Données de l'analyse";
      title.font = { bold: true, size: 16, color: { argb: C_GREEN } };
      title.alignment = { vertical: "middle" };
      ws.getRow(1).height = 28;

      ws.mergeCells(2, 1, 2, Math.min(n, 6));
      const meta = ws.getCell(2, 1);
      meta.value = `Généré le ${new Date().toLocaleString("fr-FR")} · ${DATA?.source || "—"} · Vue ${view}`;
      meta.font = { size: 10, color: { argb: "FF5B6B64" } };

      const labels = (pack.summary || []).map((r) => r[0]);
      const values = (pack.summary || []).map((r) => r[1]);
      const kpiRow = 4;
      const kh = ws.getRow(kpiRow);
      kh.height = 22;
      labels.forEach((lab, i) => {
        const cell = kh.getCell(i + 1);
        cell.value = lab;
        cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: C_HEADER_BG } };
        cell.font = { bold: true, color: { argb: C_WHITE }, size: 10 };
        cell.alignment = { horizontal: "center", vertical: "middle", wrapText: true };
      });
      const kv = ws.getRow(kpiRow + 1);
      kv.height = 24;
      values.forEach((val, i) => {
        const cell = kv.getCell(i + 1);
        cell.value = typeof val === "number" ? val : (Number(val) || val);
        cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: C_ALT } };
        cell.font = { bold: true, size: 11, color: { argb: C_GREEN } };
        cell.alignment = { horizontal: "center", vertical: "middle" };
        if (typeof val === "number" || !Number.isNaN(Number(val))) cell.numFmt = "#,##0";
      });
      rowPtr = 8;
    }

    const headerRowNum = rowPtr;
    const hr = ws.getRow(headerRowNum);
    hr.height = 26;
    headers.forEach((h, i) => {
      const cell = hr.getCell(i + 1);
      cell.value = String(h).toUpperCase();
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: C_HEADER_BG } };
      cell.font = { bold: true, color: { argb: C_WHITE }, size: 11 };
      cell.alignment = { vertical: "middle", horizontal: "center" };
      cell.border = thinBorder();
    });

    const chunk = 4000;
    for (let i = 0; i < data.length; i += chunk) {
      ws.addRows(data.slice(i, i + chunk));
      await yieldUi();
    }

    const firstData = headerRowNum + 1;
    const last = headerRowNum + data.length;
    if (data.length) {
      styleDataRows(ws, firstData, Math.min(last, firstData + 4999), headers.length);
      /* Alignement nombres à droite quand colonnes numériques connues */
      const numHints = /qté|qte|prix|montant|ca|stock|commande|ligne|unité|pop|écart|réel|prévu/i;
      headers.forEach((h, i) => {
        if (numHints.test(String(h))) {
          for (let r = firstData; r <= Math.min(last, firstData + 2000); r++) {
            const cell = ws.getCell(r, i + 1);
            if (typeof cell.value === "number") {
              cell.numFmt = "#,##0";
              cell.alignment = { horizontal: "right", vertical: "middle" };
            }
          }
        }
      });
      ws.autoFilter = {
        from: { row: headerRowNum, column: 1 },
        to: { row: last, column: headers.length },
      };
    }
    ws.views = [{
      state: "frozen",
      xSplit: 0,
      ySplit: headerRowNum,
      topLeftCell: `A${headerRowNum + 1}`,
      activeCell: `A${headerRowNum + 1}`,
    }];
  }

  function addFiltersSheet(wb) {
    const ctx = wb.addWorksheet("Filtres");
    ctx.columns = [{ width: 28 }, { width: 40 }];
    ctx.getCell(1, 1).value = "Teranga";
    ctx.getCell(1, 1).fill = { type: "pattern", pattern: "solid", fgColor: { argb: C_HEADER_BG } };
    ctx.getCell(1, 1).font = { bold: true, color: { argb: C_WHITE }, size: 12 };
    ctx.getCell(1, 1).alignment = { horizontal: "center", vertical: "middle" };
    ctx.getRow(1).height = 28;
    ctx.getCell(1, 2).value = "Filtres actifs";
    ctx.getCell(1, 2).font = { bold: true, size: 13, color: { argb: C_GREEN } };
    ctx.addRow([]);
    ctx.addRow(["Filtre", "Valeur"]);
    styleHeader(ctx, 3, 2);
    const fr = filtersRows();
    fr.forEach((r) => ctx.addRow(r));
    styleDataRows(ctx, 4, 3 + Math.max(fr.length, 1), 2);
  }

  async function buildWorkbook(view, pack) {
    const Excel = window.ExcelJS;
    if (!Excel) throw new Error("ExcelJS indisponible");
    const wb = new Excel.Workbook();
    wb.creator = "Teranga BI";

    const sheets = (pack.sheets || []).filter((s) => (s.rows || []).length);
    if (!sheets.length) throw new Error("Aucune ligne à exporter pour ce menu.");

    for (let i = 0; i < sheets.length; i++) {
      await writeBrandedSheet(wb, view, pack, sheets[i], i === 0);
    }
    addFiltersSheet(wb);
    return wb;
  }

  async function exportExcel() {
    const view = currentView();
    if (!DATA && !String(view).startsWith("ml")) {
      alert("Aucune donnée à exporter.");
      return;
    }
    const btn = el("export-excel");
    const prev = btn?.textContent;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Excel…";
    }
    try {
      if (String(view).startsWith("ml") && !window.ML_DATA && typeof window.loadModelsLive === "function") {
        btn.textContent = "Excel… modèles";
        await window.loadModelsLive(false);
      }
      const pack = await buildExportPack(view);
      const n = (pack.sheets || []).reduce((s, sh) => s + (sh.rows || []).length, 0);
      if (btn) btn.textContent = `Excel… ${n} lignes`;
      const wb = await buildWorkbook(view, pack);
      const buffer = await wb.xlsx.writeBuffer();
      downloadBuffer(buffer, `teranga-${view}-${stamp()}.xlsx`);
      if (pack.truncated) {
        console.info(`Export tronqué : ${n} lignes sur ${pack.total}. Affinez les filtres pour le reste.`);
      }
    } catch (e) {
      console.error(e);
      alert("Export Excel impossible : " + e.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = prev || "Excel";
      }
    }
  }

  /** Export Excel ciblé : vip | loyal | inactif | churn */
  async function exportClientSegment(kind) {
    const rows = DATA?.clients_detail || [];
    if (!rows.length) {
      alert("Aucune donnée clients à exporter.");
      return;
    }
    const labels = {
      vip: "VIP",
      loyal: "Loyaux",
      inactif: "Inactifs",
      churn: "Churn",
    };
    const list = rows.filter((r) => {
      const st = r.statut_client || (r.vip ? "vip" : r.loyal ? "loyal" : r.inactif ? "inactif" : r.churn ? "churn" : "");
      if (kind === "churn") return st === "churn" || Number(r.jours_inactif) >= 730;
      return st === kind;
    });
    if (!list.length) {
      alert(`Aucun client « ${labels[kind] || kind} » à exporter.`);
      return;
    }
    const btn = el(`export-${kind}-xlsx`);
    const prev = btn?.textContent;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Excel…";
    }
    try {
      const notes = {
        vip: "VIP = achats très fréquents (≈ chaque semaine / ≥ 1,5 cmd/mois).",
        loyal: "Loyaux = achètent régulièrement, moins souvent que les VIP.",
        inactif: "Inactifs = 6 mois à moins de 2 ans sans achat.",
        churn: "Churn = ≥ 2 ans sans achat (clients partis).",
      };
      const pack = {
        detailNote: notes[kind] || "",
        sheets: [{
          name: labels[kind] || kind,
          headers: ["Client", "Région", "Statut", "Âge", "1re achat", "Dernier", "Jours sans achat", "Commandes", "Fréq. cmd/mois", "Panier moy.", "CA (F CFA)"],
          rows: list.map((r) => [r.client, r.region, kind, r.age, r.premiere || "—", r.derniere || "—", r.jours_inactif, r.commandes, r.freq_mois, r.panier_moyen, r.ca || r.ca_historique || 0]),
        }],
        summary: [
          [labels[kind] || kind, list.length],
          ["CA total liste", list.reduce((s, r) => s + (r.ca || r.ca_historique || 0), 0)],
        ],
      };
      const wb = await buildWorkbook("clients", pack);
      const buffer = await wb.xlsx.writeBuffer();
      downloadBuffer(buffer, `teranga-${kind}-${stamp()}.xlsx`);
    } catch (e) {
      console.error(e);
      alert("Export Excel impossible : " + e.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = prev || "Excel";
      }
    }
  }

  function sheetToHtmlTable(sheet, maxRows) {
    const rows = (sheet.rows || []).slice(0, maxRows);
    const th = sheet.headers.map((h) => `<th>${esc(String(h).toUpperCase())}</th>`).join("");
    const body = rows.map((row) =>
      `<tr>${row.map((c, i) => {
        const num = typeof c === "number" || (c !== "" && c != null && !Number.isNaN(Number(c)) && String(c).trim() !== "" && /^-?\d/.test(String(c)));
        return `<td class="${num ? "num" : ""}">${esc(c)}</td>`;
      }).join("")}</tr>`
    ).join("") || `<tr><td colspan="${sheet.headers.length}">Aucune ligne</td></tr>`;
    return `<thead><tr>${th}</tr></thead><tbody>${body}</tbody>`;
  }

  async function exportHtml() {
    const view = currentView();
    if (!DATA && !String(view).startsWith("ml")) {
      alert("Aucune donnée à exporter.");
      return;
    }
    try {
      if (String(view).startsWith("ml") && !window.ML_DATA && typeof window.loadModelsLive === "function") {
        await window.loadModelsLive(false);
      }
      const pack = await buildExportPack(view);
      const sheets = (pack.sheets || []).filter((s) => (s.rows || []).length);
      if (!sheets.length) {
        alert("Aucune ligne à exporter pour ce menu.");
        return;
      }

      const hasFilters = Object.keys(DATA?.active_filters || {}).length > 0;
      const filterChips = filtersRows()
        .map(([a, b]) => `<span class="chip"><b>${esc(a)}</b> ${esc(b)}</span>`)
        .join("");

      const totalLines = sheets.reduce((s, sh) => s + (sh.rows || []).length, 0);
      const shownCap = 2500;

      /* KPI présentation : pour ventes, format image 1 (5 cartes) */
      let kpiCards = pack.summary || [];
      if (view === "dashboard" || view === "ventes") {
        const k = DATA?.kpis || {};
        kpiCards = [
          ["CA net", `${fmtNum(k.ca)} F`],
          ["Commandes", fmtNum(k.commandes)],
          ["Unités", fmtNum(k.qty)],
          ["Panier moyen", `${fmtNum(k.panier_moyen)} F`],
          ["Marge", `${Number(k.margin_pct || 0).toFixed(1)} %`],
        ];
      }
      const summaryHtml = kpiCards
        .map(([a, b]) => `<div class="kpi"><span>${esc(a)}</span><b>${esc(b)}</b></div>`)
        .join("");

      const charts = (pack.charts || []).filter((c) => (c.labels || []).length);
      const chartTitles = {
        c1: view === "dashboard" || view === "ventes" ? "Evolution CA — style Power BI" : null,
        c2: view === "dashboard" || view === "ventes" ? "Répartition catégories — Top N" : null,
      };
      const chartsHtml = charts.length
        ? `<section>
            <h2>Visualisations graphiques</h2>
            <p class="hint">Aire (évolution) et donut (répartition) — style Power BI — survolez pour le détail · ${totalLines} ligne(s) agrégées.</p>
            <div class="charts">${charts.map((c) => `
              <div class="chart-box">
                <h3>${esc(chartTitles[c.id] || c.title)}</h3>
                <canvas id="${esc(c.id)}"></canvas>
              </div>`).join("")}
            </div>
          </section>`
        : "";

      const tablesHtml = sheets.map((s, idx) => {
        const total = (s.rows || []).length;
        const title = idx === 0 ? "Données de l'analyse" : s.name;
        return `<section>
          <h2>${esc(title)}</h2>
          <p class="hint">${esc(pack.detailNote || "Tableau détail ligne à ligne.")}${total > shownCap ? ` (${shownCap} premières affichées)` : ""}</p>
          <div style="overflow-x:auto"><table>${sheetToHtmlTable(s, shownCap)}</table></div>
        </section>`;
      }).join("");

      const chartPayload = JSON.stringify(charts.map((c) => ({
        id: c.id,
        type: c.type || "bar",
        labels: c.labels || [],
        values: c.values || null,
        datasets: c.datasets || null,
        unit: c.unit || "",
      })));

      const html = `<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<title>Teranga BI — Rapport ${stamp()}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"><\/script>
<style>
  :root { --green:#053f24; --accent:#14a44d; --bg:#f3f8f4; --alt:#eef7f0; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:Segoe UI,Inter,sans-serif; background:var(--bg); color:#14201b; }
  .wrap { max-width:1080px; margin:0 auto; padding:28px 20px 56px; }
  .topbar { display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom:18px; }
  .brand { display:flex; align-items:center; gap:12px; }
  .logo {
    min-width:88px; height:44px; padding:0 12px; border-radius:10px;
    background:var(--green); color:#fff; display:grid; place-items:center;
    font-weight:800; font-size:14px; letter-spacing:0.02em;
  }
  .brand strong { display:block; font-size:1.05rem; }
  .brand small { color:#5b6b64; font-size:.8rem; }
  .badge { display:inline-block; background:#d8efe0; color:var(--green); font-size:.72rem; font-weight:700; padding:4px 10px; border-radius:999px; }
  h1 { margin:0 0 6px; font-size:1.55rem; }
  .sub { color:#5b6b64; margin:0 0 14px; }
  .info { background:#e8f5ec; border-radius:12px; padding:12px 16px; margin-bottom:16px; font-size:.9rem; }
  .info ul { margin:0; padding-left:18px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
  .chip { background:#fff; border:1px solid #c8e6c9; padding:5px 11px; border-radius:999px; font-size:.82rem; }
  section { background:#fff; border-radius:14px; padding:18px 20px; margin-bottom:16px; box-shadow:0 2px 14px rgba(5,63,36,.07); }
  h2 { margin:0 0 12px; font-size:1.05rem; display:flex; align-items:center; gap:10px; }
  h2::before { content:""; width:4px; height:1.1em; background:var(--accent); border-radius:2px; }
  .hint { font-size:.85rem; color:#5b6b64; margin:0 0 14px; }
  .charts { display:grid; grid-template-columns:1.15fr .85fr; gap:16px; }
  @media (max-width:800px){ .charts { grid-template-columns:1fr; } }
  .chart-box { background:#fff; border:1px solid #e6efe8; border-radius:12px; padding:14px 14px 10px; min-height:280px; }
  .chart-box h3 { margin:0 0 10px; font-size:.9rem; color:var(--green); font-weight:700; }
  .chart-box canvas { max-height:230px; }
  table { width:100%; border-collapse:collapse; font-size:.82rem; }
  th { background:var(--green); color:#fff; text-transform:uppercase; letter-spacing:.03em; padding:10px 8px; text-align:left; font-size:.72rem; }
  td { padding:9px 8px; border-bottom:1px solid #e8eee9; }
  tr:nth-child(even) td { background:#f7fbf8; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; }
  .kpi { background:var(--alt); border-radius:10px; padding:12px; text-align:center; }
  .kpi b { display:block; color:var(--green); font-size:1.1rem; margin-top:4px; }
  .kpi span { font-size:.7rem; color:#5b6b64; text-transform:uppercase; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div class="brand">
      <div class="logo">Teranga</div>
      <div>
        <strong>Teranga BI</strong>
        <small>ISM · Master 2 Big Data</small>
      </div>
    </div>
    <div class="badge">DONNÉES ${hasFilters ? "FILTRÉES" : "COMPLÈTES"}</div>
  </div>

  <section>
    <h2>Indicateurs clés</h2>
    <div class="kpi-grid">${summaryHtml}</div>
  </section>

  <h1>Rapport analytique</h1>
  <p class="sub">Tableau détail + ${charts.length} visualisation(s) (survolez pour lire) · ${esc(viewTitle(view))}</p>

  <div class="info">
    <ul>
      <li>Généré le : ${esc(new Date().toLocaleString("fr-FR"))}</li>
      <li>Source : ${esc(DATA?.source || "—")} · Vue : ${esc(view)}</li>
      <li>${totalLines} ligne(s) dans ce rapport${totalLines > shownCap ? ` (${shownCap} premières affichées)` : ""}</li>
    </ul>
    <div class="chips">${filterChips}</div>
  </div>

  ${chartsHtml}
  ${tablesHtml}
</div>
<script>
const greens = ["#053f24","#14a44d","#0d7a3e","#1ab85a","#086b32","#22c55e","#94a3b8","#64748b"];
const CHARTS = ${chartPayload};
function tipUnit(unit) {
  return {
    backgroundColor: "rgba(5,63,36,0.95)",
    callbacks: {
      label: (c) => " " + (c.dataset.label ? c.dataset.label + " : " : "") + Number(c.raw).toLocaleString("fr-FR") + (unit || ""),
    },
  };
}
CHARTS.forEach((cfg) => {
  const canvas = document.getElementById(cfg.id);
  if (!canvas || typeof Chart === "undefined") return;
  const unit = cfg.unit || "";
  let datasets;
  if (cfg.datasets && cfg.datasets.length) {
    datasets = cfg.datasets.map((ds, i) => ({
      label: ds.label,
      data: ds.data,
      backgroundColor: cfg.type === "line" ? "rgba(20,164,77,0.22)" : greens[i % greens.length],
      borderColor: greens[i % greens.length],
      borderWidth: cfg.type === "line" ? 2.5 : (cfg.type === "doughnut" ? 3 : 0),
      borderRadius: cfg.type === "bar" ? 6 : 0,
      fill: cfg.type === "line",
      tension: 0.35,
      pointRadius: cfg.type === "line" ? 4 : 0,
      pointBackgroundColor: "#053f24",
    }));
  } else {
    datasets = [{
      label: cfg.title || "Valeur",
      data: cfg.values || [],
      backgroundColor: cfg.type === "doughnut" ? greens : (cfg.type === "line" ? "rgba(20,164,77,0.22)" : "#053f24"),
      borderColor: cfg.type === "doughnut" ? "#fff" : "#053f24",
      borderWidth: cfg.type === "doughnut" ? 3 : (cfg.type === "line" ? 2.5 : 0),
      borderRadius: cfg.type === "bar" ? 6 : 0,
      fill: cfg.type === "line",
      tension: 0.35,
      pointRadius: cfg.type === "line" ? 4 : 0,
      pointBackgroundColor: "#053f24",
      hoverOffset: cfg.type === "doughnut" ? 8 : 0,
    }];
  }
  new Chart(canvas, {
    type: cfg.type || "bar",
    data: { labels: cfg.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: cfg.type === "doughnut" ? "62%" : undefined,
      plugins: {
        legend: {
          display: cfg.type === "doughnut" || (cfg.datasets && cfg.datasets.length > 1),
          position: "bottom",
          labels: { boxWidth: 10, font: { size: 10 }, color: "#5b6b64" },
        },
        tooltip: tipUnit(unit),
      },
      scales: cfg.type === "doughnut" ? {} : {
        x: { grid: { display: false }, ticks: { color: "#5b6b64", maxRotation: cfg.type === "line" ? 0 : 45, font: { size: 10 } } },
        y: {
          grid: { color: "rgba(20,32,27,0.08)" },
          ticks: {
            color: "#5b6b64",
            callback: (v) => v >= 1e6 ? (v/1e6).toFixed(1)+"M" : v >= 1e3 ? (v/1e3).toFixed(0)+"K" : v,
          },
        },
      },
    },
  });
});
<\/script>
</body>
</html>`;

      downloadText(html, `teranga-rapport-${view}-${stamp()}.html`);
    } catch (e) {
      console.error(e);
      alert("Export HTML impossible : " + e.message);
    }
  }

  function bindExport() {
    el("export-excel")?.addEventListener("click", () => exportExcel());
    el("export-html")?.addEventListener("click", () => exportHtml());
    el("detail-export-xlsx")?.addEventListener("click", () => exportExcel());
    el("detail-export-html")?.addEventListener("click", () => exportHtml());
    el("export-vip-xlsx")?.addEventListener("click", () => exportClientSegment("vip"));
    el("export-loyal-xlsx")?.addEventListener("click", () => exportClientSegment("loyal"));
    el("export-inactif-xlsx")?.addEventListener("click", () => exportClientSegment("inactif"));
    el("export-churn-xlsx")?.addEventListener("click", () => exportClientSegment("churn"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindExport);
  } else {
    bindExport();
  }
})();
