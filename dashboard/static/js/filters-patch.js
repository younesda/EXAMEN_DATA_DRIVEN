/* Filtres instantanés + tableaux métier + anti-bug vues */
(function () {
  const MOIS_FR = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin",
    7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
  };
  const STATUT_FR = {
    confirmee: "Confirmée",
    annulee: "Annulée",
    en_attente: "En attente",
    livree: "Livrée",
    retournee: "Retournée",
  };
  const NIVEAU_FR = { rupture: "Rupture", faible: "Faible", ok: "OK" };
  const SHARED_FILTERS = new Set(["annee", "mois", "region"]);

  window.STATUT_FR = STATUT_FR;
  window.MOIS_FR = MOIS_FR;

  VIEW_FILTER_KEYS.dashboard = ["annee", "mois", "region"];
  VIEW_FILTER_KEYS.ventes = ["annee", "mois", "weekend", "promo", "statut", "categorie", "produit", "region", "q"];
  VIEW_FILTER_KEYS.produits = ["annee", "mois", "categorie", "marque", "produit", "promo", "q"];
  VIEW_FILTER_KEYS.clients = ["annee", "mois", "region", "segment", "age", "client", "appareil", "source_trafic", "q"];
  VIEW_FILTER_KEYS.stock = ["categorie", "marque", "produit", "stock_level", "q"];

  FILTER_OPTIONS_KEY.client = "clients";

  Object.assign(FILTER_LABELS, {
    weekend: { weekend: "Week-end uniquement", semaine: "Semaine (lun–ven)", all: "Semaine + week-end" },
    promo: { oui: "Avec promotion", non: "Plein tarif", all: "Promo + plein tarif" },
    client: { all: "Tous clients" },
  });

  const _labelForFilter = labelForFilter;
  labelForFilter = function (key, value) {
    if (key === "mois" && value !== "all") return MOIS_FR[Number(value)] || `Mois ${value}`;
    if (key === "statut" && value !== "all") return STATUT_FR[value] || value;
    return _labelForFilter(key, value);
  };

  function activeViewRoot() {
    return document.querySelector(".view.on")
      || el("view-" + (typeof CURRENT_VIEW !== "undefined" ? CURRENT_VIEW : "dashboard"))
      || document;
  }

  fillSelectByKey = function (key, values, active, root) {
    const o = DATA?.filter_options || {};
    const current = active?.[key] || "all";
    const defaultLabel = labelForFilter(key, "all");
    const clientLabels = o.client_labels || {};
    const scope = root || activeViewRoot();
    scope.querySelectorAll(`select[data-filter="${key}"]`).forEach((node) => {
      const prev = node.value;
      node.innerHTML = `<option value="all">${defaultLabel}</option>` + (values || []).map((v) => {
        const label = key === "client" ? (clientLabels[v] || `Client ${v}`) : labelForFilter(key, v);
        return `<option value="${String(v).replace(/"/g, "&quot;")}">${label}</option>`;
      }).join("");
      const want = current !== "all" && current != null ? String(current) : "all";
      node.value = [...node.options].some((opt) => opt.value === want) ? want : "all";
      if (node.value === "all" && prev && prev !== "all" && [...node.options].some((opt) => opt.value === prev)) {
        node.value = prev;
      }
    });
  };

  syncFilter = function (key, value) {
    if (!SHARED_FILTERS.has(key)) return;
    document.querySelectorAll(`select[data-filter="${key}"]`).forEach((node) => {
      if ([...node.options].some((o) => o.value === value)) node.value = value;
    });
  };

  function productsForFilters(o, active) {
    const cat = active?.categorie;
    const marque = active?.marque;
    let list = o.produits || [];
    if (cat && o.produits_by_categorie?.[cat]) list = o.produits_by_categorie[cat];
    if (marque && o.produits_by_marque?.[marque]) {
      const set = new Set(o.produits_by_marque[marque]);
      list = list.filter((p) => set.has(p));
    }
    return list;
  }

  function clientsForFilters(o, active) {
    let list = o.clients || [];
    const apply = (map, key) => {
      if (!active?.[key] || !map?.[active[key]]) return;
      const set = new Set(map[active[key]]);
      list = list.filter((c) => set.has(c));
    };
    apply(o.clients_by_age, "age");
    apply(o.clients_by_segment, "segment");
    apply(o.clients_by_region, "region");
    return list;
  }

  function refreshCascades(active) {
    const o = DATA?.filter_options || {};
    const act = active || currentFilters();
    const root = activeViewRoot();
    fillSelectByKey("produit", productsForFilters(o, act), act, root);
    fillSelectByKey("client", clientsForFilters(o, act), act, root);
  }

  populateFilters = function (options, active) {
    const o = options || {};
    const root = activeViewRoot();
    const viewKey = root.id?.replace("view-", "") || CURRENT_VIEW;
    const keys = VIEW_FILTER_KEYS[viewKey] || [];
    keys.forEach((key) => {
      if (key === "q" || key === "produit" || key === "client") return;
      const optKey = FILTER_OPTIONS_KEY[key];
      if (!optKey) return;
      fillSelectByKey(key, o[optKey] || [], active, root);
    });
    if (keys.includes("produit")) fillSelectByKey("produit", productsForFilters(o, active), active, root);
    if (keys.includes("client")) fillSelectByKey("client", clientsForFilters(o, active), active, root);

    const qMap = { ventes: "q-ventes", produits: "q-produits", clients: "q-clients", stock: "q-stock" };
    const qId = qMap[viewKey];
    if (qId && el(qId) && keys.includes("q")) el(qId).value = active?.q || "";
  };

  document.addEventListener("change", (e) => {
    const sel = e.target?.closest?.("select[data-filter]");
    if (!sel || !DATA) return;
    if (!activeViewRoot().contains(sel)) return;
    const key = sel.dataset.filter;
    if (["categorie", "marque", "age", "segment", "region"].includes(key)) {
      const act = { ...currentFilters() };
      act[key] = sel.value !== "all" ? sel.value : undefined;
      if (sel.value === "all") delete act[key];
      if (key === "categorie" || key === "marque") {
        if (act.produit && !productsForFilters(DATA.filter_options || {}, act).includes(act.produit)) {
          delete act.produit;
        }
      }
      if (["age", "segment", "region"].includes(key) && act.client) {
        if (!clientsForFilters(DATA.filter_options || {}, act).includes(String(act.client))) {
          delete act.client;
        }
      }
      refreshCascades(act);
    }
  }, true);

  currentFilters = function () {
    const out = {};
    const view = activeViewRoot();
    if (!view || !view.id) return out;
    const viewKey = view.id.replace("view-", "");
    const keys = VIEW_FILTER_KEYS[viewKey] || [];
    const allowed = new Set(keys);

    view.querySelectorAll("select[data-filter]").forEach((node) => {
      const key = node.dataset.filter;
      if (!allowed.has(key)) return;
      const v = node.value;
      if (v && v !== "all") out[key] = v;
    });

    const qMap = { ventes: "q-ventes", produits: "q-produits", clients: "q-clients", stock: "q-stock" };
    const q = (el(qMap[viewKey])?.value || "").trim();
    if (q && allowed.has("q")) out.q = q;
    return out;
  };

  function setMeta(id, total, shown, excelHint) {
    const meta = el(id);
    if (!meta) return;
    if (!total) {
      meta.textContent = "0 ligne — aucun résultat pour cette combinaison de filtres (réessaie en élargissant)";
      return;
    }
    if (excelHint && total > shown) {
      meta.textContent = `${compact(total)} ligne(s) · ${shown} affichées — Excel / HTML pour le détail`;
    } else {
      meta.textContent = `${compact(shown)} ligne(s) selon filtres actifs`;
    }
  }

  paintTable = function (rows, targetId = "recent", metaId = "recent-meta") {
    const host = el(targetId);
    if (!host) return;
    RECENT_ROWS = rows;
    const total = DATA?.filtered_rows ?? rows.length;
    const q = (el("q-ventes")?.value || "").trim().toLowerCase();
    const list = rows.filter((r) =>
      `${r.vente_id} ${r.id} ${r.produit} ${r.categorie} ${r.statut}`.toLowerCase().includes(q)
    );
    const statLabel = (s) => STATUT_FR[s] || s;
    setMeta(metaId, total, list.length, true);
    if (!list.length) {
      host.innerHTML = `<p class="chart-hint" style="padding:16px">Aucune ligne pour ces filtres. Ex. : Statut « Retournée » + Promo + Semaine + produit précis peut donner 0 — retire un filtre.</p>`;
      return;
    }
    host.innerHTML = `<table><thead><tr>
      <th>ID</th><th>Commande</th><th>Date</th><th>Produit</th><th>Catégorie</th>
      <th>Qté</th><th>Prix</th><th>Montant</th><th>Statut</th>
    </tr></thead><tbody>${
      list.map((r) => `<tr class="drill-row" data-idx="${rows.indexOf(r)}" data-kind="vente" data-vente-id="${r.vente_id ?? ""}" data-cmd-id="${r.id ?? ""}">
        <td>${r.vente_id ?? "—"}</td><td>${r.id}</td><td>${r.date || "—"}</td>
        <td>${r.produit}</td><td>${r.categorie || "—"}</td>
        <td>${r.quantite ?? "—"}</td><td>${money(r.prix_unitaire ?? 0)}</td><td>${money(r.montant)}</td>
        <td><span class="badge ${r.statut === "confirmee" ? "ok" : r.statut === "annulee" ? "bad" : "wait"}">${statLabel(r.statut)}</span></td>
      </tr>`).join("")
    }</tbody></table>`;
  };

  function paintProduitsTable(d) {
    const host = el("table-produits");
    if (!host) return;
    try {
      const rows = d.produits_detail || [];
      const q = (el("q-produits")?.value || "").trim().toLowerCase();
      const list = rows.filter((r) =>
        `${r.produit} ${r.categorie} ${r.marque}`.toLowerCase().includes(q)
      ).slice(0, 250);
      setMeta("table-produits-meta", rows.length, list.length, true);
      host.innerHTML = !list.length
        ? `<p class="chart-hint" style="padding:16px">Aucun produit pour ces filtres.</p>`
        : `<table><thead><tr>
        <th>Produit</th><th>Catégorie</th><th>Marque</th><th>1re vente</th><th>Dernière</th>
        <th>Commandes</th><th>Qté vendue</th><th>CA (F CFA)</th><th>Lignes</th>
      </tr></thead><tbody>${
        list.map((r) => `<tr class="drill-item" data-drill-key="produit" data-drill-value="${escAttr(r.produit)}" data-drill-label="${escAttr(r.produit)}" data-drill-ca="${r.ca}">
          <td>${r.produit}</td><td>${r.categorie}</td><td>${r.marque}</td>
          <td>${r.premiere || "—"}</td><td>${r.derniere || "—"}</td>
          <td>${compact(r.commandes)}</td><td>${compact(r.quantite)}</td><td>${money(r.ca)}</td><td>${compact(r.lignes)}</td>
        </tr>`).join("")
      }</tbody></table>`;
    } catch (err) {
      console.error("paintProduitsTable", err);
      host.innerHTML = `<p class="chart-hint" style="padding:16px">Erreur affichage produits.</p>`;
    }
  }

  function statutClient(r) {
    if (r.statut_client) return r.statut_client;
    if (r.churn || Number(r.jours_inactif) >= 730) return "churn";
    if (r.inactif || Number(r.jours_inactif) >= 180) return "inactif";
    if (r.vip) return "vip";
    if (r.loyal) return "loyal";
    return "loyal";
  }

  function badgeStatut(st) {
    if (st === "vip") return `<span class="badge ok">VIP</span>`;
    if (st === "loyal") return `<span class="badge wait">Loyal</span>`;
    if (st === "inactif") return `<span class="badge wait">Inactif</span>`;
    if (st === "churn") return `<span class="badge bad">Churn</span>`;
    return st || "—";
  }

  function clientRowAttrs(r, st) {
    return `class="drill-item ${st === "vip" ? "row-vip" : st === "churn" ? "row-churn" : st === "inactif" ? "row-inactif" : "row-loyal"}" data-drill-key="client" data-drill-value="${escAttr(r.client_key)}" data-drill-label="${escAttr(r.client)}" data-drill-ca="${r.ca}"
      data-vip="${st === "vip" ? "1" : "0"}" data-loyal="${st === "loyal" ? "1" : "0"}" data-inactif="${st === "inactif" ? "1" : "0"}" data-churn="${st === "churn" ? "1" : "0"}" data-statut="${st}"
      data-cmd="${r.commandes || 0}" data-freq="${r.freq_mois || 0}" data-freq-lib="${escAttr(r.freq_libelle || "")}" data-jours="${r.jours_actif || 0}" data-jours-inactif="${r.jours_inactif ?? ""}" data-jours-entre="${r.jours_entre_cmd ?? ""}" data-panier="${r.panier_moyen || 0}" data-premiere="${escAttr(r.premiere || "")}" data-derniere="${escAttr(r.derniere || "")}" data-region="${escAttr(r.region || "")}" data-segment="${escAttr(r.segment || "")}"`;
  }

  function paintClientsTable(d) {
    const host = el("table-clients");
    if (!host) return;
    try {
      const rows = d.clients_detail || [];
      const q = (el("q-clients")?.value || "").trim().toLowerCase();
      let list = rows.filter((r) => {
        const st = statutClient(r);
        return `${r.client} ${r.region} ${r.segment} ${st} ${r.age}`.toLowerCase().includes(q);
      });
      list = list.slice(0, 250);
      const k = d.kpis || {};
      setMeta("table-clients-meta", rows.length, list.length, true);
      const meta = el("table-clients-meta");
      if (meta) {
        meta.textContent = `${list.length} affiché(s) · KPI : ${count(k.clients_vip || 0)} VIP · ${count(k.clients_loyal || 0)} loyaux · ${count(k.clients_inactif || 0)} inactifs · ${count(k.clients_churn || 0)} churn`;
      }
      host.innerHTML = !list.length
        ? `<p class="chart-hint" style="padding:16px">Aucun client pour ces filtres.</p>`
        : `<table><thead><tr>
        <th>Client</th><th>Région</th><th>Statut</th><th>Âge</th><th>1re achat</th><th>Dernier</th>
        <th>Sans achat</th><th>Commandes</th><th>Fréq. achat</th><th>CA (F CFA)</th>
      </tr></thead><tbody>${
        list.map((r) => {
          const st = statutClient(r);
          const ji = r.jours_inactif != null ? `${r.jours_inactif} j` : "—";
          return `<tr ${clientRowAttrs(r, st)}>
          <td>${r.client}</td><td>${r.region}</td><td>${badgeStatut(st)}</td><td>${r.age}</td>
          <td>${r.premiere || "—"}</td><td>${r.derniere || "—"}</td><td>${ji}</td>
          <td>${compact(r.commandes)}</td><td>${r.freq_libelle || (r.freq_mois != null ? `${r.freq_mois} cmd/mois` : "—")}</td><td>${money(r.ca)}</td>
        </tr>`;
        }).join("")
      }</tbody></table>`;
    } catch (err) {
      console.error("paintClientsTable", err);
      host.innerHTML = `<p class="chart-hint" style="padding:16px">Erreur affichage clients.</p>`;
    }
  }

  function paintStockTable(d) {
    const host = el("table-stock");
    if (!host) return;
    try {
      const rows = d.stock_detail || [];
      const q = (el("q-stock")?.value || "").trim().toLowerCase();
      const list = rows.filter((r) =>
        `${r.produit} ${r.categorie} ${r.marque}`.toLowerCase().includes(q)
      ).slice(0, 250);
      setMeta("table-stock-meta", rows.length, list.length, true);
      const fmtStock = (n) => (typeof count === "function" ? count(n) : compact(n));
      host.innerHTML = !list.length
        ? `<p class="chart-hint" style="padding:16px">Aucun stock pour ces filtres.</p>`
        : `<table><thead><tr>
        <th>Produit</th><th>Catégorie</th><th>Marque</th><th>Stock</th><th>Niveau</th><th>Prix catalogue</th>
      </tr></thead><tbody>${
        list.map((r) => `<tr class="drill-item" data-kind="stock" data-drill-key="produit" data-drill-value="${escAttr(r.produit)}" data-drill-label="${escAttr(r.produit)}" data-stock="${r.stock}" data-stock-cat="${escAttr(r.categorie || "")}" data-stock-niveau="${r.niveau || ""}">
          <td>${r.produit}</td><td>${r.categorie}</td><td>${r.marque}</td>
          <td>${fmtStock(r.stock)}</td>
          <td><span class="badge ${r.niveau === "ok" ? "ok" : r.niveau === "rupture" ? "bad" : "wait"}">${NIVEAU_FR[r.niveau] || r.niveau}</span></td>
          <td>${money(r.prix_catalogue || 0)}</td>
        </tr>`).join("")
      }</tbody></table>`;
    } catch (err) {
      console.error("paintStockTable", err);
      host.innerHTML = `<p class="chart-hint" style="padding:16px">Erreur affichage stock.</p>`;
    }
  }

  function escAttr(s) {
    return String(s ?? "").replace(/"/g, "&quot;").replace(/</g, "");
  }

  function paintStatutTable(hostId, metaId, d, statut, emptyMsg) {
    const host = el(hostId);
    if (!host) return;
    const rows = (d.clients_detail || []).filter((r) => statutClient(r) === statut);
    const top = statut === "churn" || statut === "inactif"
      ? [...rows].sort((a, b) => (b.jours_inactif || 0) - (a.jours_inactif || 0)).slice(0, 40)
      : rows.slice(0, 40);
    const totalKpi = {
      vip: d.kpis?.clients_vip,
      loyal: d.kpis?.clients_loyal,
      inactif: d.kpis?.clients_inactif,
      churn: d.kpis?.clients_churn,
    }[statut];
    if (el(metaId)) {
      const extra = statut === "vip" && d.kpis?.freq_vip_moy != null
        ? ` · freq. ${Number(d.kpis.freq_vip_moy).toFixed(2)} cmd/mois`
        : "";
      el(metaId).textContent = `${count(totalKpi != null ? totalKpi : rows.length)} au total · top ${top.length}${extra}`;
    }
    host.innerHTML = !top.length
      ? `<p class="chart-hint" style="padding:12px">${emptyMsg}</p>`
      : `<table><thead><tr>
        <th>Client</th><th>Région</th><th>Dernier</th><th>Sans achat</th>
        <th>Commandes</th><th>Fréq. achat</th><th>Panier moy.</th><th>CA (F CFA)</th>
      </tr></thead><tbody>${
        top.map((r) => {
          const st = statut;
          return `<tr ${clientRowAttrs(r, st)}>
          <td>${r.client}</td><td>${r.region}</td><td>${r.derniere || "—"}</td>
          <td>${r.jours_inactif != null ? `${r.jours_inactif} j` : "—"}</td>
          <td>${compact(r.commandes)}</td><td>${r.freq_libelle || (r.freq_mois != null ? `${r.freq_mois} cmd/mois` : "—")}</td>
          <td>${money(r.panier_moyen || 0)}</td><td>${money(r.ca || r.ca_historique || 0)}</td>
        </tr>`;
        }).join("")
      }</tbody></table>`;
  }

  function paintVipTable(d) {
    paintStatutTable("table-vip", "vip-meta", d, "vip", "Aucun client VIP (achats très fréquents) sur ce périmètre.");
  }
  function paintLoyalTable(d) {
    paintStatutTable("table-loyal", "loyal-meta", d, "loyal", "Aucun client loyal sur ce périmètre.");
  }
  function paintInactifTable(d) {
    paintStatutTable("table-inactif", "inactif-meta", d, "inactif", "Aucun client inactif (6 mois – 2 ans) sur ce périmètre.");
  }
  function paintChurnTable(d) {
    paintStatutTable("table-churn", "churn-meta", d, "churn", "Aucun client churn (≥ 2 ans sans achat) sur ce périmètre.");
  }

  function paintStockAlerts(d) {
    const host = el("stock-alerts");
    if (!host) return;
    const alerts = d.stock_alert || [];
    host.innerHTML = alerts.length
      ? alerts.map((s) => {
          const niveau = s.stock <= 0 ? "rupture" : s.stock < 40 ? "faible" : "ok";
          return `<li class="drill-item" data-kind="stock"
            data-drill-key="produit" data-drill-value="${escAttr(s.produit)}" data-drill-label="${escAttr(s.produit)}"
            data-stock="${s.stock}" data-stock-cat="${escAttr(s.categorie || "")}" data-stock-niveau="${niveau}">
            <span class="dot r"></span><div><b>${s.produit}</b><br/>stock ${s.stock}${s.categorie ? ` · ${s.categorie}` : ""}</div></li>`;
        }).join("")
      : "<li>Aucune alerte stock — bon niveau sur le périmètre filtré</li>";
  }

  function paintAllTables(d) {
    if (!d) return;
    try { paintTable(d.recent || [], "recent", "recent-meta"); } catch (e) { console.error(e); }
    paintProduitsTable(d);
    paintVipTable(d);
    paintLoyalTable(d);
    paintInactifTable(d);
    paintChurnTable(d);
    paintClientsTable(d);
    paintStockAlerts(d);
    paintStockTable(d);
  }

  function fixVentesKpis(d) {
    const k = d.kpis || {};
    const empty = !d.filtered_rows;
    const conv = empty ? "—" : `${Number(k.conversion || 0).toFixed(1)} %`;
    const host = el("kpi-ventes");
    if (!host) return;
    host.innerHTML = [
      kpiCard("hero", "CA net", money(k.ca), empty ? 0 : k.ca_delta),
      kpiCard("", "Unités vendues", compact(k.qty), empty ? 0 : k.qty_delta),
      kpiCard("", "Part promo", empty ? "—" : `${Number(k.promo_share || 0).toFixed(1)} %`, 0),
      kpiCard("", "Conversion", conv, 0),
    ].join("");
  }

  function forceResizeCharts() {
    requestAnimationFrame(() => {
      resizeAll();
      requestAnimationFrame(() => {
        resizeAll();
        setTimeout(resizeAll, 120);
      });
    });
  }

  const _renderBase = render;
  render = function (d) {
    _renderBase(d);
    fixVentesKpis(d);
    paintAllTables(d);
    if (typeof attachDrillLists === "function") attachDrillLists();
    forceResizeCharts();
  };

  /* Load immédiat + annulation des requêtes obsolètes */
  let loadSeq = 0;
  let loadAbort = null;

  const _load = load;
  load = async function (force = false) {
    const seq = ++loadSeq;
    if (loadAbort) loadAbort.abort();
    loadAbort = new AbortController();
    const { signal } = loadAbort;
    const qs = filterQuery();
    bar("on");
    try {
      const base = force ? "/api/refresh" : "/api/dashboard";
      const url = qs ? `${base}?${qs}` : base;
      const data = await fetch(url, { signal }).then((r) => r.json());
      if (seq !== loadSeq) return;
      render(data);
    } catch (err) {
      if (err?.name !== "AbortError" && seq === loadSeq) console.error(err);
    } finally {
      if (seq === loadSeq) {
        bar("done");
        setTimeout(() => bar(""), 400);
      }
    }
  };

  /* Remplace le listener app.js : load immédiat (pas de debounce) */
  document.querySelectorAll("select[data-filter]").forEach((node) => {
    if (node.dataset.instantBound) return;
    node.dataset.instantBound = "1";
    node.addEventListener("change", (e) => {
      e.stopImmediatePropagation();
      syncFilter(e.target.dataset.filter, e.target.value);
      load(false);
    }, true);
  });

  document.addEventListener("input", (e) => {
    if (e.target?.matches("#q-ventes, #q-produits, #q-clients, #q-stock") && DATA) {
      paintAllTables(DATA);
      if (typeof attachDrillLists === "function") attachDrillLists();
    }
  });

  ["q-ventes", "q-produits", "q-clients", "q-stock"].forEach((id) => {
    el(id)?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") load(false);
    });
  });

  /* Changement de menu : PAS de reload API — juste afficher + resize + re-peindre tableaux */
  document.querySelectorAll(".nav[data-view]").forEach((b) => {
    b.addEventListener("click", () => {
      setTimeout(() => {
        if (DATA) {
          populateFilters(DATA.filter_options || {}, DATA.active_filters || currentFilters());
          updateFilterMeta(DATA, CURRENT_VIEW);
          paintAllTables(DATA);
          if (typeof attachDrillLists === "function") attachDrillLists();
        }
        forceResizeCharts();
        if (typeof rebindAllDrills === "function") rebindAllDrills();
        if (String(CURRENT_VIEW || "").startsWith("ml") && typeof window.paintModelsView === "function") {
          window.paintModelsView();
        }
        setTimeout(() => {
          forceResizeCharts();
          if (typeof rebindAllDrills === "function") rebindAllDrills();
        }, 180);
      }, 30);
    });
  });
})();
