(function () {
  window.LAST_DETAIL = null;

  function sharePct(value, total) {
    const t = Number(total) || 0;
    if (!t) return "—";
    return ((Number(value) / t) * 100).toFixed(1) + " %";
  }

  function caTotal() {
    return DATA?.kpis?.ca || 0;
  }

  function buildTargetAnalysis(value, target, targetLabel) {
    const v = Number(value) || 0;
    const t = Number(target) || 0;
    const diff = v - t;
    const reached = v >= t;
    const gap = Math.max(0, t - v);
    const pct = t ? ((diff / t) * 100).toFixed(1) : "0.0";
    let comment;
    if (!t) {
      comment = "Pas de référence disponible pour cette période (premier point de la série).";
      return { reached: true, rows: [], comment, status: null };
    }
    if (reached) {
      comment = `Objectif ${targetLabel} atteint : vous réalisez ${money(v)} contre ${money(t)} de référence, soit ${money(Math.abs(diff))} de plus (+${pct} %).`;
    } else {
      comment = `Objectif ${targetLabel} non atteint : il manque ${money(gap)} pour égaler la référence (${money(v)} vs ${money(t)}, ${pct} %).`;
    }
    return {
      reached,
      rows: [
        ["Référence (" + targetLabel + ")", money(t)],
        ["Écart", (diff >= 0 ? "+" : "−") + money(Math.abs(diff))],
        ["Variation", (diff >= 0 ? "+" : "") + pct + " %"],
        [reached ? "Résultat" : "Reste à combler", reached ? "✓ Objectif atteint" : money(gap)],
      ],
      comment,
      status: { ok: reached, text: reached ? "Objectif atteint" : `Manque ${money(gap)}` },
    };
  }

  function periodLabel() {
    if (PERIOD === "day") return "30 jours";
    if (PERIOD === "year") return "annuel";
    return "mensuel";
  }

  function drillFromCaPoint(dataIndex, s, chartId = "chart-ca") {
    const label = s.labels[dataIndex];
    const value = s.values[dataIndex];
    let targetLabel, target;
    if (COMPARE) {
      targetLabel = "N-1 (barre sombre)";
      target = prevSeries(s.values)[dataIndex];
    } else if (dataIndex > 0) {
      targetLabel = PERIOD === "day" ? "jour précédent" : PERIOD === "year" ? "année précédente" : "mois précédent";
      target = s.values[dataIndex - 1];
    } else {
      const avg = s.values.reduce((a, b) => a + b, 0) / (s.values.length || 1);
      targetLabel = `moyenne ${periodLabel()}`;
      target = Math.round(avg);
    }
    const analysis = buildTargetAnalysis(value, target, targetLabel);
    const rows = [["Période", label], ["CA réalisé", money(value)], ...analysis.rows];
    let filter = null;
    if (/^\d{4}-\d{2}$/.test(label)) {
      const [, m] = label.split("-");
      filter = { key: "mois", value: String(Number(m)), label: `Explorer · ${label}` };
    } else if (/^\d{4}-\d{2}-\d{2}$/.test(label)) {
      filter = null;
    } else if (/^\d{4}$/.test(label)) {
      filter = { key: "annee", value: label, label: `Explorer · ${label}` };
    }
    const fullComment = `${analysis.comment} Vue ${periodLabel()}${COMPARE ? " · comparaison N-1 activée" : ""}.`;
    openDetail({
      title: `CA · ${label}`,
      rows,
      comment: fullComment,
      analysis: analysis.status,
      filter,
      chartId,
    });
  }

  function funnelStepComment(index, vals) {
    const labels = ["Sessions", "Paniers", "Commandes"];
    const hints = [
      "Point d'entrée du parcours : toute la conversion se calcule à partir de ce volume.",
      "Intentions d'achat — comparez au objectif « sessions » pour mesurer l'ajout panier.",
      "Achats confirmés — comparez aux paniers pour voir l'abandon au checkout.",
    ];
    let text = hints[index] || "";
    if (index > 0 && vals[index - 1]) {
      const a = buildTargetAnalysis(vals[index], vals[index - 1], labels[index - 1]);
      text = a.comment + " " + text;
    }
    return text;
  }

  openDetail = function ({ title, rows, filter, comment, analysis, chartId }) {
    try {
      const safeRows = Array.isArray(rows) ? rows : [];
      const autoComment = comment
        || (analysis?.text
          ? `Lecture métier : ${analysis.text}.`
          : null)
        || (safeRows.length
          ? `Détail de « ${title || "l’élément"} » : ${safeRows.slice(0, 3).map(([k, v]) => `${k} = ${v}`).join(" · ")}. Utilisez Explorer pour filtrer le dashboard sur ce point.`
          : `Point sélectionné : « ${title || "détail"} ». Analysez les indicateurs ci-dessous pour décider d’une action métier.`);

      LAST_DETAIL = { title, rows: safeRows, comment: autoComment, filter, chartId };
      const titleEl = el("detail-title");
      if (titleEl) titleEl.textContent = title || "Détail";
      const commentEl = el("detail-comment");
      if (commentEl) {
        commentEl.textContent = autoComment;
        commentEl.hidden = false;
      }
      const statusEl = el("detail-status");
      if (statusEl) {
        if (analysis) {
          statusEl.className = "detail-status " + (analysis.ok ? "ok" : "bad");
          statusEl.textContent = analysis.text;
          statusEl.hidden = false;
        } else {
          statusEl.hidden = true;
          statusEl.textContent = "";
        }
      }
      const bodyEl = el("detail-body");
      if (bodyEl) {
        bodyEl.innerHTML = safeRows.map(([k, v]) =>
          `<div class="detail-row"><span>${k}</span><b>${v}</b></div>`
        ).join("") || `<div class="detail-row"><span>Info</span><b>Aucune ligne de détail</b></div>`;
      }
      const applyBtn = el("detail-apply");
      if (applyBtn) {
        if (filter?.key && filter?.value) {
          pendingFilter = filter;
          applyBtn.hidden = false;
          applyBtn.textContent = filter.label || "Explorer avec ce filtre";
        } else {
          pendingFilter = null;
          applyBtn.hidden = true;
        }
      }
      const modal = el("detail-modal");
      if (!modal) {
        console.error("detail-modal introuvable");
        return;
      }
      const card = modal.querySelector(".modal-card");
      modal.classList.remove("hidden");
      modal.removeAttribute("hidden");
      modal.setAttribute("aria-hidden", "false");
      modal.style.display = "grid";
      if (card) {
        card.classList.remove("modal-in");
        void card.offsetWidth;
        card.classList.add("modal-in");
      }
      /* 2e passe : certains re-renders retirent le modal juste après le clic */
      requestAnimationFrame(() => {
        modal.classList.remove("hidden");
        modal.setAttribute("aria-hidden", "false");
        modal.style.display = "grid";
      });
    } catch (err) {
      console.error("openDetail", err);
    }
  };

  closeDetail = function () {
    const modal = el("detail-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    modal.style.display = "";
    pendingFilter = null;
  };

  drillFromCategory = function (name, value, extra = []) {
    const cats = DATA?.categories || [];
    const avg = cats.length ? cats.reduce((a, c) => a + c.value, 0) / cats.length : 0;
    const analysis = buildTargetAnalysis(value, avg, "moyenne catégories");
    openDetail({
      title: name,
      comment: `${analysis.comment} Part du CA total : ${sharePct(value, caTotal())}.`,
      analysis: analysis.status,
      rows: [["Catégorie", name], ["CA", money(value)], ...analysis.rows, ...extra],
      filter: { key: "categorie", value: name, label: `Explorer · ${name}` },
      chartId: "chart-cat-donut",
    });
  };

  drillFromRegion = function (name, value) {
    const regs = DATA?.regions || [];
    const avg = regs.length ? regs.reduce((a, r) => a + r.value, 0) / regs.length : 0;
    const analysis = buildTargetAnalysis(value, avg, "moyenne régions");
    openDetail({
      title: name,
      comment: `${analysis.comment} Poids : ${sharePct(value, caTotal())} du CA filtré.`,
      analysis: analysis.status,
      rows: [["Région", name], ["CA", money(value)], ...analysis.rows],
      filter: { key: "region", value: name, label: `Explorer · ${name}` },
      chartId: "chart-region",
    });
  };

  drillFromSegment = function (item) {
    const segs = DATA?.segments || [];
    const avg = segs.length ? segs.reduce((a, s) => a + s.value, 0) / segs.length : 0;
    const analysis = buildTargetAnalysis(item.value, avg, "moyenne segments");
    openDetail({
      title: item.name,
      comment: `${analysis.comment} Part CA : ${sharePct(item.value, caTotal())}.`,
      analysis: analysis.status,
      rows: [
        ["Segment", item.name],
        ["CA", money(item.value)],
        ...(item.clients ? [["Clients", compact(item.clients)]] : []),
        ...analysis.rows,
      ],
      filter: { key: "segment", value: item.name, label: `Explorer · ${item.name}` },
      chartId: "chart-seg",
    });
  };

  drillFromPeriod = function (label, value, dataIndex, s) {
    if (s && dataIndex != null) {
      drillFromCaPoint(dataIndex, s, "chart-ca-qty");
      return;
    }
    drillFromCaPoint(0, { labels: [label], values: [value] }, "chart-ca");
  };

  let drillDelegated = false;

  function handleDrillClick(node) {
    if (!node) return;
    if (node.dataset.kind === "stock") {
      const label = node.dataset.drillLabel || node.dataset.drillValue;
      const stock = Number(node.dataset.stock || 0);
      const cat = node.dataset.stockCat || "—";
      const niveau = node.dataset.stockNiveau || "faible";
      let comment;
      let analysis;
      if (stock <= 0) {
        comment = `Rupture sur « ${label} ». Priorité haute : déclencher une commande fournisseur ou retirer le produit des mises en avant jusqu’à réassort.`;
        analysis = { ok: false, text: "Rupture — action immédiate" };
      } else if (stock < 20) {
        comment = `Stock très bas (${stock} unités) sur « ${label} ». Risque de rupture sous peu si la demande continue. Anticipez un réassort cette semaine.`;
        analysis = { ok: false, text: `Critique — ${stock} unités` };
      } else {
        comment = `Stock faible (${stock} unités) sur « ${label} » (${cat}). Surveillez les ventes des prochains jours et préparez une commande avant bascule en rupture.`;
        analysis = { ok: false, text: `Alerte — ${stock} unités restantes` };
      }
      openDetail({
        title: `Alerte stock · ${label}`,
        comment,
        analysis,
        rows: [
          ["Produit", label],
          ["Catégorie", cat],
          ["Stock actuel", String(stock)],
          ["Niveau", niveau === "rupture" ? "Rupture" : "Faible"],
          ["Action suggérée", stock <= 0 ? "Réapprovisionner / masquer" : "Planifier réassort"],
        ],
        filter: { key: "produit", value: label, label: `Voir · ${label}` },
      });
      return;
    }
    const key = node.dataset.drillKey;
    const value = node.dataset.drillValue;
    const label = node.dataset.drillLabel || value;
    const ca = Number(node.dataset.drillCa || 0);
    const labelMap = { categorie: "Catégorie", region: "Région", segment: "Segment", produit: "Produit", client: "Client" };
    const avgMap = {
      categorie: (DATA?.categories || []).reduce((a, c) => a + c.value, 0) / ((DATA?.categories || []).length || 1),
      region: (DATA?.regions || []).reduce((a, r) => a + r.value, 0) / ((DATA?.regions || []).length || 1),
    };
    const analysis = ca && avgMap[key] ? buildTargetAnalysis(ca, avgMap[key], "moyenne") : null;
    let comment = analysis ? analysis.comment : null;
    if (!comment && key === "produit") {
      comment = ca
        ? `« ${label} » représente ${money(ca)} de CA sur le périmètre filtré. Utilisez « Explorer » pour isoler ce produit dans les ventes.`
        : `Fiche produit « ${label} ». Explorez avec le filtre pour voir ses ventes et son stock.`;
    } else if (!comment && key === "client") {
      const isVip = node.dataset.vip === "1" || node.dataset.statut === "vip";
      const isLoyal = node.dataset.loyal === "1" || node.dataset.statut === "loyal";
      const isInactif = node.dataset.inactif === "1" || node.dataset.statut === "inactif";
      const isChurn = node.dataset.churn === "1" || node.dataset.statut === "churn" || Number(node.dataset.joursInactif || 0) >= 730;
      const freq = Number(node.dataset.freq || 0);
      const freqLib = node.dataset.freqLib || (freq ? `${freq} cmd/mois` : "—");
      const cmd = Number(node.dataset.cmd || 0);
      const jours = Number(node.dataset.jours || 0);
      const joursInactif = Number(node.dataset.joursInactif || 0);
      const entre = node.dataset.joursEntre !== "" ? Number(node.dataset.joursEntre) : null;
      const panier = Number(node.dataset.panier || 0);
      const freqMoyVip = Number(DATA?.kpis?.freq_vip_moy || 0);
      let freqComment;
      if (freq >= 2) freqComment = `Fréquence élevée (${freqLib}).`;
      else if (freq >= 0.8) freqComment = `Fréquence correcte (${freqLib}).`;
      else if (freq > 0) freqComment = `Fréquence faible (${freqLib}).`;
      else freqComment = "Fréquence non calculable.";

      let clientTitle;
      let clientComment;
      let clientAnalysis;
      let statutLib;
      if (isVip) {
        clientTitle = `VIP · ${label}`;
        clientComment = `Client VIP « ${label} » — achats très fréquents. À choyer, distinct des simples loyaux. CA ${ca ? money(ca) : "—"}, ${cmd} commande(s). ${freqComment}${freqMoyVip ? ` Moyenne VIP : ${freqMoyVip} cmd/mois.` : ""}`;
        clientAnalysis = { ok: true, text: "VIP — très fréquent" };
        statutLib = "VIP";
      } else if (isChurn) {
        const jTxt = joursInactif ? `${joursInactif} jours` : "au moins 2 ans";
        clientTitle = `Churn · ${label}`;
        clientComment = `Client parti « ${label} » — aucune commande depuis ${jTxt} (≥ 2 ans). ${cmd} commande(s) au total. ${freqComment}`;
        clientAnalysis = { ok: false, text: "Churn — ≥ 2 ans sans achat" };
        statutLib = "Churn";
      } else if (isInactif) {
        clientTitle = `Inactif · ${label}`;
        clientComment = `Client inactif « ${label} » — ${joursInactif || "180+"} jours sans achat (moins de 2 ans). Encore récupérable par relance. ${freqComment}`;
        clientAnalysis = { ok: false, text: "Inactif — à relancer" };
        statutLib = "Inactif";
      } else {
        clientTitle = `Loyal · ${label}`;
        clientComment = `Client loyal « ${label} » — achète régulièrement, sans la fréquence d’un VIP. CA ${ca ? money(ca) : "—"}, ${cmd} commande(s). ${freqComment}`;
        clientAnalysis = { ok: true, text: "Loyal — à fidéliser" };
        statutLib = isLoyal ? "Loyal" : (node.dataset.segment || "Loyal");
      }
      openDetail({
        title: clientTitle,
        comment: clientComment,
        analysis: clientAnalysis,
        rows: [
          ["Client", label],
          ["Statut", statutLib],
          ["Segment Mozart", node.dataset.segment || "—"],
          ["Région", node.dataset.region || "—"],
          ["1re achat", node.dataset.premiere || "—"],
          ["Dernier achat", node.dataset.derniere || "—"],
          ...(joursInactif ? [["Jours sans achat", String(joursInactif)]] : []),
          ["Commandes", String(cmd)],
          ["Fréquence", freqLib],
          ...(jours ? [["Jours d’activité", String(jours)]] : []),
          ...(entre != null && !Number.isNaN(entre) ? [["Jours entre cmd (moy.)", String(entre)]] : []),
          ["Panier moyen", money(panier)],
          ...(ca ? [["CA", money(ca)]] : []),
        ],
        filter: { key, value, label: `Explorer · ${label}` },
      });
      return;
    } else if (!comment) {
      comment = "Lecture métier du point sélectionné. Exportez le détail ou explorez avec le filtre.";
    }
    openDetail({
      title: label,
      comment,
      analysis: analysis?.status,
      rows: [[labelMap[key] || "Élément", label], ...(ca ? [["CA", money(ca)]] : []), ...(analysis?.rows || [])],
      filter: { key, value, label: `Explorer · ${label}` },
    });
  }

  function handleVenteRowClick(tr) {
    const idx = Number(tr.dataset.idx);
    const venteId = tr.dataset.venteId || "";
    const cmdId = tr.dataset.cmdId || "";
    let r = Number.isFinite(idx) && idx >= 0 ? RECENT_ROWS[idx] : null;
    if (!r && venteId) {
      r = RECENT_ROWS.find((x) => String(x.vente_id) === String(venteId));
    }
    if (!r && cmdId) {
      r = RECENT_ROWS.find((x) => String(x.id) === String(cmdId));
    }
    if (!r) {
      const cells = [...tr.querySelectorAll("td")].map((td) => td.textContent.trim());
      openDetail({
        title: `Commande ${cells[1] || cmdId || "—"}`,
        comment: "Détail lu depuis la ligne du tableau. Rechargez les données si les chiffres semblent incomplets.",
        rows: [
          ["ID ligne", cells[0] || venteId || "—"],
          ["N° commande", cells[1] || cmdId || "—"],
          ["Date", cells[2] || "—"],
          ["Produit", cells[3] || "—"],
          ["Catégorie", cells[4] || "—"],
          ["Qté", cells[5] || "—"],
          ["Prix", cells[6] || "—"],
          ["Montant", cells[7] || "—"],
          ["Statut", cells[8] || "—"],
        ],
      });
      return;
    }
    const panier = DATA?.kpis?.panier_moyen || 0;
    const analysis = buildTargetAnalysis(r.montant, panier, "panier moyen");
    const statutHint = r.statut === "confirmee"
      ? "Commande validée — incluse dans le CA net."
      : r.statut === "annulee"
        ? "Commande annulée — à exclure de l’analyse de performance."
        : r.statut === "retournee"
          ? "Retour client — impact marge et stock à surveiller."
          : "Statut à confirmer côté opérations.";
    const statLabel = (window.STATUT_FR && STATUT_FR[r.statut]) || r.statut;
    openDetail({
      title: `Commande ${r.id}`,
      comment: `${statutHint} ${analysis.comment}`,
      analysis: analysis.status,
      rows: [
        ["ID ligne", r.vente_id ?? "—"],
        ["N° commande", r.id],
        ["Date", r.date || "—"],
        ["Produit", r.produit],
        ["Catégorie", r.categorie || "—"],
        ["Quantité", r.quantite ?? "—"],
        ["Prix unitaire", money(r.prix_unitaire ?? 0)],
        ["Montant", money(r.montant)],
        ["Promo", r.promo || "—"],
        ["Statut", statLabel],
        ...analysis.rows,
      ],
      filter: r.categorie && r.categorie !== "—"
        ? { key: "categorie", value: r.categorie, label: `Explorer · ${r.categorie}` }
        : r.produit
          ? { key: "produit", value: r.produit, label: `Explorer · ${r.produit}` }
          : null,
    });
  }

  /* Délégation en capture : survit au re-render et passe avant d’autres handlers */
  attachDrillLists = function () {
    if (drillDelegated) return;
    drillDelegated = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest("[data-close-modal], #detail-modal .modal-card button, #detail-modal a")) return;
      const row = e.target.closest("tr.drill-row");
      if (row && !row.closest("#detail-modal")) {
        e.preventDefault();
        try { handleVenteRowClick(row); } catch (err) { console.error(err); }
        return;
      }
      const item = e.target.closest(".drill-item");
      if (item && !item.closest("#detail-modal")) {
        e.preventDefault();
        try { handleDrillClick(item); } catch (err) { console.error(err); }
      }
    }, true);
  };

  function animateBlocks() {
    document.querySelectorAll(".kpi-row .kpi").forEach((node, i) => {
      node.classList.remove("kpi-in");
      node.style.animationDelay = `${i * 0.07}s`;
      void node.offsetWidth;
      node.classList.add("kpi-in");
    });
  }

  const _drawCA = drawCA;
  drawCA = function () {
    _drawCA();
    if (!DATA) return;
    const s = seriesForPeriod(DATA.timeseries, PERIOD);
    bindDrill("chart-ca", (p) => drillFromCaPoint(p.dataIndex, s, "chart-ca"));
  };

  const _render = render;
  render = function (d) {
    _render(d);

    const k = d.kpis;
    const topCats = d.categories.slice(0, 8);
    const sMonth = seriesForPeriod(d.timeseries, "month");

    /* Dashboard : catégorie + segments toujours cliquables avec commentaire */
    const catsDash = (d.categories || []).slice(0, 6);
    donut("chart-cat-donut", catsDash, (p) => drillFromCategory(p.name, p.value));
    const segs = d.segments || [];
    donut("chart-seg", segs, (p) => {
      const item = segs.find((s) => s.name === p.name) || { name: p.name, value: p.value };
      drillFromSegment(item);
    });

    bindDrill("chart-ca-qty", (p) => drillFromCaPoint(p.dataIndex, sMonth, "chart-ca-qty"));

    /* Rentabilité ventes */
    const cost = Math.max(0, (k.ca || 0) - (k.profit || 0));
    const promoAmt = Math.round((k.ca || 0) * (k.promo_share || 0) / 100);
    const breakItems = [
      ["Coût produits", cost],
      ["Marge brute", k.profit || 0],
      ["CA promo", promoAmt],
      ["CA net", k.ca || 0],
    ];
    bindDrill("chart-rentab", (p) => {
      const item = breakItems[p.dataIndex];
      if (!item) {
        openDetail({
          title: "Rentabilité",
          comment: "Cliquez directement sur une barre (Coût, Marge, Promo ou CA net) pour le détail.",
          rows: breakItems.map(([n, v]) => [n, money(v)]),
          chartId: "chart-rentab",
        });
        return;
      }
      openDetail({
        title: item[0],
        comment: `Lecture rentabilité : « ${item[0]} » représente ${money(item[1])} sur le périmètre filtré. Comparez coût, marge, promo et CA net pour juger la santé commerciale.`,
        rows: breakItems.map(([n, v]) => [n, money(v)]),
        chartId: "chart-rentab",
      });
    });

    bindDrill("chart-cat-bar", (p) => {
      const c = topCats.slice().reverse()[p.dataIndex];
      if (c) drillFromCategory(c.name, c.value);
      else if (p.name) drillFromCategory(p.name, p.value || 0);
    });
    el("cat-list").innerHTML = topCats.map((c) =>
      statLi(c.name, `<b>${money(c.value)}</b> ${pill(c.delta || 0)}`, { key: "categorie", value: c.name, ca: c.value })
    ).join("");
    donut("chart-cat-promo", d.categories.slice(0, 6), (p) => drillFromCategory(p.name, p.value));

    bindDrill("chart-funnel", (p) => {
      const names = ["Sessions", "Paniers", "Commandes"];
      const vals = [d.funnel.view, d.funnel.add_to_cart, d.funnel.purchase];
      const prev = p.dataIndex > 0 ? vals[p.dataIndex - 1] : 0;
      const analysis = p.dataIndex > 0 ? buildTargetAnalysis(vals[p.dataIndex], prev, names[p.dataIndex - 1]) : null;
      openDetail({
        title: names[p.dataIndex],
        comment: funnelStepComment(p.dataIndex, vals),
        analysis: analysis?.status,
        rows: [[names[p.dataIndex], compact(vals[p.dataIndex])], ...(analysis?.rows || [])],
        chartId: "chart-funnel",
      });
    });

    donut("chart-promo", [
      { name: "Plein tarif", value: Math.max(0, 100 - (k.promo_share || 0)) },
      { name: "Promo", value: k.promo_share || 0 },
    ], (p) => {
      const isPromo = p.name === "Promo";
      const target = 20;
      const val = isPromo ? k.promo_share : 100 - k.promo_share;
      const analysis = buildTargetAnalysis(val, isPromo ? 15 : 80, isPromo ? "cible promo 15 %" : "cible plein tarif 80 %");
      openDetail({
        title: p.name,
        comment: isPromo
          ? `${analysis.comment} Toute décision promo reste à valider par l’équipe métier.`
          : `${analysis.comment} Le cœur du CA reste hors promotion.`,
        analysis: analysis.status,
        rows: [
          ["Part", `${Number(p.value).toFixed(1)} %`],
          ["CA estimé", money(isPromo ? k.ca * (k.promo_share || 0) / 100 : k.ca - k.ca * (k.promo_share || 0) / 100)],
          ...analysis.rows,
        ],
        filter: { key: "promo", value: isPromo ? "oui" : "non", label: isPromo ? "Explorer · avec promo" : "Explorer · sans promo" },
        chartId: "chart-promo",
      });
    });

    donut("chart-device", d.devices.length ? d.devices : [{ name: "n/a", value: 1 }], (p) => {
      const total = d.devices.reduce((a, x) => a + x.value, 0) || 1;
      const analysis = buildTargetAnalysis(p.value, total / d.devices.length, "moyenne appareils");
      openDetail({
        title: p.name,
        comment: `${analysis.comment} Part : ${sharePct(p.value, total)}.`,
        analysis: analysis.status,
        rows: [["Appareil", p.name], ["Sessions / CA", money(p.value)], ...analysis.rows],
        filter: { key: "appareil", value: p.name, label: `Explorer · ${p.name}` },
        chartId: "chart-device",
      });
    });

    const traf = d.traffic.length ? d.traffic : d.categories;
    bindDrill("chart-traffic", (p) => {
      const item = traf[p.dataIndex] || (p.name ? { name: p.name, value: p.value } : null);
      if (!item) {
        openDetail({
          title: "Sources de trafic",
          comment: "Cliquez sur une barre / un canal pour voir sa contribution.",
          rows: traf.slice(0, 8).map((t) => [t.name, money(t.value)]),
          chartId: "chart-traffic",
        });
        return;
      }
      const total = traf.reduce((a, x) => a + x.value, 0) || 1;
      const analysis = buildTargetAnalysis(item.value, total / traf.length, "moyenne canaux");
      openDetail({
        title: item.name,
        comment: `${analysis.comment} Conversion globale ~${Number(k.conversion || 0).toFixed(1)} %.`,
        analysis: analysis.status,
        rows: [["Source", item.name], ["Valeur", money(item.value)], ...analysis.rows],
        filter: { key: "source_trafic", value: item.name, label: `Explorer · ${item.name}` },
        chartId: "chart-traffic",
      });
    });

    const maxR = Math.max(...d.regions.map((r) => r.value), 1);
    el("region-bars").innerHTML = d.regions.slice(0, 6).map((r) =>
      `<li class="drill-item" data-drill-key="region" data-drill-value="${r.name}" data-drill-label="${r.name}" data-drill-ca="${r.value}">
        <span>${r.name}</span><span class="track"><span class="fill" style="width:${Math.round((r.value / maxR) * 100)}%"></span></span><b>${money(r.value)}</b></li>`
    ).join("");

    el("stock-alerts").innerHTML = (d.stock_alert || []).length
      ? d.stock_alert.map((s) => {
          const niveau = s.stock <= 0 ? "rupture" : s.stock < 40 ? "faible" : "ok";
          return `<li class="drill-item" data-kind="stock"
            data-drill-key="produit" data-drill-value="${s.produit}" data-drill-label="${s.produit}"
            data-stock="${s.stock}" data-stock-cat="${s.categorie || ""}" data-stock-niveau="${niveau}">
            <span class="dot r"></span><div><b>${s.produit}</b><br/>stock ${s.stock}${s.categorie ? ` · ${s.categorie}` : ""}</div></li>`;
        }).join("")
      : "<li>Aucune alerte stock — bon niveau sur le périmètre filtré</li>";

    if (charts["chart-region"] && d.regions?.length) {
      const rNames = d.regions.map((x) => x.name).reverse();
      const rVals = d.regions.map((x) => x.value).reverse();
      charts["chart-region"].setOption({
        grid: { left: 102, right: 24, top: 12, bottom: 12 },
        yAxis: {
          type: "category",
          data: rNames,
          axisLabel: { color: "#5b6b64", width: 96, overflow: "truncate", interval: 0, fontSize: 11 },
        },
        series: [{
          type: "bar",
          data: rVals,
          barWidth: 14,
          itemStyle: barItem("#053f24", [0, 8, 8, 0]),
        }],
      });
      bindDrill("chart-region", (p) => {
        const name = rNames[p.dataIndex] || p.name;
        const value = rVals[p.dataIndex] != null ? rVals[p.dataIndex] : p.value;
        if (name) drillFromRegion(name, value || 0);
        else openDetail({
          title: "CA par région",
          comment: "Cliquez sur une barre de région pour le détail.",
          rows: rNames.map((n, i) => [n, money(rVals[i])]),
          chartId: "chart-region",
        });
      });
    }

    /* Jauges abandon — clic → modal */
    const abandonCart = k.abandon_pct || 0;
    const views = d.funnel?.view || 0;
    const purch = d.funnel?.purchase || 0;
    const carts = d.funnel?.add_to_cart || 0;
    const abandonRev = views ? (1 - purch / views) * 100 : 0;
    bindDrill("chart-abandon-cart", () => {
      openDetail({
        title: "Paniers abandonnés",
        comment: `Taux d’abandon panier : ${abandonCart.toFixed(1)} %. Environ ${compact(Math.max(0, carts - purch))} paniers non convertis.`,
        rows: [
          ["Taux abandon", `${abandonCart.toFixed(1)} %`],
          ["Paniers", compact(carts)],
          ["Commandes", compact(purch)],
          ["Abandons estimés", compact(Math.max(0, carts - purch))],
        ],
        chartId: "chart-abandon-cart",
      });
    });
    bindDrill("chart-abandon-rev", () => {
      openDetail({
        title: "Vues sans achat",
        comment: `Part des sessions sans achat : ${abandonRev.toFixed(1)} %. CA potentiel associé (proxy) : ${money(Math.round((k.ca || 0) * abandonRev / 100))}.`,
        rows: [
          ["Sessions", compact(views)],
          ["Achats", compact(purch)],
          ["Sans achat", `${abandonRev.toFixed(1)} %`],
        ],
        chartId: "chart-abandon-rev",
      });
    });

    drawCA();
    animateBlocks();
    attachDrillLists();
    setTimeout(() => {
      if (typeof resizeAll === "function") resizeAll();
      if (typeof rebindAllDrills === "function") rebindAllDrills();
    }, 60);
    setTimeout(() => {
      if (typeof resizeAll === "function") resizeAll();
      if (typeof rebindAllDrills === "function") rebindAllDrills();
    }, 220);
  };

  /* Active la délégation dès le chargement (avant le 1er render) */
  attachDrillLists();

  document.querySelectorAll("[data-refresh-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.classList.add("spin");
      Promise.resolve(load(true)).finally(() => {
        setTimeout(() => btn.classList.remove("spin"), 400);
      });
    });
  });
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", closeDetail);
  });
  el("detail-apply")?.addEventListener("click", applyPendingFilter);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDetail();
  });

  if (DATA) render(DATA);
})();
