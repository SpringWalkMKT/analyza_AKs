/* Dashboard reads precomputed public/meta.json (merged_dataset + analysis)
   Filtering + ranking is done client-side from merged_dataset reviews.
   Themes + representative quotes are taken from analysis.themes_by_firm.
*/

const META_URL = "./meta.json";

const els = {
  kpiFirms: document.getElementById("kpiFirms"),
  kpiReviews: document.getElementById("kpiReviews"),
  kpiWithRating: document.getElementById("kpiWithRating"),
  kpiWithText: document.getElementById("kpiWithText"),
  firmsTbody: document.getElementById("firmsTbody"),
  searchFirm: document.getElementById("searchFirm"),
  platformFilter: document.getElementById("platformFilter"),
  rankMode: document.getElementById("rankMode"),
  excludeEnforcement: document.getElementById("excludeEnforcement"),
  minN: document.getElementById("minN"),
  chartNote: document.getElementById("chartNote"),

  dlg: document.getElementById("firmDialog"),
  dlgTitle: document.getElementById("dlgTitle"),
  dlgMeta: document.getElementById("dlgMeta"),
  dlgPosThemes: document.getElementById("dlgPosThemes"),
  dlgNegThemes: document.getElementById("dlgNegThemes"),
  dlgPosQuotes: document.getElementById("dlgPosQuotes"),
  dlgNegQuotes: document.getElementById("dlgNegQuotes"),
  dlgClose: document.getElementById("dlgClose"),
};

let state = {
  meta: null,
  firmsFlat: [],
  themesByFirm: new Map(),
  charts: { top: null, sentiment: null, posThemes: null, negThemes: null }
};

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}

function normText(s) { return String(s || "").trim().replace(/\s+/g, " ").toLowerCase(); }

function ratingTo5(r) {
  if (typeof r.rating_value !== "number") return null;
  if (typeof r.rating_scale !== "number" || !r.rating_scale) return null;
  return (r.rating_value / r.rating_scale) * 5;
}

// Rule-based theme classifier (for filtering out enforcement/debt/mass mail)
const ENFORCEMENT_KWS = [
  "dluh","vymáh","vymáhat","exekuc","pojist","předžalob","automati","picrights","copyright","mass","threat","zastraš"
];
function isEnforcementReview(text) {
  const t = normText(text);
  if (!t) return false;
  return ENFORCEMENT_KWS.some(k => t.includes(k));
}

function flattenFirms(mergedDataset) {
  const out = [];
  for (const f of (mergedDataset.firms || [])) {
    const reviews = [];
    const platforms = new Set();
    const cities = new Set();

    for (const o of (f.offices || [])) {
      if (o.city) cities.add(o.city);
      for (const r of (o.reviews || [])) {
        reviews.push(r);
        if (r.platform) platforms.add(r.platform);
      }
    }

    out.push({
      firm_id: f.firm_id,
      firm_name: f.firm_name,
      website: f.website || null,
      cities: [...cities],
      platforms: [...platforms],
      reviews,
    });
  }
  return out;
}

function computeStats(firm, { platform, excludeEnforcement }) {
  const reviews = firm.reviews.filter(r => {
    if (platform !== "ALL" && r.platform !== platform) return false;
    if (excludeEnforcement && isEnforcementReview(r.review_text || "")) return false;
    return true;
  });

  const ratings = reviews.map(ratingTo5).filter(v => v != null);
  const sentiments = reviews.map(r => (typeof r.sentiment_score === "number" ? r.sentiment_score : null)).filter(v => v != null);

  return {
    reviews_n: reviews.length,
    ratings_n: ratings.length,
    avg_rating_5: ratings.length ? ratings.reduce((a,b)=>a+b,0)/ratings.length : null,
    scored_n: sentiments.length,
    avg_sentiment: sentiments.length ? sentiments.reduce((a,b)=>a+b,0)/sentiments.length : null
  };
}

function renderKPIs({ firms_n, reviews_n, with_rating_n, with_text_n }) {
  els.kpiFirms.textContent = String(firms_n);
  els.kpiReviews.textContent = String(reviews_n);
  els.kpiWithRating.textContent = String(with_rating_n);
  els.kpiWithText.textContent = String(with_text_n);
}

function updateChart(id, oldChart, config) {
  const ctx = document.getElementById(id);
  if (oldChart) oldChart.destroy();
  return new Chart(ctx, config);
}

function applyFilters() {
  const q = normText(els.searchFirm.value);
  const platform = els.platformFilter.value;
  const rankMode = els.rankMode.value;
  const excludeEnforcement = els.excludeEnforcement.checked;
  const minN = Number(els.minN.value);

  const firms = [];
  let reviewsTotal = 0, withRating = 0, withText = 0;

  for (const f of state.firmsFlat) {
    if (q && !normText(f.firm_name || "").includes(q)) continue;

    const stats = computeStats(f, { platform, excludeEnforcement });
    reviewsTotal += stats.reviews_n;

    // KPI counters at review level
    for (const r of f.reviews) {
      if (platform !== "ALL" && r.platform !== platform) continue;
      if (excludeEnforcement && isEnforcementReview(r.review_text || "")) continue;
      if (ratingTo5(r) != null) withRating += 1;
      if ((r.review_text || "").trim()) withText += 1;
    }

    firms.push({ ...f, ...stats });
  }

  renderKPIs({
    firms_n: firms.length,
    reviews_n: reviewsTotal,
    with_rating_n: withRating,
    with_text_n: withText
  });

  // table
  firms.sort((a,b)=> (b.reviews_n - a.reviews_n) || String(a.firm_name||"").localeCompare(String(b.firm_name||"")));
  renderTable(firms);

  // top chart
  renderTopChart(firms, rankMode, minN);

  // sentiment distribution chart from filtered reviews
  renderSentimentChart(firms, { platform, excludeEnforcement });

  // themes charts from precomputed analysis (overall)
  renderThemeCharts();
}

function renderTable(firms) {
  els.firmsTbody.innerHTML = "";
  for (const f of firms) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(f.firm_name || "")}</td>
      <td>${f.reviews_n}</td>
      <td>${f.ratings_n}</td>
      <td>${f.avg_rating_5 == null ? "—" : f.avg_rating_5.toFixed(2)}</td>
      <td>${f.scored_n}</td>
      <td>${f.avg_sentiment == null ? "—" : f.avg_sentiment.toFixed(2)}</td>
      <td>${escapeHtml((f.platforms || []).join(", "))}</td>
    `;
    tr.addEventListener("click", () => openFirmDialog(f));
    els.firmsTbody.appendChild(tr);
  }
}

function renderTopChart(firms, mode, minN) {
  let scored = [];
  if (mode === "rating") {
    scored = firms.filter(f => f.avg_rating_5 != null && f.ratings_n >= minN)
      .sort((a,b)=> (b.avg_rating_5 - a.avg_rating_5) || (b.ratings_n - a.ratings_n))
      .slice(0, 15);
    els.chartNote.textContent = scored.length
      ? `Zobrazeno top 15 dle avg rating (min n=${minN}).`
      : `Žádné firmy nesplňují min n=${minN} pro rating ve filtru.`;
    state.charts.top = updateChart("chartTopFirms", state.charts.top, {
      type: "bar",
      data: { labels: scored.map(x=>x.firm_name), datasets: [{ label:"Avg rating", data: scored.map(x=>x.avg_rating_5) }] },
      options: { responsive:true, plugins:{ legend:{ display:false } } }
    });
  } else {
    scored = firms.filter(f => f.avg_sentiment != null && f.scored_n >= minN)
      .sort((a,b)=> (b.avg_sentiment - a.avg_sentiment) || (b.scored_n - a.scored_n))
      .slice(0, 15);
    els.chartNote.textContent = scored.length
      ? `Zobrazeno top 15 dle avg sentiment (min n=${minN}).`
      : `Žádné firmy nesplňují min n=${minN} pro sentiment ve filtru.`;
    state.charts.top = updateChart("chartTopFirms", state.charts.top, {
      type: "bar",
      data: { labels: scored.map(x=>x.firm_name), datasets: [{ label:"Avg sentiment", data: scored.map(x=>x.avg_sentiment) }] },
      options: { responsive:true, plugins:{ legend:{ display:false } } }
    });
  }
}

function renderSentimentChart(firms, { platform, excludeEnforcement }) {
  const counts = { positive:0, neutral:0, negative:0, mixed:0, unknown:0 };
  for (const f of firms) {
    for (const r of f.reviews) {
      if (platform !== "ALL" && r.platform !== platform) continue;
      if (excludeEnforcement && isEnforcementReview(r.review_text || "")) continue;
      const k = (r.sentiment_label in counts) ? r.sentiment_label : "unknown";
      counts[k] += 1;
    }
  }
  const labels = Object.keys(counts);
  const data = labels.map(k=>counts[k]);

  state.charts.sentiment = updateChart("chartSentiment", state.charts.sentiment, {
    type: "doughnut",
    data: { labels, datasets: [{ data }] },
    options: { responsive:true, plugins:{ legend:{ position:"bottom" } } }
  });
}

function renderThemeCharts() {
  const pos = (state.meta.analysis.themes_overall.top_positive_categories || []).slice(0, 10);
  const neg = (state.meta.analysis.themes_overall.top_negative_categories || []).slice(0, 10);

  state.charts.posThemes = updateChart("chartPosThemes", state.charts.posThemes, {
    type: "bar",
    data: { labels: pos.map(x=>x.category), datasets:[{ label:"Count", data: pos.map(x=>x.count) }] },
    options: { responsive:true, plugins:{ legend:{ display:false } } }
  });

  state.charts.negThemes = updateChart("chartNegThemes", state.charts.negThemes, {
    type: "bar",
    data: { labels: neg.map(x=>x.category), datasets:[{ label:"Count", data: neg.map(x=>x.count) }] },
    options: { responsive:true, plugins:{ legend:{ display:false } } }
  });
}

function renderThemeList(ul, items) {
  ul.innerHTML = "";
  for (const it of items || []) {
    const li = document.createElement("li");
    li.textContent = `${it.category} (${it.count})`;
    ul.appendChild(li);
  }
  if (!items || !items.length) {
    const li = document.createElement("li");
    li.textContent = "—";
    ul.appendChild(li);
  }
}

function renderQuoteList(ul, quotes) {
  ul.innerHTML = "";
  for (const q of (quotes || [])) {
    const li = document.createElement("li");
    li.textContent = q;
    ul.appendChild(li);
  }
  if (!quotes || !quotes.length) {
    const li = document.createElement("li");
    li.textContent = "—";
    ul.appendChild(li);
  }
}

function openFirmDialog(firm) {
  els.dlgTitle.textContent = firm.firm_name || firm.firm_id;
  els.dlgMeta.textContent = `reviews=${firm.reviews_n}, ratings_n=${firm.ratings_n}, avg_rating=${firm.avg_rating_5==null?"—":firm.avg_rating_5.toFixed(2)}, avg_sent=${firm.avg_sentiment==null?"—":firm.avg_sentiment.toFixed(2)}`;

  const themes = state.themesByFirm.get(firm.firm_id) || null;
  renderThemeList(els.dlgPosThemes, themes?.top_positive_categories);
  renderThemeList(els.dlgNegThemes, themes?.top_negative_categories);
  renderQuoteList(els.dlgPosQuotes, themes?.representative_quotes_positive);
  renderQuoteList(els.dlgNegQuotes, themes?.representative_quotes_negative);

  els.dlg.showModal();
}

async function loadMeta() {
  const r = await fetch(META_URL, { cache:"no-store" });
  if (!r.ok) throw new Error(`Failed to load ${META_URL}: ${r.status}`);
  return r.json();
}

async function init() {
  state.meta = await loadMeta();

  state.firmsFlat = flattenFirms(state.meta.merged_dataset);

  // build themes map
  const arr = state.meta.analysis.themes_by_firm || [];
  for (const x of arr) state.themesByFirm.set(x.firm_id, x);

  els.searchFirm.addEventListener("input", applyFilters);
  els.platformFilter.addEventListener("change", applyFilters);
  els.rankMode.addEventListener("change", applyFilters);
  els.excludeEnforcement.addEventListener("change", applyFilters);
  els.minN.addEventListener("change", applyFilters);

  els.dlgClose.addEventListener("click", () => els.dlg.close());

  applyFilters();
}

init().catch(err => {
  console.error(err);
  document.body.innerHTML = `<pre style="padding:16px;color:#fff;">${escapeHtml(String(err.stack || err))}</pre>`;
});
