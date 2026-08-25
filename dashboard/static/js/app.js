const fmt = (n) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(n);
const PAL = ["#053f24", "#14a44d", "#0d7a3e", "#1ab85a", "#086b32", "#22c55e"];
const AXIS = "#5b6b64";
const GRID = "rgba(20,32,27,0.08)";
const TIP = { backgroundColor: "rgba(5,63,36,0.94)", borderWidth: 0, textStyle: { color: "#fff" } };
let DATA = null;
let PERIOD = "month";
let COMPARE = false;
const charts = {};
const DRILL_HANDLERS = {};

/* ── Helpers ── */
function compact(n) {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(Number(n) || 0);
  if (v >= 1e9) return sign + (v / 1e9).toFixed(1).replace(/\.0$/, "") + "Md";
  if (v >= 1e6) return sign + (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (v >= 1e3) return sign + (v / 1e3).toFixed(v >= 10_000 ? 0 : 1).replace(/\.0$/, "") + "K";
  return sign + fmt(v);
}
/** Compteurs métier : toujours le nombre exact (évite 4974 et 4960 → « 5K ») */
function count(n) {
  return fmt(Math.round(Number(n) || 0));
}
function money(n) { return compact(n) + " F"; }
function pct(n) {
  const v = Number(n) || 0;
  return (v > 0 ? "+" : "") + v.toFixed(1) + " %";
}
function pill(n) {
  if (n == null || n === "") return "";
  const v = Number(n) || 0;
  return `<span class="pill ${v < 0 ? "down" : "up"}">${pct(v)}</span>`;
}
function el(id) { return document.getElementById(id); }

function chart(id, option) {
  const node = el(id);
  if (!node) return;
  if (!charts[id]) charts[id] = echarts.init(node, null, { renderer: "canvas" });
  option.animation = true;
  option.animationDuration = 450;
  option.animationEasing = "cubicOut";
  charts[id].setOption(option, true);
}
function bindDrill(id, handler) {
  if (typeof handler === "function") DRILL_HANDLERS[id] = handler;
  const h = DRILL_HANDLERS[id];
  const c = charts[id];
  if (!c || !h) return;
  c.off("click");
  const onSeries = (params) => {
    try {
      if (params == null) return;
      const node = el(id);
      if (node) node.__drillHit = Date.now();
      h(params);
    } catch (err) {
      console.error("bindDrill", id, err);
    }
  };
  c.on("click", onSeries);
  const dom = c.getDom && c.getDom();
  if (dom) {
    dom.style.cursor = "pointer";
    if (!dom.__drillDomBound) {
      dom.__drillDomBound = true;
      dom.addEventListener("click", () => {
        /* Fallback si ECharts rate le hit (vue cachée / jauge / fond) */
        setTimeout(() => {
          const node = el(id);
          const recent = node && node.__drillHit && (Date.now() - node.__drillHit < 80);
          if (recent) return;
          const fn = DRILL_HANDLERS[id];
          if (!fn) return;
          try {
            fn({ dataIndex: 0, name: "", value: null, _fallback: true });
          } catch (err) {
            console.error("bindDrill fallback", id, err);
          }
        }, 30);
      });
    }
  }
}

function rebindAllDrills() {
  Object.keys(DRILL_HANDLERS).forEach((id) => {
    if (charts[id]) bindDrill(id);
  });
}
function barItem(color, radius = [6, 6, 0, 0]) {
  return {
    borderRadius: radius,
    color: {
      type: "linear", x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [
        { offset: 0, color: color },
        { offset: 1, color: color === "#14a44d" ? "#0d7a3e" : "#042f1a" },
      ],
    },
    shadowBlur: 6,
    shadowColor: "rgba(5,63,36,0.12)",
  };
}
function resizeAll() { Object.values(charts).forEach((c) => c.resize()); }
function bar(state) { const b = el("bar"); if (b) b.className = state; }

function donut(id, items, onClick) {
  chart(id, {
    tooltip: {
      trigger: "item",
      ...TIP,
      formatter: (p) => `${p.name}<br/><b>${money(p.value)}</b> · ${p.percent}%`,
    },
    series: [{
      type: "pie",
      radius: ["54%", "80%"],
      padAngle: 3,
      itemStyle: { borderRadius: 8, borderColor: "#fff", borderWidth: 3 },
      emphasis: {
        scale: true,
        scaleSize: 10,
        itemStyle: { shadowBlur: 14, shadowColor: "rgba(5,63,36,0.28)" },
      },
      label: { show: false },
      data: items.map((x, i) => ({
        name: x.name,
        value: x.value,
        itemStyle: { color: PAL[i % PAL.length] },
      })),
    }],
  });
  bindDrill(id, onClick);
}

function gauge(id, pctVal, color) {
  chart(id, {
    series: [{
      type: "pie", radius: ["68%", "88%"],
      label: { show: true, position: "center", formatter: pctVal.toFixed(1) + "%", fontSize: 15, fontWeight: 800, color: "#14201b" },
      data: [
        { value: pctVal, itemStyle: { color } },
        { value: Math.max(0, 100 - pctVal), itemStyle: { color: "rgba(20,32,27,0.08)" } },
      ],
    }],
  });
}

function seriesForPeriod(ts, period) {
  const daily = ts.daily && ts.daily.labels && ts.daily.labels.length ? ts.daily : null;
  if (period === "month" || !daily) return { labels: ts.labels || [], values: ts.values || [], qty: ts.qty || [] };
  if (period === "year") {
    const mapV = {}, mapQ = {};
    (ts.labels || []).forEach((l, i) => {
      const y = String(l).slice(0, 4);
      mapV[y] = (mapV[y] || 0) + ts.values[i];
      mapQ[y] = (mapQ[y] || 0) + ((ts.qty || [])[i] || 0);
    });
    const labels = Object.keys(mapV).sort();
    return { labels, values: labels.map((y) => mapV[y]), qty: labels.map((y) => mapQ[y]) };
  }
  const n = Math.min(30, daily.labels.length);
  return { labels: daily.labels.slice(-n), values: daily.values.slice(-n), qty: (daily.qty || []).slice(-n) };
}

function prevSeries(values) {
  return values.map((v, i) => Math.round((values[i - 1] || v) * 0.92));
}

function ringSvg(pctVal) {
  const r = 26, c = 2 * Math.PI * r, off = c - (Math.min(100, pctVal) / 100) * c;
  return `<svg class="ring" viewBox="0 0 64 64">
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="rgba(5,63,36,0.12)" stroke-width="7"/>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="#14a44d" stroke-width="7"
      stroke-dasharray="${c}" stroke-dashoffset="${off}" stroke-linecap="round"
      transform="rotate(-90 32 32)"/>
  </svg>`;
}

const KPI_ICONS = {
  "CA net":        { bg: "#e8f5e9", color: "#2e7d32", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>` },
  "Marge brute":   { bg: "#fff3e0", color: "#e65100", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 6l-9.5 9.5-5-5L1 18"/><polyline points="17 6 23 6 23 12"/></svg>` },
  "Commandes":     { bg: "#e3f2fd", color: "#1565c0", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M8 7h8M8 11h5"/></svg>` },
  "Panier moyen":  { bg: "#fce4ec", color: "#c62828", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>` },
  "Conversion":    { bg: "#e8f5e9", color: "#2e7d32", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>` },
  "Unités vendues":{ bg: "#ede7f6", color: "#4527a0", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>` },
  "Part promo":    { bg: "#fff8e1", color: "#f57f17", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>` },
  "Produits":      { bg: "#e0f2f1", color: "#00695c", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a4 4 0 0 0-8 0v2"/></svg>` },
  "Catégories":    { bg: "#f3e5f5", color: "#6a1b9a", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>` },
  "Promotions actives": { bg: "#fff3e0", color: "#e65100", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>` },
  "Multi-produits":{ bg: "#e8eaf6", color: "#283593", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M9 14l2 2 4-4"/></svg>` },
  "Clients":       { bg: "#e3f2fd", color: "#1565c0", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>` },
  "Acheteurs":     { bg: "#e8f5e9", color: "#2e7d32", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>` },
  "CLV moyen":     { bg: "#fff3e0", color: "#e65100", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>` },
  "CA VIP":        { bg: "#fce4ec", color: "#c62828", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>` },
  "Rotation":      { bg: "#e0f7fa", color: "#00838f", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>` },
  "Couverture":    { bg: "#e8eaf6", color: "#283593", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></svg>` },
  "Rupture":       { bg: "#ffebee", color: "#c62828", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>` },
  "Qualité données":{ bg: "#e8f5e9", color: "#2e7d32", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>` },
  "WAPE 30j":      { bg: "#e3f2fd", color: "#1565c0", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/></svg>` },
  "WAPE pricing":  { bg: "#fff3e0", color: "#e65100", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>` },
  "Recall@10":     { bg: "#ede7f6", color: "#4527a0", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>` },
  "ROI estimé":    { bg: "#fce4ec", color: "#c62828", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>` },
};

function kpiCard(cls, label, value, delta) {
  const icon = KPI_ICONS[label] || { bg: "#e8f5e9", color: "#2e7d32", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>` };
  return `<article class="kpi ${cls}">
    <div class="kpi-top">
      <div class="kpi-icon" style="background:${cls === "hero" ? "rgba(255,255,255,0.18)" : icon.bg}; color:${cls === "hero" ? "#fff" : icon.color}">${icon.svg}</div>
      ${pill(delta)}
    </div>
    <span class="label">${label}</span>
    <b>${value}</b>
  </article>`;
}

/* ── Filters ── */
const VIEW_FILTER_KEYS = {
  dashboard: ["periode", "annee", "mois", "region"],
  ventes: ["periode", "annee", "mois", "weekend", "promo", "statut", "region", "q"],
  produits: ["categorie", "marque", "produit", "promo"],
  clients: ["region", "segment", "age", "appareil", "source_trafic"],
  stock: ["categorie", "marque", "produit", "stock_level"],
};

const FILTER_LABELS = {
  periode: { "30d": "30 jours", "3m": "3 mois", "6m": "6 mois", "1y": "1 an", all: "Toute période" },
  weekend: { weekend: "Week-end", semaine: "Semaine", all: "Semaine + week-end" },
  promo: { oui: "Avec promo", non: "Sans promo", all: "Promo + plein tarif" },
  stock_level: { rupture: "Rupture", faible: "Stock faible", ok: "Stock OK", all: "Tous niveaux stock" },
  annee: { all: "Toutes années" },
  mois: { all: "Tous mois" },
  region: { all: "Toutes régions" },
  categorie: { all: "Toutes catégories" },
  marque: { all: "Toutes marques" },
  produit: { all: "Tous produits" },
  segment: { all: "Tous segments" },
  age: { all: "Tous âges" },
  statut: { all: "Tous statuts" },
  appareil: { all: "Tous appareils" },
  source_trafic: { all: "Toutes sources" },
};

const FILTER_OPTIONS_KEY = {
  periode: "periodes",
  categorie: "categories",
  marque: "marques",
  produit: "produits",
  region: "regions",
  segment: "segments",
  age: "ages",
  annee: "annees",
  mois: "mois",
  weekend: "weekends",
  promo: "promos",
  statut: "statuts",
  appareil: "appareils",
  source_trafic: "sources_trafic",
  stock_level: "stock_levels",
};

function labelForFilter(key, value) {
  if (key === "mois" && value !== "all") return `Mois ${value}`;
  if (key === "source_trafic" && value !== "all") return String(value).replace(/_/g, " ");
  return FILTER_LABELS[key]?.[value] || value;
}

function syncFilter(key, value) {
  document.querySelectorAll(`select[data-filter="${key}"]`).forEach((node) => {
    if ([...node.options].some((o) => o.value === value)) node.value = value;
  });
}

function fillSelectByKey(key, values, active) {
  const current = active?.[key] || "all";
  const defaultLabel = labelForFilter(key, "all");
  document.querySelectorAll(`select[data-filter="${key}"]`).forEach((node) => {
    node.innerHTML = `<option value="all">${defaultLabel}</option>` + (values || []).map((v) =>
      `<option value="${v}">${labelForFilter(key, v)}</option>`
    ).join("");
    node.value = [...node.options].some((o) => o.value === current) ? current : "all";
  });
}

function populateFilters(options, active) {
  const o = options || {};
  Object.keys(FILTER_OPTIONS_KEY).forEach((key) => {
    fillSelectByKey(key, o[FILTER_OPTIONS_KEY[key]] || [], active);
  });
  if (el("q-ventes")) el("q-ventes").value = active?.q || "";
}

function currentFilters() {
  const out = {};
  const seen = new Set();
  document.querySelectorAll("select[data-filter]").forEach((node) => {
    const key = node.dataset.filter;
    if (seen.has(key)) return;
    seen.add(key);
    const v = node.value;
    if (v && v !== "all") out[key] = v;
  });
  const q = (el("q-ventes")?.value || "").trim();
  if (q) out.q = q;
  return out;
}

function filterQuery() {
  return new URLSearchParams(currentFilters()).toString();
}

function resetViewFilters(view) {
  (VIEW_FILTER_KEYS[view] || []).forEach((key) => {
    if (key === "q") {
      if (el("q-ventes")) el("q-ventes").value = "";
      return;
    }
    syncFilter(key, "all");
  });
  load(false);
}

function updateFilterMeta(d, view) {
  const active = d.active_filters || {};
  const keys = VIEW_FILTER_KEYS[view] || [];
  const local = Object.keys(active).filter((k) => keys.includes(k));
  const rows = d.filtered_rows != null ? compact(d.filtered_rows) : "—";
  el("filter-meta").textContent = local.length
    ? `${local.length} filtre(s) · ${rows} lignes ventes`
    : `${rows} lignes ventes`;
}

/* ── Drill-down modal ── */
let pendingFilter = null;
let RECENT_ROWS = [];

function openDetail({ title, rows, filter }) {
  el("detail-title").textContent = title;
  el("detail-body").innerHTML = rows.map(([k, v]) =>
    `<div class="detail-row"><span>${k}</span><b>${v}</b></div>`
  ).join("");
  const applyBtn = el("detail-apply");
  if (filter?.key && filter?.value) {
    pendingFilter = filter;
    applyBtn.hidden = false;
    applyBtn.textContent = filter.label || "Appliquer ce filtre";
  } else {
    pendingFilter = null;
    applyBtn.hidden = true;
  }
  const modal = el("detail-modal");
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function closeDetail() {
  const modal = el("detail-modal");
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  pendingFilter = null;
}

function applyPendingFilter() {
  if (!pendingFilter) return;
  syncFilter(pendingFilter.key, pendingFilter.value);
  closeDetail();
  load(false);
}

function drillFromCategory(name, value, extra = []) {
  openDetail({
    title: name,
    rows: [["Catégorie", name], ["CA", money(value)], ...extra],
    filter: { key: "categorie", value: name, label: `Filtrer · ${name}` },
  });
}

function drillFromRegion(name, value) {
  openDetail({
    title: name,
    rows: [["Région", name], ["CA", money(value)]],
    filter: { key: "region", value: name, label: `Filtrer · ${name}` },
  });
}

function drillFromSegment(item) {
  openDetail({
    title: item.name,
    rows: [
      ["Segment", item.name],
      ["CA", money(item.value)],
      ...(item.clients ? [["Clients", compact(item.clients)]] : []),
    ],
    filter: { key: "segment", value: item.name, label: `Filtrer · ${item.name}` },
  });
}

function drillFromPeriod(label, value) {
  const rows = [["Période", label], ["CA", money(value)]];
  const filter = {};
  if (/^\d{4}-\d{2}$/.test(label)) {
    const [y, m] = label.split("-");
    rows.push(["Année", y], ["Mois", m]);
    filter.key = "mois";
    filter.value = String(Number(m));
    filter.label = `Filtrer · ${label}`;
    openDetail({ title: `CA · ${label}`, rows, filter });
    return;
  }
  if (/^\d{4}$/.test(label)) {
    filter.key = "annee";
    filter.value = label;
    filter.label = `Filtrer · ${label}`;
    openDetail({ title: `CA · ${label}`, rows, filter });
    return;
  }
  openDetail({ title: `CA · ${label}`, rows });
}

function statLi(name, right, drill) {
  if (!drill) return `<li><span>${name}</span><span>${right}</span></li>`;
  return `<li class="drill-item" data-drill-key="${drill.key}" data-drill-value="${drill.value}" data-drill-label="${name}" data-drill-ca="${drill.ca || 0}">
    <span>${name}</span><span>${right}</span></li>`;
}

function attachDrillLists() {
  document.querySelectorAll(".drill-item").forEach((node) => {
    node.onclick = () => {
      const key = node.dataset.drillKey;
      const value = node.dataset.drillValue;
      const label = node.dataset.drillLabel || value;
      const ca = Number(node.dataset.drillCa || 0);
      openDetail({
        title: label,
        rows: [[key === "categorie" ? "Catégorie" : key === "region" ? "Région" : "Élément", label], ["CA", money(ca)]],
        filter: { key, value, label: `Filtrer · ${label}` },
      });
    };
  });
  document.querySelectorAll("tr.drill-row").forEach((tr) => {
    tr.onclick = () => {
      const idx = Number(tr.dataset.idx);
      const r = RECENT_ROWS[idx];
      if (!r) return;
      openDetail({
        title: `Commande ${r.id}`,
        rows: [
          ["ID", r.id],
          ["Produit", r.produit],
          ["Catégorie", r.categorie || "—"],
          ["Région", r.region],
          ["Montant", money(r.montant)],
          ["Statut", r.statut],
        ],
        filter: r.region && r.region !== "—"
          ? { key: "region", value: r.region, label: `Filtrer · ${r.region}` }
          : null,
      });
    };
  });
}

/* ── Table ── */
function paintTable(rows) {
  RECENT_ROWS = rows;
  const q = (el("q-ventes")?.value || "").toLowerCase();
  const list = rows.filter((r) =>
    `${r.id} ${r.produit} ${r.region}`.toLowerCase().includes(q)
  );
  el("recent").innerHTML = `<table><thead><tr><th>ID</th><th>Produit</th><th>Région</th><th>Montant</th><th>Statut</th></tr></thead><tbody>${
    list.map((r, i) => `<tr class="drill-row" data-idx="${rows.indexOf(r)}"><td>${r.id}</td><td>${r.produit}</td><td>${r.region}</td><td>${money(r.montant)}</td>
      <td><span class="badge ${r.statut === "confirmee" ? "ok" : r.statut === "annulee" ? "bad" : "wait"}">${r.statut}</span></td></tr>`).join("")
  }</tbody></table>`;
}

/* ── Draw CA chart ── */
function drawCA() {
  if (!DATA) return;
  const s = seriesForPeriod(DATA.timeseries, PERIOD);
  const series = [{
    name: "CA",
    type: "bar",
    data: s.values,
    barWidth: 16,
    itemStyle: barItem("#14a44d"),
    emphasis: { itemStyle: { shadowBlur: 16, shadowColor: "rgba(20,164,77,0.35)" } },
  }];
  if (COMPARE) {
    series.push({
      name: "N-1",
      type: "bar",
      data: prevSeries(s.values),
      barWidth: 16,
      itemStyle: barItem("#053f24"),
    });
  }
  chart("chart-ca", {
    tooltip: { trigger: "axis", ...TIP, valueFormatter: (v) => compact(v) },
    legend: { bottom: 0, textStyle: { color: AXIS } },
    grid: { left: 48, right: 12, top: 16, bottom: 36 },
    xAxis: { type: "category", data: s.labels, axisLabel: { color: AXIS }, axisLine: { lineStyle: { color: GRID } } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    series,
  });
  bindDrill("chart-ca", (p) => {
    const label = s.labels[p.dataIndex];
    drillFromPeriod(label, s.values[p.dataIndex]);
  });
}

/* ── Main render ── */
function render(d) {
  DATA = d;
  el("source-tag").textContent = d.empty
    ? "Warehouse 0 ligne (RLS) · démo"
    : d.source === "supabase" ? "Supabase live"
    : (d.error ? "Erreur — démo" : "Mode démonstration");

  populateFilters(d.filter_options, d.active_filters);
  updateFilterMeta(d, CURRENT_VIEW);

  const k = d.kpis;

  /* ── DASHBOARD : KPI row ── */
  el("kpi-row").innerHTML = [
    kpiCard("hero", "CA net", money(k.ca), k.ca_delta),
    kpiCard("", "Marge brute", Number(k.margin_pct).toFixed(1) + " %", k.margin_delta),
    kpiCard("", "Commandes", count(k.commandes), k.orders_delta),
    kpiCard("", "Panier moyen", money(k.panier_moyen), 0),
  ].join("");

  /* ── DASHBOARD : CA chart ── */
  drawCA();

  /* ── DASHBOARD : Catégorie donut ── */
  const cats = d.categories.slice(0, 6);
  donut("chart-cat-donut", cats, (p) => drillFromCategory(p.name, p.value));
  el("cat-legend").innerHTML = d.categories.slice(0, 5).map((c) =>
    statLi(c.name, `<b>${money(c.value)}</b> ${pill(c.delta || 0)}`, { key: "categorie", value: c.name, ca: c.value })
  ).join("");

  /* ── DASHBOARD : Funnel ── */
  const views = d.funnel.view || 1, carts = d.funnel.add_to_cart || 1, purch = d.funnel.purchase || 0;
  chart("chart-funnel", {
    tooltip: { trigger: "axis", ...TIP, valueFormatter: (v) => compact(v) },
    grid: { left: 8, right: 8, top: 16, bottom: 28 },
    xAxis: { type: "category", data: ["Sessions", "Paniers", "Commandes"], axisLabel: { color: AXIS } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    series: [{
      type: "bar", data: [d.funnel.view, d.funnel.add_to_cart, d.funnel.purchase],
      barWidth: 32, itemStyle: barItem("#14a44d"),
      emphasis: { itemStyle: { shadowBlur: 14 } },
    }],
  });
  bindDrill("chart-funnel", (p) => {
    const names = ["Sessions", "Paniers", "Commandes"];
    const vals = [d.funnel.view, d.funnel.add_to_cart, d.funnel.purchase];
    openDetail({ title: names[p.dataIndex], rows: [[names[p.dataIndex], compact(vals[p.dataIndex])]] });
  });
  el("funnel-list").innerHTML = [
    ["Sessions", d.funnel.view, 100],
    ["Paniers", d.funnel.add_to_cart, views ? (carts / views) * 100 : 0],
    ["Commandes", d.funnel.purchase, views ? (purch / views) * 100 : 0],
  ].map(([n, v, p]) => `<li><span>${n}</span><span><b>${compact(v)}</b> ${p.toFixed(1)}%</span></li>`).join("");

  /* ── DASHBOARD : Segments ── */
  const segs = d.segments || [];
  donut("chart-seg", segs, (p) => {
    const item = segs.find((s) => s.name === p.name) || { name: p.name, value: p.value };
    drillFromSegment(item);
  });
  const segSum = segs.reduce((a, x) => a + x.value, 0) || 1;
  el("seg-list").innerHTML = segs.map((s) =>
    statLi(
      `${s.name}${s.clients ? ` · ${compact(s.clients)} cl.` : ""}`,
      `<b>${money(s.value)}</b> ${((s.value / segSum) * 100).toFixed(1)} %`,
      { key: "segment", value: s.name, ca: s.value }
    )
  ).join("");

  /* ── VENTES : KPI ── */
  el("kpi-ventes").innerHTML = [
    kpiCard("hero", "CA net", money(k.ca), k.ca_delta),
    kpiCard("", "Unités vendues", compact(k.qty), k.qty_delta),
    kpiCard("", "Part promo", Number(k.promo_share).toFixed(1) + " %", 0),
    kpiCard("", "Conversion", Number(k.conversion).toFixed(1) + " %", 0),
  ].join("");

  /* ── VENTES : Région ── */
  const regionNames = d.regions.map((x) => x.name);
  const regionVals = d.regions.map((x) => x.value);
  chart("chart-region", {
    tooltip: { trigger: "axis", ...TIP, valueFormatter: (v) => compact(v) },
    grid: { left: 90, right: 16, top: 8, bottom: 8 },
    xAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    yAxis: { type: "category", data: regionNames.slice().reverse(), axisLabel: { color: AXIS } },
    series: [{
      type: "bar",
      data: regionVals.slice().reverse(),
      barWidth: 14,
      itemStyle: barItem("#053f24", [0, 8, 8, 0]),
      emphasis: { itemStyle: { shadowBlur: 14 } },
    }],
  });
  bindDrill("chart-region", (p) => {
    const name = regionNames.slice().reverse()[p.dataIndex];
    const value = regionVals.slice().reverse()[p.dataIndex];
    drillFromRegion(name, value);
  });

  /* ── VENTES : Promo donut ── */
  donut("chart-promo", [
    { name: "Plein tarif", value: Math.max(0, 100 - (k.promo_share || 0)) },
    { name: "Promo", value: k.promo_share || 0 },
  ], (p) => {
    const isPromo = p.name === "Promo";
    openDetail({
      title: p.name,
      rows: [["Part", `${Number(p.value).toFixed(1)} %`], ["CA estimé", money(isPromo ? k.ca * (k.promo_share || 0) / 100 : k.ca - k.ca * (k.promo_share || 0) / 100)]],
      filter: { key: "promo", value: isPromo ? "oui" : "non", label: isPromo ? "Filtrer · avec promo" : "Filtrer · sans promo" },
    });
  });

  /* ── VENTES : CA & unités ── */
  const s = seriesForPeriod(d.timeseries, "month");
  chart("chart-ca-qty", {
    tooltip: { trigger: "axis", ...TIP, valueFormatter: (v) => compact(v) },
    legend: { top: 0, textStyle: { color: AXIS } },
    grid: { left: 48, right: 12, top: 36, bottom: 28 },
    xAxis: { type: "category", data: s.labels, axisLabel: { color: AXIS }, axisLine: { lineStyle: { color: GRID } } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    series: [
      { name: "CA", type: "bar", data: s.values, barWidth: 12, itemStyle: barItem("#14a44d") },
      { name: "Unités", type: "bar", data: s.qty, barWidth: 12, itemStyle: barItem("#053f24") },
    ],
  });
  bindDrill("chart-ca-qty", (p) => drillFromPeriod(s.labels[p.dataIndex], s.values[p.dataIndex]));

  /* ── VENTES : Rentabilité ── */
  const cost = Math.max(0, k.ca - k.profit);
  const promo = Math.round(k.ca * (k.promo_share || 0) / 100);
  const breakItems = [
    ["Coût produits", cost, "#053f24"],
    ["Marge brute", k.profit, "#14a44d"],
    ["CA promo", promo, "#0d7a3e"],
    ["CA net", k.ca, "#1ab85a"],
  ];
  chart("chart-rentab", {
    tooltip: { ...TIP, valueFormatter: (v) => compact(v) },
    grid: { left: 8, right: 8, top: 12, bottom: 28 },
    xAxis: { type: "category", data: breakItems.map((x) => x[0]), axisLabel: { color: AXIS, fontSize: 11 } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    series: [{
      type: "bar", data: breakItems.map((x) => ({ value: x[1], itemStyle: { color: x[2] } })),
      barWidth: 18, itemStyle: { borderRadius: [8, 8, 0, 0] },
    }],
  });
  bindDrill("chart-rentab", (p) => {
    const item = breakItems[p.dataIndex] || breakItems[0];
    if (!item) return;
    openDetail({
      title: item[0],
      rows: breakItems.map((x) => [x[0], money(x[1])]),
    });
  });
  el("rentab-list").innerHTML = breakItems.map((x) =>
    `<li><span><span class="dot" style="background:${x[2]};display:inline-block;margin-right:8px"></span>${x[0]}</span><b>${money(x[1])}</b></li>`
  ).join("");

  paintTable(d.recent);

  /* ── PRODUITS : KPI ── */
  el("kpi-produits").innerHTML = [
    kpiCard("hero", "Produits vendus", count(k.produits), 0),
    kpiCard("", "Catégories", count(d.categories.length), 0),
    kpiCard("", "Promos utilisées", count(k.promos), 0),
    kpiCard("", "Multi-produits", Number(k.multi_pct).toFixed(1) + " %", 0),
  ].join("");

  /* ── PRODUITS : CA par catégorie bar ── */
  chart("chart-cat-bar", {
    tooltip: { trigger: "axis", ...TIP, valueFormatter: (v) => compact(v) },
    grid: { left: 90, right: 16, top: 8, bottom: 8 },
    xAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    yAxis: { type: "category", data: d.categories.slice(0, 8).map((x) => x.name).reverse(), axisLabel: { color: AXIS } },
    series: [{ type: "bar", data: d.categories.slice(0, 8).map((x) => x.value).reverse(), barWidth: 12, itemStyle: { color: "#14a44d", borderRadius: [0, 8, 8, 0] } }],
  });
  bindDrill("chart-cat-bar", (p) => {
    const cats = d.categories.slice(0, 8).reverse();
    const c = cats[p.dataIndex] || { name: p.name, value: p.value };
    if (c?.name) drillFromCategory(c.name, c.value || 0);
  });
  el("cat-list").innerHTML = d.categories.slice(0, 8).map((c) =>
    `<li><span>${c.name}</span><span><b>${money(c.value)}</b> ${pill(c.delta || 0)}</span></li>`
  ).join("");

  /* ── PRODUITS : Part promo par catégorie (placeholder as donut) ── */
  donut("chart-cat-promo", d.categories.slice(0, 6), (p) => drillFromCategory(p.name, p.value));

  /* ── CLIENTS : KPI ── */
  el("kpi-clients").innerHTML = [
    kpiCard("hero", "Clients uniques", count(k.clients_uniques ?? k.clients), null),
    kpiCard("", "VIP", count(k.clients_vip || 0), null),
    kpiCard("", "Loyaux", count(k.clients_loyal || 0), null),
    kpiCard("", "Inactifs", count(k.clients_inactif || 0), null),
    kpiCard("", "Churn (≥ 2 ans)", count(k.clients_churn || 0), null),
  ].join("");
  const sumStat = (k.clients_vip || 0) + (k.clients_loyal || 0) + (k.clients_inactif || 0) + (k.clients_churn || 0);
  if (el("clients-statut-note")) {
    el("clients-statut-note").textContent =
      `VIP + Loyaux + Inactifs + Churn = ${count(sumStat)} uniques`
      + (k.clients && k.clients !== k.clients_uniques
        ? ` · Cumul client×année (toutes années) : ${count(k.clients)}`
        : "");
  }

  /* ── CLIENTS : Device ── */
  donut("chart-device", d.devices.length ? d.devices : [{ name: "n/a", value: 1 }], (p) => {
    openDetail({
      title: p.name,
      rows: [["Appareil", p.name], ["Valeur", money(p.value)]],
      filter: { key: "appareil", value: p.name, label: `Filtrer · ${p.name}` },
    });
  });

  /* ── CLIENTS : Traffic ── */
  const traf = d.traffic.length ? d.traffic : d.categories;
  chart("chart-traffic", {
    tooltip: { trigger: "axis", ...TIP, valueFormatter: (v) => compact(v) },
    grid: { left: 40, right: 12, top: 12, bottom: 48 },
    xAxis: { type: "category", data: traf.map((x) => x.name), axisLabel: { color: AXIS, rotate: 20 } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, formatter: (v) => compact(v) } },
    series: [{ type: "bar", data: traf.map((x) => x.value), itemStyle: { borderRadius: [8, 8, 0, 0], color: "#14a44d" } }],
  });
  bindDrill("chart-traffic", (p) => {
    const item = traf[p.dataIndex] || { name: p.name, value: p.value };
    if (!item?.name) return;
    openDetail({
      title: item.name,
      rows: [["Source", item.name], ["Valeur", money(item.value)]],
      filter: { key: "source_trafic", value: item.name, label: `Filtrer · ${item.name}` },
    });
  });

  /* ── CLIENTS : Région bars ── */
  const maxR = Math.max(...d.regions.map((r) => r.value), 1);
  el("region-bars").innerHTML = d.regions.slice(0, 6).map((r) =>
    `<li class="drill-item" data-drill-key="region" data-drill-value="${r.name}" data-drill-label="${r.name}" data-drill-ca="${r.value}"><span>${r.name}</span><span class="track"><span class="fill" style="width:${Math.round((r.value / maxR) * 100)}%"></span></span><b>${money(r.value)}</b></li>`
  ).join("");

  /* ── CLIENTS : Abandon gauges ── */
  const abandonCart = k.abandon_pct || 0;
  const abandonRev = views ? (1 - purch / views) * 100 : 0;
  gauge("chart-abandon-cart", abandonCart, "#14a44d");
  gauge("chart-abandon-rev", abandonRev, "#053f24");
  bindDrill("chart-abandon-cart", () => {
    openDetail({
      title: "Paniers abandonnés",
      rows: [["Taux abandon", `${abandonCart.toFixed(1)} %`]],
    });
  });
  bindDrill("chart-abandon-rev", () => {
    openDetail({
      title: "Vues sans achat",
      rows: [["Sans achat", `${abandonRev.toFixed(1)} %`]],
    });
  });
  el("abandon-cart-n").textContent = compact(Math.max(0, carts - purch));
  el("abandon-rev-n").textContent = money(Math.round(k.ca * abandonRev / 100));

  /* ── STOCK : KPI ── */
  el("kpi-stock").innerHTML = [
    kpiCard("hero", "Rotation", Number(k.stock_rotation).toFixed(2) + "x", 0),
    kpiCard("", "Couverture", compact(k.stock_cover_days) + " j", 0),
    kpiCard("", "Rupture", Number(k.rupture_pct).toFixed(1) + " %", 0),
    kpiCard("", "Qualité données", Number(k.data_quality).toFixed(1) + " %", 0),
  ].join("");

  /* ── STOCK : Alertes (cliquables → modal) ── */
  el("stock-alerts").innerHTML = (d.stock_alert || []).length
    ? d.stock_alert.map((s) => {
        const niveau = s.stock <= 0 ? "rupture" : s.stock < 40 ? "faible" : "ok";
        const prod = String(s.produit || "").replace(/"/g, "&quot;");
        const cat = String(s.categorie || "").replace(/"/g, "&quot;");
        return `<li class="drill-item" data-kind="stock"
          data-drill-key="produit" data-drill-value="${prod}" data-drill-label="${prod}"
          data-stock="${s.stock}" data-stock-cat="${cat}" data-stock-niveau="${niveau}">
          <span class="dot r"></span><div><b>${s.produit}</b><br/>stock ${s.stock}${s.categorie ? ` · ${s.categorie}` : ""}</div></li>`;
      }).join("")
    : "<li>Aucune alerte stock</li>";

  /* ── ML : rendu délégué aux menus outils métier ── */
  if (typeof CURRENT_VIEW !== "undefined" && String(CURRENT_VIEW).startsWith("ml") && typeof window.paintModelsView === "function") {
    window.paintModelsView();
  }

  setTimeout(resizeAll, 80);
}

/* ── Load ── */
async function load(force = false) {
  bar("on");
  try {
    const qs = filterQuery();
    const base = force ? "/api/refresh" : "/api/dashboard";
    const url = qs ? `${base}?${qs}` : base;
    render(await fetch(url).then((r) => r.json()));
  } finally {
    bar("done");
    setTimeout(() => bar(""), 500);
  }
}

let searchTimer = null;
function scheduleLoad() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => load(false), 350);
}

/* ── Init ── */
const VIEW_TITLES = {
  dashboard: "Sales Report",
  ventes: "Ventes & Rentabilité",
  produits: "Produits & Catégories",
  clients: "Clients & Parcours",
  stock: "Stock & Réapprovisionnement",
  ml: "Outils métier",
  "ml-forecast": "Prévisions des ventes",
  "ml-pricing": "Simulation des prix",
  "ml-reco": "Recommandation — gains de classement",
};
let CURRENT_VIEW = "dashboard";

el("today").textContent = new Date().toLocaleDateString("fr-FR", {
  weekday: "long", day: "numeric", month: "long", year: "numeric",
});

document.querySelectorAll(".nav[data-view]").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".nav[data-view]").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("on"));
    el("view-" + b.dataset.view).classList.add("on");
    CURRENT_VIEW = b.dataset.view;
    el("view-title").textContent = VIEW_TITLES[CURRENT_VIEW] || "Dashboard";
    if (DATA) updateFilterMeta(DATA, CURRENT_VIEW);
    setTimeout(() => {
      resizeAll();
      rebindAllDrills();
    }, 40);
    setTimeout(() => {
      resizeAll();
      rebindAllDrills();
    }, 200);
  });
});

/* Uniquement les boutons période — pas les .f-btn du modal (Fermer / Excel / Explorer) */
document.querySelectorAll(".f-btn[data-period]").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".f-btn[data-period]").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    PERIOD = b.dataset.period;
    drawCA();
  });
});

el("compare").addEventListener("change", (e) => { COMPARE = e.target.checked; drawCA(); });
document.querySelectorAll("select[data-filter]").forEach((node) => {
  node.addEventListener("change", (e) => {
    syncFilter(e.target.dataset.filter, e.target.value);
    load(false);
  });
});
el("q-ventes")?.addEventListener("input", scheduleLoad);
document.querySelectorAll("[data-reset-view]").forEach((btn) => {
  btn.addEventListener("click", () => resetViewFilters(btn.dataset.resetView));
});
el("refresh").addEventListener("click", () => load(true));
window.addEventListener("resize", resizeAll);
/* Chargement immédiat + modèles en parallèle */
load();
if (typeof window.loadModelsLive === "function") {
  window.loadModelsLive(false);
}
