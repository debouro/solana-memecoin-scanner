const app = document.getElementById("app");
let refreshTimer = null;
let currentChart = null;
let currentSeries = null;
let selectedTrade = null;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
}

const fmtUsd = (v) => v === null || v === undefined ? "—" : "$" + Number(v).toLocaleString("fr-FR", { maximumFractionDigits: v < 1 ? 8 : 2 });
const fmtPct = (v) => v === null || v === undefined ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2) + " %";
const fmtPctCls = (v) => v === null || v === undefined ? "neutral" : v >= 0 ? "up" : "down";
const fmtDate = (iso) => iso ? new Date(iso).toLocaleString("fr-FR") : "—";
const fmtDur = (s) => {
  if (s === null || s === undefined) return "—";
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return (s / 60).toFixed(1) + " min";
  if (s < 86400) return (s / 3600).toFixed(1) + " h";
  return (s / 86400).toFixed(1) + " j";
};
const shortMint = (m) => m ? m.slice(0, 6) + "…" + m.slice(-4) : "—";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function setStatus() {
  api("/stats/global").then((s) => {
    const el = document.getElementById("scanner-status");
    const ok = s.scanner_status === "running";
    el.textContent = (ok ? "● " : "● ") + (s.scanner_status === "running" ? "Scanner actif" : s.scanner_status) + (s.last_scan ? " · dernier scan " + fmtDate(s.last_scan.finished_at) : "");
    el.className = "scanner-status " + (ok ? "ok" : "err");
    const badge = document.getElementById("notif-badge");
    badge.textContent = s.unread_notifications;
    badge.classList.toggle("hidden", s.unread_notifications === 0);
  }).catch(() => {});
}

async function toggleFavorite(mint, isFav) {
  try {
    if (isFav) await api("/favorites/" + mint, { method: "DELETE" });
    else await api("/favorites/" + mint, { method: "POST" });
    toast(isFav ? "Retiré des favoris" : "Ajouté aux favoris");
    return !isFav;
  } catch (e) { toast("Erreur: " + e.message); return isFav; }
}

function starBtn(mint, isFav) {
  return `<button class="star ${isFav ? "on" : ""}" data-mint="${esc(mint)}" data-fav="${isFav}" title="Favori">★</button>`;
}

document.addEventListener("click", async (ev) => {
  const star = ev.target.closest(".star");
  if (star) {
    ev.stopPropagation();
    const mint = star.dataset.mint;
    const nowFav = await toggleFavorite(mint, star.dataset.fav === "true");
    star.dataset.fav = nowFav;
    star.classList.toggle("on", nowFav);
  }
});

const PHASE_LABEL = { up: "Phase ascendante", down: "Phase descendante", consolidation: "Consolidation", new_cycle: "Nouveau cycle", insufficient: "Données insuffisantes" };
function phaseBadge(p) {
  return `<span class="phase ${esc(p.phase)}">${esc(PHASE_LABEL[p.phase] || p.phase)}</span>`;
}

async function viewDashboard() {
  const params = new URLSearchParams(dashState);
  app.innerHTML = `<h1>Dashboard</h1><div class="subtitle">Memecoins Solana suivis par le moteur (market cap ≥ seuil) — actualisation automatique</div>
  <div class="cards" id="kpis"></div>
  <div class="toolbar">
    <input id="q" placeholder="Recherche nom, symbole ou mint…" value="${esc(dashState.search || "")}" style="min-width:240px">
    <label>MCap min <input id="f-mcap" type="number" value="${dashState.min_mcap || ""}" style="width:110px"></label>
    <label>Vol 24h min <input id="f-vol" type="number" value="${dashState.min_volume || ""}" style="width:110px"></label>
    <label>Liquidité min <input id="f-liq" type="number" value="${dashState.min_liquidity || ""}" style="width:110px"></label>
    <label>Phase <select id="f-phase"><option value="">Toutes</option>${["up","down","consolidation","new_cycle","insufficient"].map(p => `<option value="${p}" ${dashState.phase === p ? "selected" : ""}>${PHASE_LABEL[p]}</option>`).join("")}</select></label>
    <label>Tri <select id="f-sort">${[["mcap","Market cap"],["volume","Volume 24h"],["liquidity","Liquidité"],["amplitude","Amplitude moy."],["cycles","Nb cycles"],["updated","Dernière maj"],["name","Nom"]].map(([v,l]) => `<option value="${v}" ${dashState.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <select id="f-order"><option value="desc" ${dashState.order !== "asc" ? "selected" : ""}>↓ desc</option><option value="asc" ${dashState.order === "asc" ? "selected" : ""}>↑ asc</option></select>
    <label><input type="checkbox" id="f-refresh" ${dashState.refresh ? "checked" : ""}> auto</label>
    <button class="secondary small" id="btn-apply">Appliquer</button>
  </div>
  <div class="table-wrap"><table class="data" id="tbl"><thead><tr>
    <th></th><th>Token</th><th>Mint</th><th>Market Cap</th><th>Prix</th><th>Vol 24h</th><th>Liquidité</th><th>5m</th><th>1h</th><th>24h</th><th>Cycles</th><th>Ampl. moy.</th><th>Durée moy.</th><th>Phase</th><th>Maj</th>
  </tr></thead><tbody id="tbody"></tbody></table></div>
  <div class="pagination" id="pager"></div>`;
  document.getElementById("btn-apply").onclick = () => {
    dashState.search = document.getElementById("q").value;
    dashState.min_mcap = document.getElementById("f-mcap").value;
    dashState.min_volume = document.getElementById("f-vol").value;
    dashState.min_liquidity = document.getElementById("f-liq").value;
    dashState.phase = document.getElementById("f-phase").value;
    dashState.sort = document.getElementById("f-sort").value;
    dashState.order = document.getElementById("f-order").value;
    dashState.page = 1;
    dashState.refresh = document.getElementById("f-refresh").checked;
    loadDashboard();
  };
  await loadDashboard();
  setStatus();
}

const dashState = { search: "", min_mcap: "", min_volume: "", min_liquidity: "", phase: "", sort: "mcap", order: "desc", page: 1, page_size: 25, refresh: true };

async function loadDashboard() {
  clearInterval(refreshTimer);
  const p = new URLSearchParams({ sort: dashState.sort, order: dashState.order, page: dashState.page, page_size: dashState.page_size });
  if (dashState.search) p.set("search", dashState.search);
  if (dashState.min_mcap) p.set("min_mcap", dashState.min_mcap);
  if (dashState.min_volume) p.set("min_volume", dashState.min_volume);
  if (dashState.min_liquidity) p.set("min_liquidity", dashState.min_liquidity);
  if (dashState.phase) p.set("phase", dashState.phase);
  try {
    const [sum, glob] = await Promise.all([api("/tokens/summary?" + p), api("/stats/global")]);
    document.getElementById("kpis").innerHTML = [
      ["Tokens surveillés", glob.tokens_tracked], ["Passent les filtres", glob.tokens_passed_filters],
      ["Nouveaux aujourd'hui", glob.new_today], ["Cycles aujourd'hui", glob.cycles_today],
      ["Phase ascendante", glob.phases.up], ["Phase descendante", glob.phases.down],
      ["Consolidation", glob.phases.consolidation], ["Nouveaux cycles", glob.phases.new_cycle],
    ].map(([l, v]) => `<div class="card"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("");
    const tb = document.getElementById("tbody");
    tb.innerHTML = sum.rows.map(r => {
      const l = r.latest || {};
      const s = r.stats || {};
      const logo = r.logo_url ? `<img src="${esc(r.logo_url)}" onerror="this.outerHTML='<span class=\\'placeholder\\'>${esc((r.symbol||'?')[0])}</span>'">` : `<span class="placeholder">${esc((r.symbol || "?")[0])}</span>`;
      return `<tr class="clickable" data-mint="${esc(r.mint)}">
        <td>${starBtn(r.mint, r.favorite)}</td>
        <td><div class="token-cell">${logo}<div class="names"><span class="sym">${esc(r.symbol || "?")}</span><span class="nm">${esc(r.name || "")}</span></div></div></td>
        <td class="mono" title="${esc(r.mint)}">${shortMint(r.mint)}</td>
        <td>${fmtUsd(l.market_cap)}</td>
        <td class="mono">${l.price_usd !== null && l.price_usd !== undefined ? Number(l.price_usd).toExponential(3) : "—"}</td>
        <td>${fmtUsd(l.volume_24h)}</td>
        <td>${fmtUsd(l.liquidity_usd)}</td>
        <td class="${fmtPctCls(l.price_change_m5)}">${fmtPct(l.price_change_m5)}</td>
        <td class="${fmtPctCls(l.price_change_h1)}">${fmtPct(l.price_change_h1)}</td>
        <td class="${fmtPctCls(l.price_change_h24)}">${fmtPct(l.price_change_h24)}</td>
        <td>${s.total_cycles ?? "—"}</td>
        <td class="${fmtPctCls(s.avg_up_pct)}">${fmtPct(s.avg_up_pct)}</td>
        <td>${fmtDur(s.avg_cycle_duration_s)}</td>
        <td>${phaseBadge(r.phase)}</td>
        <td class="neutral">${fmtDate(l.ts)}</td>
      </tr>`;
    }).join("");
    tb.querySelectorAll("tr.clickable").forEach(tr => tr.onclick = () => location.hash = "#/token/" + tr.dataset.mint);
    const pages = Math.max(1, Math.ceil(sum.total / sum.page_size));
    document.getElementById("pager").innerHTML = `Page ${sum.page} / ${pages} — ${sum.total} token(s) <button class="secondary small" id="pg-prev">‹</button><button class="secondary small" id="pg-next">›</button>`;
    document.getElementById("pg-prev").onclick = () => { if (dashState.page > 1) { dashState.page--; loadDashboard(); } };
    document.getElementById("pg-next").onclick = () => { if (dashState.page < pages) { dashState.page++; loadDashboard(); } };
    if (dashState.refresh) {
      api("/settings").then(s => {
        refreshTimer = setInterval(loadDashboard, Math.max(2, s.effective.refresh_interval_seconds || 15) * 1000);
      }).catch(() => { refreshTimer = setInterval(loadDashboard, 15000); });
    }
  } catch (e) {
    app.innerHTML = `<div class="error-box">Erreur de chargement: ${esc(e.message)}</div>`;
  }
}

async function viewToken(mint) {
  app.innerHTML = `<div class="loading">Chargement de la fiche…</div>`;
  try {
    const ov = await api("/tokens/" + mint + "/overview");
    const t = ov.token, l = ov.latest || {}, s = ov.stats || {}, a = ov.ath_atl || {};
    const logo = t.logo_url ? `<img src="${esc(t.logo_url)}" style="width:40px;height:40px;border-radius:50%">` : `<span class="placeholder" style="width:40px;height:40px;border-radius:50%;background:var(--bg-card-2);display:inline-flex;align-items:center;justify-content:center;font-weight:700">${esc((t.symbol||'?')[0])}</span>`;
    app.innerHTML = `
    <button class="secondary small" onclick="location.hash='#/dashboard'">← Dashboard</button>
    <div class="panel" style="margin-top:12px">
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        ${logo}
        <div>
          <h1 style="display:inline">${esc(t.symbol || "?")} <span class="neutral" style="font-size:14px">${esc(t.name || "")}</span></h1>
          ${starBtn(mint, ov.favorite)}
          <div class="mono" style="margin-top:4px">${esc(t.mint)} <button class="copy-btn" id="copy-mint">copier</button> <span class="chain-badge">SOLANA</span></div>
        </div>
        <div style="margin-left:auto" id="phase-box">${phaseBadge(ov.phase)}</div>
      </div>
      <div class="kv" style="margin-top:14px">
        <span class="k">Market Cap</span><span class="v">${fmtUsd(l.market_cap)} (max observé ${fmtUsd(t.max_market_cap)})</span>
        <span class="k">FDV</span><span class="v">${fmtUsd(l.fdv)}</span>
        <span class="k">Prix actuel</span><span class="v mono">${l.price_usd ? Number(l.price_usd).toExponential(6) + " $" : "—"}</span>
        <span class="k">Variations</span><span class="v"><span class="${fmtPctCls(l.price_change_m5)}">5m ${fmtPct(l.price_change_m5)}</span> · <span class="${fmtPctCls(l.price_change_h1)}">1h ${fmtPct(l.price_change_h1)}</span> · <span class="${fmtPctCls(l.price_change_h24)}">24h ${fmtPct(l.price_change_h24)}</span></span>
        <span class="k">Volume 24h</span><span class="v">${fmtUsd(l.volume_24h)}</span>
        <span class="k">Liquidité</span><span class="v">${fmtUsd(l.liquidity_usd)}</span>
        <span class="k">Transactions 24h</span><span class="v">${l.txns_buys ?? "—"} achats / ${l.txns_sells ?? "—"} ventes${l.buyers != null ? ` · ${l.buyers} acheteurs / ${l.sellers} vendeurs` : ""}</span>
        <span class="k">Création</span><span class="v">${fmtDate(t.created_at)} ${t.created_at_source ? "(" + esc(t.created_at_source) + ")" : ""}</span>
        <span class="k">1er franchissement ${fmtUsd(t.threshold_usd)}</span><span class="v">${fmtDate(t.first_crossed_threshold_at)}</span>
        <span class="k">Cycles détectés</span><span class="v">${ov.cycles_count} — hausse moy. <span class="${fmtPctCls(s.avg_up_pct)}">${fmtPct(s.avg_up_pct)}</span>, baisse moy. <span class="${fmtPctCls(s.avg_down_pct)}">${fmtPct(s.avg_down_pct)}</span>, durée moy. ${fmtDur(s.avg_cycle_duration_s)}</span>
      </div>
    </div>
    <div class="grid-2">
      <div class="panel">
        <h2 style="margin-top:0">ATH / ATL (historique collecté)</h2>
        <div class="kv">
          <span class="k">ATH</span><span class="v">${a.ath ? Number(a.ath).toExponential(6) + " $" : "—"} le ${fmtDate(a.ath_ts)}</span>
          <span class="k">ATL</span><span class="v">${a.atl ? Number(a.atl).toExponential(6) + " $" : "—"} le ${fmtDate(a.atl_ts)}</span>
          <span class="k">Prix vs ATH</span><span class="v ${fmtPctCls(a.vs_ath_pct)}">${fmtPct(a.vs_ath_pct)}</span>
          <span class="k">Prix vs ATL</span><span class="v ${fmtPctCls(a.vs_atl_pct)}">${fmtPct(a.vs_atl_pct)}</span>
        </div>
        <div class="subtitle" style="margin:10px 0 0">${esc(a.note || "")}</div>
      </div>
      <div class="panel">
        <h2 style="margin-top:0">Liquidité</h2>
        <div class="kv">
          <span class="k">Liquidité actuelle</span><span class="v">${fmtUsd(l.liquidity_usd)}</span>
          <span class="k">Tendance</span><span class="v">${esc(s.liquidity_trend || "—")}</span>
        </div>
        <div class="chart-box" style="margin-top:10px"><div id="liq-chart"></div></div>
      </div>
    </div>
    <div class="panel">
      <h2 style="margin-top:0">Graphique</h2>
      <div class="tf-bar" id="tf-bar">${["5m","15m","1h","4h","24h","7d","all"].map(x => `<button data-tf="${x}" class="${x === tokenState.tf ? "active" : ""}">${x === "all" ? "Tout" : x}</button>`).join("")}</div>
      <div class="chart-box"><div id="price-chart"></div></div>
      <div class="legend">
        <span><span class="dot" style="background:#2962ff"></span>Point bas confirmé</span>
        <span><span class="dot" style="background:#f0b90b"></span>Point haut confirmé</span>
        <span><span class="dot" style="background:#16c784"></span>Hausse ≥ seuil</span>
        <span><span class="dot" style="background:#ea3943"></span>Baisse ≥ seuil</span>
        <span><span class="dot" style="background:#7c5cff"></span>Cycles (bas → haut)</span>
      </div>
    </div>
    <div class="panel">
      <h2 style="margin-top:0">Historique des cycles (${ov.cycles_count})</h2>
      <div class="table-wrap"><table class="data"><thead><tr><th>#</th><th>Départ</th><th>Point bas</th><th>Point haut</th><th>Ampl. hausse</th><th>Ampl. baisse</th><th>Durée hausse</th><th>Durée baisse</th><th>Durée totale</th><th>Bas le</th><th>Haut le</th><th>Liquidité (bas/hot)</th></tr></thead><tbody id="cycles-body"></tbody></table></div>
    </div>
    <div class="panel">
      <h2 style="margin-top:0">Mouvements confirmés (≥ seuil)</h2>
      <div class="table-wrap"><table class="data"><thead><tr><th>Type</th><th>Amplitude</th><th>Départ</th><th>Arrivée</th><th>Début</th><th>Fin</th></tr></thead><tbody id="mov-body"></tbody></table></div>
    </div>`;
    document.getElementById("copy-mint").onclick = () => { navigator.clipboard.writeText(t.mint); toast("Adresse copiée"); };
    document.querySelectorAll("#tf-bar button").forEach(b => b.onclick = () => { tokenState.tf = b.dataset.tf; loadChart(mint); document.querySelectorAll("#tf-bar button").forEach(x => x.classList.toggle("active", x.dataset.tf === tokenState.tf)); });
    await loadChart(mint);
    const cycles = await api("/tokens/" + mint + "/cycles");
    document.getElementById("cycles-body").innerHTML = cycles.map(c => `<tr class="clickable" data-cycle="${c.id}">
      <td>${c.cycle_index}</td><td class="mono">${c.start_price ? Number(c.start_price).toExponential(4) : "—"}</td>
      <td class="mono">${c.min_price ? Number(c.min_price).toExponential(4) : "—"}</td><td class="mono">${c.max_price ? Number(c.max_price).toExponential(4) : "—"}</td>
      <td class="up">${fmtPct(c.up_amplitude_pct)}</td><td class="down">${fmtPct(c.down_amplitude_pct)}</td>
      <td>${fmtDur(c.up_duration_s)}</td><td>${fmtDur(c.down_duration_s)}</td><td>${fmtDur((c.up_duration_s||0)+(c.down_duration_s||0))}</td>
      <td class="neutral">${fmtDate(c.low_ts)}</td><td class="neutral">${fmtDate(c.high_ts)}</td>
      <td>${fmtUsd(c.liquidity_at_low)} / ${fmtUsd(c.liquidity_at_high)}</td></tr>`).join("") || `<tr><td colspan="12" class="neutral">Aucun cycle pour le moment.</td></tr>`;
    const movs = await api("/tokens/" + mint + "/movements?counted_only=true");
    document.getElementById("mov-body").innerHTML = movs.map(m => `<tr>
      <td class="${m.type === "up" ? "up" : "down"}">${m.type === "up" ? "Hausse" : "Baisse"}</td>
      <td class="${m.type === "up" ? "up" : "down"}">${fmtPct(m.amplitude_pct)}</td>
      <td class="mono">${Number(m.start_price).toExponential(4)}</td><td class="mono">${Number(m.end_price).toExponential(4)}</td>
      <td class="neutral">${fmtDate(m.start_ts)}</td><td class="neutral">${fmtDate(m.end_ts)}</td></tr>`).join("") || `<tr><td colspan="6" class="neutral">Aucun mouvement confirmé.</td></tr>`;
    loadLiqChart(mint);
  } catch (e) {
    app.innerHTML = `<div class="error-box">Erreur: ${esc(e.message)}</div><button class="secondary small" onclick="location.hash='#/dashboard'">← Dashboard</button>`;
  }
}

const tokenState = { tf: "all" };

async function loadChart(mint) {
  const data = await api(`/tokens/${mint}/chart?tf=${tokenState.tf}`);
  const el = document.getElementById("price-chart");
  if (!el) return;
  if (currentChart) { currentChart.remove(); currentChart = null; }
  const chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "#151a20" }, textColor: "#8b94a3" },
    grid: { vertLines: { color: "#1e2630" }, horzLines: { color: "#1e2630" } },
    rightPriceScale: { borderColor: "#262e3a" },
    timeScale: { borderColor: "#262e3a", timeVisible: true, secondsVisible: false },
    crosshair: { mode: 0 },
  });
  currentChart = chart;
  const series = chart.addCandlestickSeries({
    upColor: "#16c784", downColor: "#ea3943", wickUpColor: "#16c784", wickDownColor: "#ea3943", borderVisible: false,
  });
  currentSeries = series;
  series.setData(data.candles);
  const markers = [];
  for (const e of data.extremes) markers.push({ time: e.time, position: e.kind === "high" ? "aboveBar" : "belowBar", color: e.kind === "high" ? "#f0b90b" : "#2962ff", shape: e.kind === "high" ? "arrowDown" : "arrowUp", text: (e.kind === "high" ? "H" : "L") + " " + Number(e.price).toExponential(2) });
  for (const m of data.movements) markers.push({ time: m.time, position: m.type === "up" ? "belowBar" : "aboveBar", color: m.type === "up" ? "#16c784" : "#ea3943", shape: m.type === "up" ? "arrowUp" : "arrowDown", text: fmtPct(m.amplitude_pct) });
  for (const c of data.cycles) {
    if (c.low_time) markers.push({ time: c.low_time, position: "belowBar", color: "#7c5cff", shape: "circle", text: "C" + c.cycle_index });
    if (c.high_time) markers.push({ time: c.high_time, position: "aboveBar", color: "#7c5cff", shape: "circle", text: "C" + c.cycle_index });
  }
  if (selectedTrade && selectedTrade.mint === mint) {
    markers.push({ time: Math.floor(new Date(selectedTrade.entry_ts).getTime() / 1000), position: "belowBar", color: "#16c784", shape: "arrowUp", text: "ENTRÉE sim" });
    if (selectedTrade.exit_ts) markers.push({ time: Math.floor(new Date(selectedTrade.exit_ts).getTime() / 1000), position: "aboveBar", color: "#ea3943", shape: "arrowDown", text: "SORTIE sim" });
  }
  markers.sort((a, b) => a.time - b.time);
  series.setMarkers(markers);
  chart.timeScale().fitContent();
}

async function loadLiqChart(mint) {
  const data = await api("/tokens/" + mint + "/liquidity?limit=500");
  const el = document.getElementById("liq-chart");
  if (!el) return;
  el.innerHTML = "";
  const chart = LightweightCharts.createChart(el, { layout: { background: { color: "#151a20" }, textColor: "#8b94a3" }, grid: { vertLines: { color: "#1e2630" }, horzLines: { color: "#1e2630" } }, rightPriceScale: { borderColor: "#262e3a" }, timeScale: { borderColor: "#262e3a" } });
  const series = chart.addAreaSeries({ topColor: "rgba(124,92,255,.4)", bottomColor: "rgba(124,92,255,0)", lineColor: "#7c5cff", lineWidth: 2 });
  const pts = data.filter(e => e.liquidity_usd !== null).map(e => ({ time: Math.floor(new Date(e.ts).getTime() / 1000), value: e.liquidity_usd })).reverse();
  series.setData(pts);
  chart.timeScale().fitContent();
  setTimeout(() => chart.resize && el.clientWidth && chart.applyOptions({ width: el.clientWidth }), 50);
}

async function viewFavorites() {
  app.innerHTML = `<h1>Favoris</h1><div class="subtitle">Liste persistée côté serveur (base de données) — consultable même si le token ne passe plus temporairement les filtres</div>
  <div class="toolbar"><input id="fav-mint" placeholder="Mint address à ajouter…" style="min-width:320px"><button id="fav-add">Ajouter</button></div>
  <div class="table-wrap"><table class="data"><thead><tr><th></th><th>Token</th><th>Mint</th><th>Statut</th><th>Market Cap max</th><th>1er franchissement</th><th>Ajouté le</th><th></th></tr></thead><tbody id="fav-body"></tbody></table></div>`;
  document.getElementById("fav-add").onclick = async () => {
    const mint = document.getElementById("fav-mint").value.trim();
    if (!mint) return;
    try { await api("/favorites/" + mint, { method: "POST" }); toast("Ajouté aux favoris"); viewFavorites(); }
    catch (e) { toast("Erreur: " + e.message); }
  };
  try {
    const favs = await api("/favorites");
    document.getElementById("fav-body").innerHTML = favs.map(f => {
      const t = f.token || {};
      const logo = t.logo_url ? `<img src="${esc(t.logo_url)}" style="width:24px;height:24px;border-radius:50%">` : `<span class="placeholder">${esc((t.symbol||'?')[0])}</span>`;
      return `<tr class="clickable" data-mint="${esc(f.mint)}">
        <td>${starBtn(f.mint, true)}</td>
        <td><div class="token-cell">${logo}<div class="names"><span class="sym">${esc(t.symbol || "?")}</span><span class="nm">${esc(t.name || "")}</span></div></div></td>
        <td class="mono" title="${esc(f.mint)}">${shortMint(f.mint)}</td>
        <td>${esc(t.status || "watchlist")}</td>
        <td>${fmtUsd(t.max_market_cap)}</td>
        <td class="neutral">${fmtDate(t.first_crossed_threshold_at)}</td>
        <td class="neutral">${fmtDate(f.added_at)}</td>
        <td><button class="danger small" data-del="${esc(f.mint)}">Retirer</button></td></tr>`;
    }).join("") || `<tr><td colspan="8" class="neutral">Aucun favori. Ajoutez un mint ci-dessus ou cliquez sur ★ dans le dashboard.</td></tr>`;
    document.querySelectorAll("tr.clickable").forEach(tr => tr.onclick = () => location.hash = "#/token/" + tr.dataset.mint);
    document.querySelectorAll("[data-del]").forEach(b => b.onclick = async (ev) => { ev.stopPropagation(); await api("/favorites/" + b.dataset.del, { method: "DELETE" }); viewFavorites(); });
  } catch (e) { app.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

async function viewControl() {
  app.innerHTML = `<div class="loading">Chargement des paramètres…</div>`;
  try {
    const s = await api("/settings");
    const e = s.effective;
    app.innerHTML = `<h1>Centre de contrôle</h1>
    <div class="subtitle">Les modifications sont transmises au moteur via l'API et appliquées à la prochaine collecte — l'historique n'est jamais supprimé. Dernière modification : ${fmtDate(s.last_modified)}</div>
    <div class="panel"><div class="form-grid">
      <div class="form-section-title">Market Cap</div>
      <label>Market Cap minimale ($)<input id="c-mcap_min" type="number" value="${e.mcap_threshold_usd}"></label>
      <label>Market Cap maximale ($) (vide = illimité)<input id="c-mcap_max" type="number" value="${e.mcap_max_usd ?? ""}"></label>
      <div class="form-section-title">Variations (seuils de détection)</div>
      <label>Hausse minimale (%)<input id="c-up" type="number" step="0.1" value="${e.up_threshold_pct ?? e.variation_threshold_pct}"></label>
      <label>Baisse minimale (%)<input id="c-down" type="number" step="0.1" value="${e.down_threshold_pct ?? e.variation_threshold_pct}"></label>
      <label>Seuil général (%)<input id="c-var" type="number" step="0.1" value="${e.variation_threshold_pct}"></label>
      <label>Fenêtre de confirmation (observations)<input id="c-window" type="number" value="${e.confirmation_window}"></label>
      <label>Retracement de confirmation (%)<input id="c-retrace" type="number" step="0.1" value="${e.retracement_pct}"></label>
      <div class="form-section-title">Durée des cycles (unité : <select id="c-unit"><option value="1">secondes</option><option value="60">minutes</option><option value="3600">heures</option><option value="86400">jours</option></select>)</div>
      <label>Hausse durée min<input id="c-minup" type="number" value="${e.min_up_duration_s ?? ""}"></label>
      <label>Hausse durée max<input id="c-maxup" type="number" value="${e.max_up_duration_s ?? ""}"></label>
      <label>Baisse durée min<input id="c-mindown" type="number" value="${e.min_down_duration_s ?? ""}"></label>
      <label>Baisse durée max<input id="c-maxdown" type="number" value="${e.max_down_duration_s ?? ""}"></label>
      <label>Cycle durée min<input id="c-mincycle" type="number" value="${e.min_cycle_duration_s ?? ""}"></label>
      <label>Cycle durée max<input id="c-maxcycle" type="number" value="${e.max_cycle_duration_s ?? ""}"></label>
      <div class="form-section-title">Liquidité & volume</div>
      <label>Liquidité minimale filtre ($)<input id="c-minliq" type="number" value="${e.min_liquidity_usd}"></label>
      <label>Volume 24h minimum ($)<input id="c-minvol" type="number" value="${e.min_volume_24h_usd}"></label>
      <label>Alerte liquidité faible ($)<input id="c-liqlow" type="number" value="${e.liquidity_low_usd}"></label>
      <label>Baisse liquidité alerte (%)<input id="c-liqdecl" type="number" value="${e.liquidity_decline_pct}"></label>
      <label>Variation max liquidité autorisée (%) (vide = illimité)<input id="c-liqmax" type="number" value="${e.max_liquidity_change_pct ?? ""}"></label>
      <div class="form-section-title">Collecte & analyse</div>
      <label>Fréquence de collecte (s)<input id="c-collect" type="number" value="${e.collect_interval_seconds}"></label>
      <label>Fréquence d'analyse (s, 0 = avec collecte)<input id="c-analysis" type="number" value="${e.analysis_interval_seconds}"></label>
      <label>Fréquence d'actualisation UI (s)<input id="c-refresh" type="number" value="${e.refresh_interval_seconds}"></label>
      <label>Nb max de tokens surveillés<input id="c-maxtok" type="number" value="${e.max_tokens_watched}"></label>
      <label>Pages de découverte<input id="c-pages" type="number" value="${e.discovery_pages}"></label>
      <label>Tolérance cohérence sources (%)<input id="c-tol" type="number" value="${e.source_coherence_tolerance_pct}"></label>
    </div>
    <div style="margin-top:16px;display:flex;gap:10px">
      <button id="btn-save">Enregistrer et appliquer au moteur</button>
      <button class="secondary" id="btn-reset">Réinitialiser</button>
      <button class="secondary" id="btn-defaults">Valeurs par défaut</button>
    </div></div>`;
    document.getElementById("btn-save").onclick = async () => {
      const unit = Number(document.getElementById("c-unit").value);
      const num = (id) => { const v = document.getElementById(id).value; return v === "" ? null : Number(v); };
      const body = {
        mcap_threshold_usd: num("c-mcap_min"), mcap_max_usd: num("c-mcap_max"),
        up_threshold_pct: num("c-up"), down_threshold_pct: num("c-down"), variation_threshold_pct: num("c-var"),
        confirmation_window: num("c-window"), retracement_pct: num("c-retrace"),
        min_up_duration_s: num("c-minup") !== null ? num("c-minup") * unit : null,
        max_up_duration_s: num("c-maxup") !== null ? num("c-maxup") * unit : null,
        min_down_duration_s: num("c-mindown") !== null ? num("c-mindown") * unit : null,
        max_down_duration_s: num("c-maxdown") !== null ? num("c-maxdown") * unit : null,
        min_cycle_duration_s: num("c-mincycle") !== null ? num("c-mincycle") * unit : null,
        max_cycle_duration_s: num("c-maxcycle") !== null ? num("c-maxcycle") * unit : null,
        min_liquidity_usd: num("c-minliq"), min_volume_24h_usd: num("c-minvol"),
        liquidity_low_usd: num("c-liqlow"), liquidity_decline_pct: num("c-liqdecl"), max_liquidity_change_pct: num("c-liqmax"),
        collect_interval_seconds: num("c-collect"), analysis_interval_seconds: num("c-analysis"),
        refresh_interval_seconds: num("c-refresh"), max_tokens_watched: num("c-maxtok"),
        discovery_pages: num("c-pages"), source_coherence_tolerance_pct: num("c-tol"),
      };
      try { await api("/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); toast("Paramètres enregistrés et appliqués au moteur"); }
      catch (e) { toast("Erreur: " + e.message); }
    };
    document.getElementById("btn-reset").onclick = async () => { await api("/settings/reset", { method: "POST" }); toast("Surprises supprimées (valeurs .env)"); viewControl(); };
    document.getElementById("btn-defaults").onclick = async () => { await api("/settings/reset", { method: "POST" }); toast("Valeurs par défaut restaurées"); viewControl(); };
  } catch (e) { app.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

const NOTIF_ICON = { new_token: "🆕", new_cycle: "🔁", movement_up: "📈", movement_down: "📉", liquidity_alert: "💧", data_unavailable: "⚠️", connection_error: "🔌" };
async function viewNotifications() {
  app.innerHTML = `<h1>Notifications</h1><div class="subtitle">Événements du moteur — <span id="unread-count"></span> non lue(s)</div>
  <div class="toolbar"><button id="mark-all" class="secondary small">Tout marquer comme lu</button><button id="reload" class="secondary small">Rafraîchir</button></div>
  <div class="panel" id="notif-list" style="padding:0"></div>`;
  document.getElementById("mark-all").onclick = async () => { await api("/notifications/read-all", { method: "POST" }); viewNotifications(); setStatus(); };
  document.getElementById("reload").onclick = () => viewNotifications();
  try {
    const data = await api("/notifications?limit=300");
    document.getElementById("unread-count").textContent = data.unread;
    document.getElementById("notif-list").innerHTML = data.items.map(n => `<div class="notif ${n.read ? "" : "unread"}">
      <span class="icon">${NOTIF_ICON[n.type] || "ℹ️"}</span>
      <div class="body"><div class="msg">${esc(n.message)}</div>
      <div class="meta"><span class="notif-type">${esc(n.type)}</span> ${n.mint ? `<a href="#/token/${esc(n.mint)}" class="mono">${shortMint(n.mint)}</a> · ` : ""}${fmtDate(n.ts)}</div></div>
      ${n.read ? "" : `<button class="secondary small" data-read="${n.id}">lu</button>`}
    </div>`).join("") || `<div class="notif"><div class="body"><div class="msg neutral">Aucune notification.</div></div></div>`;
    document.querySelectorAll("[data-read]").forEach(b => b.onclick = async () => { await api("/notifications/" + b.dataset.read + "/read", { method: "POST" }); viewNotifications(); setStatus(); });
  } catch (e) { app.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

async function viewBacktest() {
  app.innerHTML = `<h1>Backtesting — simulations virtuelles</h1>
  <div class="subtitle">Stratégies testées uniquement sur les données réellement collectées, sans aucune donnée future (pas d'achat exact au point bas). Résultats virtuels, distincts des performances réelles.</div>
  <div class="grid-2">
    <div class="panel">
      <h2 style="margin-top:0">Nouvelle simulation</h2>
      <div class="form-grid">
        <label>Mint du token<input id="b-mint" placeholder="Mint address" style="min-width:280px"></label>
        <label>Capital initial (€)<input id="b-capital" type="number" value="100"></label>
        <label>Objectif de gain (%)<input id="b-tp" type="number" step="1" value="30"></label>
        <label>Seuil de perte (%)<input id="b-sl" type="number" step="1" value="20"></label>
        <label>Frais par transaction (%)<input id="b-fees" type="number" step="0.1" value="0.5"></label>
        <label>Slippage estimé (%)<input id="b-slip" type="number" step="0.1" value="1"></label>
        <label>Début de période<input id="b-from" type="datetime-local"></label>
        <label>Fin de période<input id="b-to" type="datetime-local"></label>
        <label>Nb max de cycles<input id="b-maxc" type="number" value=""></label>
        <label>Mode d'entrée<select id="b-mode"><option value="low_confirmation">Après confirmation d'un point bas</option><option value="up_movement">Au début d'une hausse confirmée</option></select></label>
      </div>
      <div style="margin-top:14px"><button id="b-run">Lancer la simulation</button></div>
      <div id="b-result"></div>
    </div>
    <div class="panel">
      <h2 style="margin-top:0">Comparer des stratégies</h2>
      <div class="form-grid">
        <label>Mint<input id="c-mint2" placeholder="Mint address"></label>
        <label>Objectifs de gain (%) — un par ligne (ex: 20, 30, 40)<textarea id="c-tps" rows="3">20
30
40</textarea></label>
      </div>
      <div style="margin-top:14px"><button id="c-run">Comparer</button></div>
      <div id="c-result"></div>
    </div>
  </div>
  <div class="panel">
    <h2 style="margin-top:0">Historique des simulations</h2>
    <div class="toolbar"><input id="h-mint" placeholder="Filtrer par mint (optionnel)" style="min-width:280px"><button id="h-load" class="secondary small">Charger</button></div>
    <div class="table-wrap"><table class="data"><thead><tr><th>ID</th><th>Token</th><th>Date</th><th>Capital</th><th>Objectif</th><th>Trades</th><th>Taux de réussite</th><th>Résultat net</th><th></th></tr></thead><tbody id="h-body"></tbody></table></div>
    <div id="h-detail"></div>
  </div>`;
  document.getElementById("b-run").onclick = async () => {
    const body = {
      mint: document.getElementById("b-mint").value.trim(),
      capital: Number(document.getElementById("b-capital").value),
      take_profit_pct: Number(document.getElementById("b-tp").value),
      stop_loss_pct: Number(document.getElementById("b-sl").value),
      fees_pct: Number(document.getElementById("b-fees").value),
      slippage_pct: Number(document.getElementById("b-slip").value),
      max_cycles: document.getElementById("b-maxc").value ? Number(document.getElementById("b-maxc").value) : null,
      entry_mode: document.getElementById("b-mode").value,
    };
    const from = document.getElementById("b-from").value, to = document.getElementById("b-to").value;
    if (from) body.time_from = new Date(from).toISOString();
    if (to) body.time_to = new Date(to).toISOString();
    const el = document.getElementById("b-result");
    el.innerHTML = `<div class="loading">Simulation en cours…</div>`;
    try {
      const r = await api("/backtest/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      renderBacktestResult(r, el);
    } catch (e) { el.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
  };
  document.getElementById("c-run").onclick = async () => {
    const tps = document.getElementById("c-tps").value.split("\n").map(x => parseFloat(x.trim())).filter(x => !isNaN(x));
    const el = document.getElementById("c-result");
    el.innerHTML = `<div class="loading">Comparaison en cours…</div>`;
    try {
      const r = await api("/backtest/compare", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mint: document.getElementById("c-mint2").value.trim(), configs: tps.map(tp => ({ capital: 100, take_profit_pct: tp, stop_loss_pct: 20, fees_pct: 0.5, slippage_pct: 1, entry_mode: "low_confirmation" })) }) });
      el.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Stratégie</th><th>Trades</th><th>Gagnantes</th><th>Perdantes</th><th>Taux réussite</th><th>Gain moyen</th><th>Perte moyenne</th><th>Résultat net total (€)</th><th>Frais totaux</th></tr></thead><tbody>` +
        r.results.map((x, i) => x.error ? `<tr><td colspan="9" class="down">${esc(x.error)}</td></tr>` : `<tr><td>Stratégie ${String.fromCharCode(65 + i)} — objectif +${x.config.take_profit_pct}%</td><td>${x.summary.total_trades}</td><td class="up">${x.summary.winning_trades}</td><td class="down">${x.summary.losing_trades}</td><td>${x.summary.win_rate_pct !== null ? x.summary.win_rate_pct.toFixed(1) + " %" : "—"}</td><td class="up">${x.summary.avg_win_pct !== null ? fmtPct(x.summary.avg_win_pct) : "—"}</td><td class="down">${x.summary.avg_loss_pct !== null ? fmtPct(x.summary.avg_loss_pct) : "—"}</td><td class="${x.summary.net_total_amount >= 0 ? "up" : "down"}">${x.summary.net_total_amount.toFixed(2)} €</td><td>${x.summary.total_fees_usd.toFixed(2)} €</td></tr>`).join("") +
        `</tbody></table></div>`;
    } catch (e) { el.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
  };
  document.getElementById("h-load").onclick = () => loadSimHistory();
  await loadSimHistory();
}

function renderBacktestResult(r, el) {
  const s = r.summary;
  if (r.insufficient_data) {
    el.innerHTML = `<div class="error-box" style="margin-top:14px">Données insuffisantes pour simuler : ${esc(r.note || "")}</div>`;
    return;
  }
  el.innerHTML = `<div class="cards" style="margin-top:14px">${[
    ["Simulations (trades)", s.total_trades], ["Positives", s.winning_trades], ["Négatives", s.losing_trades],
    ["Taux de réussite", s.win_rate_pct !== null ? s.win_rate_pct.toFixed(1) + " %" : "—"],
    ["Gain moyen", s.avg_win_pct !== null ? fmtPct(s.avg_win_pct) : "—"], ["Perte moyenne", s.avg_loss_pct !== null ? fmtPct(s.avg_loss_pct) : "—"],
    ["Résultat net total", (s.net_total_amount >= 0 ? "+" : "") + s.net_total_amount.toFixed(2) + " €"],
    ["Net moyen / opération", s.net_avg_per_trade !== null ? s.net_avg_per_trade.toFixed(2) + " €" : "—"],
    ["Meilleure opération", s.best_trade_pct !== null ? fmtPct(s.best_trade_pct) : "—"], ["Pire opération", s.worst_trade_pct !== null ? fmtPct(s.worst_trade_pct) : "—"],
    ["Frais totaux estimés", s.total_fees_usd.toFixed(2) + " €"], ["Slippage total estimé", s.total_slippage_usd.toFixed(2) + " €"],
    ["Capital final", s.final_capital.toFixed(2) + " €"],
  ].map(([l, v]) => `<div class="card"><div class="label">${l}</div><div class="value small">${v}</div></div>`).join("")}</div>
  <div class="subtitle">Période analysée : ${fmtDate(s.period_from)} → ${fmtDate(s.period_to)} · ${s.observations_used} observations · Simulation #${r.simulation_id} (virtuelle)</div>
  <div class="table-wrap"><table class="data"><thead><tr><th>Entrée</th><th>Prix entrée</th><th>Sortie</th><th>Prix sortie</th><th>Var. brute</th><th>Frais</th><th>Slippage</th><th>Résultat net</th><th>Statut</th><th></th></tr></thead><tbody>
  ${r.trades.map(t => `<tr><td class="neutral">${fmtDate(t.entry_ts)}</td><td class="mono">${Number(t.entry_price).toExponential(4)}</td><td class="neutral">${t.exit_ts ? fmtDate(t.exit_ts) : "—"}</td><td class="mono">${t.exit_price ? Number(t.exit_price).toExponential(4) : "—"}</td><td class="${fmtPctCls(t.gross_pct)}">${fmtPct(t.gross_pct)}</td><td>${t.fees_usd.toFixed(2)} €</td><td>${t.slippage_usd.toFixed(2)} €</td><td class="${t.net_amount >= 0 ? "up" : "down"}">${t.net_amount.toFixed(2)} € (${fmtPct(t.net_pct)})</td><td>${esc(t.status)}</td><td><button class="secondary small" data-trade='${JSON.stringify({ mint: r.config.mint, entry_ts: t.entry_ts, exit_ts: t.exit_ts })}'>Voir sur le graphique</button></td></tr>`).join("")}
  </tbody></table></div>`;
  el.querySelectorAll("[data-trade]").forEach(b => b.onclick = () => {
    selectedTrade = JSON.parse(b.dataset.trade);
    location.hash = "#/token/" + selectedTrade.mint;
    toast("Simulation mise en évidence sur le graphique (marqueurs ENTRÉE/SORTIE)");
  });
}

async function loadSimHistory() {
  const mint = document.getElementById("h-mint")?.value.trim();
  try {
    const sims = await api("/backtest/simulations?limit=100" + (mint ? "&mint=" + mint : ""));
    const body = document.getElementById("h-body");
    if (!body) return;
    body.innerHTML = sims.map(s => `<tr class="clickable" data-sim="${s.id}">
      <td>${s.id}</td><td class="mono" title="${esc(s.mint)}">${shortMint(s.mint)}</td><td class="neutral">${fmtDate(s.created_at)}</td>
      <td>${s.config.capital} €</td><td>+${s.config.take_profit_pct}%</td>
      <td>${s.summary ? s.summary.total_trades : "—"}</td>
      <td>${s.summary && s.summary.win_rate_pct !== null ? s.summary.win_rate_pct.toFixed(1) + " %" : "—"}</td>
      <td class="${s.summary && s.summary.net_total_amount >= 0 ? "up" : "down"}">${s.summary ? s.summary.net_total_amount.toFixed(2) + " €" : (s.insufficient_data ? "données insuffisantes" : "—")}</td>
      <td><button class="secondary small" data-sim="${s.id}">Détail</button></td></tr>`).join("") || `<tr><td colspan="9" class="neutral">Aucune simulation enregistrée.</td></tr>`;
    body.querySelectorAll("[data-sim]").forEach(b => b.onclick = async () => {
      const d = await api("/backtest/simulations/" + b.dataset.sim);
      const el = document.getElementById("h-detail");
      const s = JSON.parse(d.simulation.results_json).summary;
      el.innerHTML = `<div class="panel" style="margin-top:14px"><h2 style="margin-top:0">Détail simulation #${d.simulation.id}</h2>
      <div class="subtitle">${s ? `Trades ${s.total_trades} · réussite ${s.win_rate_pct?.toFixed(1)} % · net ${s.net_total_amount.toFixed(2)} €` : esc(d.simulation.note || "")}</div>
      <div class="table-wrap"><table class="data"><thead><tr><th>Entrée</th><th>Prix</th><th>Sortie</th><th>Prix</th><th>Net</th><th>Statut</th><th></th></tr></thead><tbody>
      ${d.trades.map(t => `<tr><td class="neutral">${fmtDate(t.entry_ts)}</td><td class="mono">${Number(t.entry_price).toExponential(4)}</td><td class="neutral">${t.exit_ts ? fmtDate(t.exit_ts) : "—"}</td><td class="mono">${t.exit_price ? Number(t.exit_price).toExponential(4) : "—"}</td><td class="${t.net_amount >= 0 ? "up" : "down"}">${t.net_amount.toFixed(2)} €</td><td>${esc(t.status)}</td><td><button class="secondary small" data-trade='${JSON.stringify({ mint: d.simulation.mint, entry_ts: t.entry_ts, exit_ts: t.exit_ts })}'>Graphique</button></td></tr>`).join("")}
      </tbody></table></div></div>`;
      el.querySelectorAll("[data-trade]").forEach(x => x.onclick = () => { selectedTrade = JSON.parse(x.dataset.trade); location.hash = "#/token/" + selectedTrade.mint; });
    });
  } catch (e) { const b = document.getElementById("h-body"); if (b) b.innerHTML = `<tr><td colspan="9" class="down">${esc(e.message)}</td></tr>`; }
}

async function route() {
  clearInterval(refreshTimer);
  const hash = location.hash || "#/dashboard";
  const parts = hash.replace(/^#\//, "").split("/");
  document.querySelectorAll(".nav a").forEach(a => a.classList.toggle("active", a.dataset.route === parts[0]));
  try {
    if (parts[0] === "dashboard" || parts[0] === "") await viewDashboard();
    else if (parts[0] === "token" && parts[1]) await viewToken(parts[1]);
    else if (parts[0] === "favorites") await viewFavorites();
    else if (parts[0] === "control") await viewControl();
    else if (parts[0] === "notifications") await viewNotifications();
    else if (parts[0] === "backtest") await viewBacktest();
    else await viewDashboard();
  } catch (e) {
    app.innerHTML = `<div class="error-box">Erreur: ${esc(e.message)}</div>`;
  }
  setStatus();
}

window.addEventListener("hashchange", route);
route();
setInterval(setStatus, 30000);
