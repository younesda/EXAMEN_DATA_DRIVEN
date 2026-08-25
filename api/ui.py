from __future__ import annotations

# ruff: noqa: E501 -- HTML, CSS and JavaScript are kept as a self-contained deployable page.

UI_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Model API — Console</title>
  <style>
    :root { color-scheme: dark; --bg:#07111f; --panel:#0d1b2d; --line:#203653; --text:#edf5ff; --muted:#9db0c8; --accent:#66e3b4; --danger:#ff8b8b; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; color:var(--text); background:radial-gradient(circle at top right,#163654 0,transparent 35%),var(--bg); }
    main { width:min(1100px,calc(100% - 32px)); margin:40px auto 64px; }
    header { display:flex; gap:24px; align-items:end; justify-content:space-between; margin-bottom:24px; }
    h1 { margin:0; font-size:clamp(28px,5vw,48px); letter-spacing:-.04em; }
    h2 { margin:0 0 6px; font-size:19px; }
    p { margin:4px 0; color:var(--muted); }
    a { color:var(--accent); }
    .links { white-space:nowrap; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
    .card { padding:20px; border:1px solid var(--line); border-radius:16px; background:color-mix(in srgb,var(--panel) 94%,transparent); box-shadow:0 18px 50px #0004; }
    .wide { grid-column:1/-1; }
    .keyrow,.row { display:flex; gap:10px; margin-top:14px; }
    label { display:block; color:var(--muted); margin-top:12px; }
    input,textarea { width:100%; margin-top:5px; padding:11px 12px; color:var(--text); background:#071321; border:1px solid var(--line); border-radius:9px; font:inherit; }
    input:focus,textarea:focus { outline:2px solid #66e3b466; border-color:var(--accent); }
    textarea { min-height:74px; resize:vertical; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }
    button { padding:11px 16px; border:0; border-radius:9px; color:#062017; background:var(--accent); font-weight:750; cursor:pointer; }
    button:disabled { opacity:.55; cursor:wait; }
    .secondary { color:var(--text); background:#1c3450; }
    .notice { border-left:3px solid #f7c66b; padding-left:12px; }
    .result { display:none; margin-top:14px; padding:14px; max-height:380px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; color:#cfe5ff; background:#050d18; border:1px solid var(--line); border-radius:10px; font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }
    .result.error { color:var(--danger); border-color:#723d48; }
    .badge { display:inline-block; padding:3px 8px; margin-left:7px; border-radius:999px; background:#173c35; color:var(--accent); font-size:12px; vertical-align:middle; }
    small { color:var(--muted); }
    @media (max-width:760px) { header { align-items:start; flex-direction:column; } .grid { grid-template-columns:1fr; } .wide { grid-column:auto; } .keyrow,.row { flex-direction:column; } }
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Model API <span class="badge">en ligne</span></h1><p>Recommandation et simulation pricing — console interactive.</p></div>
    <nav class="links"><a href="/docs">Documentation</a> · <a href="/health">Santé</a> · <a href="/ready">Modèles prêts</a></nav>
  </header>

  <section class="card wide">
    <h2>Connexion</h2>
    <p>Entrez la clé configurée dans Render. Elle reste en mémoire dans cette page et n’est pas enregistrée.</p>
    <div class="keyrow"><input id="apiKey" type="password" autocomplete="off" placeholder="X-API-Key" aria-label="Clé API"><button type="button" data-action="status">Vérifier et afficher les modèles</button></div>
    <pre id="statusResult" class="result" aria-live="polite"></pre>
  </section>

  <div class="grid" style="margin-top:18px">
    <section class="card">
      <h2>Recommandations générales</h2>
      <p>Baseline validée : <strong>popularite_globale</strong>.</p>
      <label>Nombre de produits (1–50)<input id="generalK" type="number" min="1" max="50" value="10"></label>
      <label>Produits à exclure, séparés par des virgules<input id="generalExclude" placeholder="PRD000001, PRD000002"></label>
      <div class="row"><button type="button" data-action="general">Obtenir les recommandations</button></div>
      <pre id="generalResult" class="result" aria-live="polite"></pre>
    </section>

    <section class="card">
      <h2>Complément panier</h2>
      <p>Baseline popularité globale ; aucun modèle personnalisé validé.</p>
      <label>Produits du panier, séparés par des virgules<input id="basketProducts" value="PRD000001" required></label>
      <label>Nombre de produits (1–50)<input id="basketK" type="number" min="1" max="50" value="10"></label>
      <div class="row"><button type="button" data-action="basket">Compléter le panier</button></div>
      <pre id="basketResult" class="result" aria-live="polite"></pre>
    </section>

    <section class="card wide">
      <h2>Simulation pricing</h2>
      <p class="notice">Modèle exploratoire non causal. Validation humaine obligatoire ; aucune application automatique.</p>
      <div class="grid">
        <label>Produit<input id="pricingProduct" value="PRD000000"></label>
        <label>Date de décision<input id="pricingDate" type="date" value="2026-08-18"></label>
        <label>Remises candidates (%), séparées par des virgules<input id="pricingDiscounts" value="0"></label>
        <label>Stock à la date de décision<input id="pricingStock" type="number" step="any" value="152.5"></label>
      </div>
      <div class="row"><button type="button" data-action="pricing">Simuler les prix</button></div>
      <pre id="pricingResult" class="result" aria-live="polite"></pre>
    </section>
  </div>
</main>
<script>
  const byId = id => document.getElementById(id);
  const csv = value => value.split(',').map(v => v.trim()).filter(Boolean);
  const numbers = value => csv(value).map(Number);

  async function request(path, options, outputId, button) {
    const output = byId(outputId);
    const key = byId('apiKey').value.trim();
    output.style.display = 'block';
    output.classList.remove('error');
    if (!key) {
      output.classList.add('error');
      output.textContent = 'Entrez d’abord votre clé API.';
      return;
    }
    button.disabled = true;
    output.textContent = 'Chargement…';
    try {
      const response = await fetch(path, {
        ...options,
        headers: {'X-API-Key': key, 'Content-Type': 'application/json', ...(options.headers || {})}
      });
      const body = await response.json().catch(() => ({detail: 'Réponse non JSON'}));
      output.classList.toggle('error', !response.ok);
      output.textContent = JSON.stringify(body, null, 2);
    } catch (error) {
      output.classList.add('error');
      output.textContent = `Connexion impossible : ${error.message}`;
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (action === 'status') request('/api/v1/models/status', {method:'GET'}, 'statusResult', button);
    if (action === 'general') request('/api/v1/recommendations/general', {method:'POST', body:JSON.stringify({k:Number(byId('generalK').value), exclude_product_keys:csv(byId('generalExclude').value)})}, 'generalResult', button);
    if (action === 'basket') request('/api/v1/recommendations/basket', {method:'POST', body:JSON.stringify({product_keys:csv(byId('basketProducts').value), k:Number(byId('basketK').value)})}, 'basketResult', button);
    if (action === 'pricing') request('/api/v1/pricing/simulate', {method:'POST', body:JSON.stringify({product_key:byId('pricingProduct').value.trim(), decision_date:byId('pricingDate').value, candidate_discounts_pct:numbers(byId('pricingDiscounts').value), features:{stock_at_cutoff:Number(byId('pricingStock').value)}})}, 'pricingResult', button);
  });
</script>
</body>
</html>
"""
