// Chart builders ported from the Observable Framework dashboard (src/index.md).
// Each function builds a DOM node from the aggregate data and returns it so the
// React wrapper can mount it into a ref'd container. Logic mirrors the original
// Plot/d3 specs; only the data source changed (live aggregate endpoint instead
// of static FileAttachment loaders).
import * as Plot from "@observablehq/plot";
import * as d3 from "d3";
import type { AggregateData, VizConcept } from "../../lib/api";

export const catColors: Record<string, string> = {
  "DISEASE CONCEPTS": "#4472C4",
  "INDIVIDUAL IMPACTS": "#ED7D31",
  "CAREGIVER IMPACTS": "#70AD47",
  "MODIFYING FACTORS": "#FFC000",
  "MEDICAL INTERVENTIONS": "#9966CC",
};
export const catOrder = [
  "DISEASE CONCEPTS", "INDIVIDUAL IMPACTS", "CAREGIVER IMPACTS",
  "MODIFYING FACTORS", "MEDICAL INTERVENTIONS",
];

const catLabel = (cat: string) =>
  cat.charAt(0) + cat.slice(1).toLowerCase().replace(/_/g, " ");
const trunc = (s: string, n: number) =>
  s && s.length > n ? s.slice(0, n) + "…" : s;
const esc = (s: unknown) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// A "model" derived from the aggregate payload, shared by all charts. Mirrors
// the reactive blocks at the top of index.md.
export interface VizModel {
  nInterviews: number;
  caregivers: AggregateData["caregivers"];
  caregiverSets: Set<string>[];
  codebook: Map<string, VizConcept>;
  quotesByCode: Map<string, Array<{ quote: string; caregiver: string; age: string | null }>>;
  conceptCounts: Map<string, number>;
  allConcepts: Array<VizConcept & { id: string; cnt: number }>;
  cooc: (a: string, b: string) => number;
}

export function buildModel(data: AggregateData): VizModel {
  const caregivers = data.caregivers;
  const codebook = new Map(data.concept_frequency.map((c) => [String(c.code_id), c]));
  const quotesByCode = new Map(Object.entries(data.quotes_by_concept));

  const caregiverSets = caregivers.map((cg) => new Set(cg.expected));
  const conceptCounts = new Map<string, number>();
  for (const s of caregiverSets)
    for (const id of s) conceptCounts.set(id, (conceptCounts.get(id) || 0) + 1);

  const cooc = (a: string, b: string) =>
    caregiverSets.filter((s) => s.has(a) && s.has(b)).length;

  const allConcepts = [...conceptCounts.entries()]
    .filter(([id, cnt]) => cnt >= 1 && codebook.has(id) && codebook.get(id)!.category !== "DEMOGRAPHICS")
    .map(([id, cnt]) => ({ id, cnt, ...(codebook.get(id) as VizConcept) }))
    .sort((a, b) => {
      const ci = catOrder.indexOf(a.category) - catOrder.indexOf(b.category);
      return ci !== 0 ? ci : b.cnt - a.cnt;
    });

  return {
    nInterviews: data.n_interviews,
    caregivers,
    caregiverSets,
    codebook,
    quotesByCode,
    conceptCounts,
    allConcepts,
    cooc,
  };
}

// ── Shared floating tooltip ──────────────────────────────────────────────────
function axisTooltip(): HTMLElement {
  let el = document.getElementById("_obs_axis_tt");
  if (!el) {
    el = document.createElement("div");
    el.id = "_obs_axis_tt";
    el.style.cssText =
      "position:fixed;background:#f5f5f5;color:#1a1a1a;padding:3px 7px;border-radius:3px;font-size:11px;font-family:Inter,sans-serif;pointer-events:none;opacity:0;transition:opacity 0.08s;z-index:9999;max-width:320px;white-space:normal;line-height:1.4;border:1px solid #ccc;box-shadow:0 1px 4px rgba(0,0,0,0.15);";
    document.body.appendChild(el);
  }
  return el;
}

function attachAxisTooltips(svgEl: Element, nameMap: Map<string, string>) {
  const tt = axisTooltip();
  const hide = () => { tt.style.opacity = "0"; };
  svgEl.querySelectorAll("text").forEach((el) => {
    const t = [...el.childNodes]
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent).join("").trim();
    if (!t) return;
    const titleChild = el.querySelector(":scope > title");
    const full = titleChild?.textContent?.trim() || nameMap.get(t);
    if (!full || full === t) return;
    el.setAttribute("pointer-events", "all");
    (el as SVGElement).style.cursor = "help";
    el.addEventListener("mouseover", (e: Event) => {
      const me = e as MouseEvent;
      me.stopPropagation();
      tt.innerHTML = full;
      tt.style.opacity = "1";
      tt.style.left = `${me.clientX + 14}px`;
      tt.style.top = `${me.clientY - 36}px`;
    });
    el.addEventListener("mousemove", (e: Event) => {
      const me = e as MouseEvent;
      tt.style.left = `${me.clientX + 14}px`;
      tt.style.top = `${me.clientY - 36}px`;
    });
    el.addEventListener("mouseout", hide);
  });
}

// ── Chart 1: Concept Frequency by Category (clickable bars -> quotes panel) ──
export function conceptFrequencyChart(model: VizModel, quotesPanel: HTMLElement): HTMLElement {
  const { allConcepts, codebook, quotesByCode, nInterviews } = model;
  const N = nInterviews;
  const ROW_H = 20;
  // "coded in >= ~half" cutoff scaled to interview count (orig hardcoded 6 of 12).
  const minCnt = Math.max(1, Math.round(N / 2));
  const bcConceptRows = allConcepts.filter((r) => r.cnt >= minCnt);

  const tt = axisTooltip();

  function showQuotesForConcept(row: VizConcept & { id: string; cnt: number }, catColor: string) {
    const quotes = quotesByCode.get(String(row.id)) || [];
    quotesPanel.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 18px;background:${catColor}18;border-bottom:1px solid #e0e0e0;">
        <div>
          <span style="font-size:13px;font-weight:700;color:#1a1a1a;">${esc(row.name)}</span>
          <span style="font-size:11px;color:#888;margin-left:10px;">${quotes.length} quote${quotes.length !== 1 ? "s" : ""} · ${row.cnt} of ${N} caregivers</span>
        </div>
        <button id="_qp_close" style="background:none;border:none;font-size:20px;color:#aaa;cursor:pointer;line-height:1;padding:0 4px;">×</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;max-height:400px;overflow-y:auto;padding:14px 18px;">
        ${quotes.length ? quotes.map((q) => `
          <div style="background:white;border-left:3px solid ${catColor};padding:10px 12px;border-radius:0 6px 6px 0;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <p style="margin:0 0 5px;font-size:12px;color:#333;font-style:italic;line-height:1.55;">"${esc(q.quote)}"</p>
            <div style="font-size:10.5px;color:#999;">${esc(q.caregiver)}${q.age ? " · " + esc(q.age) : ""}</div>
          </div>`).join("") :
          `<p style="color:#aaa;font-size:12px;font-style:italic;margin:0;">No quotes available for this concept.</p>`}
      </div>`;
    quotesPanel.querySelector("#_qp_close")!.addEventListener("click", () => { quotesPanel.style.display = "none"; });
    quotesPanel.style.display = "block";
    quotesPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function attachBarEvents(svgEl: Element, rows: Array<VizConcept & { id: string; cnt: number }>, catColor: string) {
    svgEl.querySelectorAll("rect[aria-label^='bar-']").forEach((el) => {
      const id = el.getAttribute("aria-label")!.slice(4);
      const row = rows.find((r) => String(r.id) === id);
      if (!row) return;
      const cb = codebook.get(id);
      const previewQuote = cb?.quote;
      const previewCg = cb?.quote_caregiver;
      (el as SVGElement).style.cursor = "pointer";
      el.addEventListener("mouseover", (e: Event) => {
        const me = e as MouseEvent;
        me.stopPropagation();
        tt.style.maxWidth = "300px";
        tt.innerHTML = previewQuote
          ? `<div style="font-style:italic;margin-bottom:4px;">"${esc(previewQuote)}"</div><div style="font-size:10px;color:#888;">— ${esc(previewCg || "")} · click for all quotes</div>`
          : "Click to see quotes";
        tt.style.opacity = "1";
        tt.style.left = `${me.clientX + 14}px`;
        tt.style.top = `${me.clientY - 36}px`;
      });
      el.addEventListener("mousemove", (e: Event) => {
        const me = e as MouseEvent;
        tt.style.left = `${me.clientX + 14}px`;
        tt.style.top = `${me.clientY - 36}px`;
      });
      el.addEventListener("mouseout", () => { tt.style.opacity = "0"; });
      el.addEventListener("click", () => showQuotesForConcept(row, catColor));
    });
  }

  const bcPanels = catOrder.map((cat) => {
    const rows = bcConceptRows.filter((r) => r.category === cat).sort((a, b) => b.cnt - a.cnt);
    if (!rows.length) return null;
    const rowsStyled = rows.map((r, i) => ({
      ...r,
      fillOpacity: rows.length === 1 ? 1 : 1 - (i / (rows.length - 1)) * 0.65,
    }));
    const panel = Plot.plot({
      width: 680,
      height: rows.length * ROW_H + 28,
      marginLeft: 175, marginRight: 70, marginTop: 4, marginBottom: 28,
      style: { fontFamily: "Inter, sans-serif" },
      x: { domain: [0, N], label: "Caregivers", labelAnchor: "center", grid: true, tickSize: 4 },
      y: { domain: rows.map((r) => r.name), axis: null, label: null },
      marks: [
        Plot.axisY(rows.map((r) => r.name), {
          y: (d: string) => d, anchor: "left", tickSize: 0, fontSize: 11,
          tickPadding: 4, label: null, tickFormat: (d: string) => trunc(d, 26),
        }),
        Plot.barX(rowsStyled, {
          y: "name", x: "cnt", fill: catColors[cat], rx: 10,
          fillOpacity: "fillOpacity", ariaLabel: (d: { id: string }) => `bar-${d.id}`,
        }),
      ],
    });
    attachAxisTooltips(panel, new Map(rows.map((r) => [trunc(r.name, 26), r.name])));
    attachBarEvents(panel, rowsStyled, catColors[cat]);
    return { cat, panel };
  }).filter(Boolean) as Array<{ cat: string; panel: (SVGSVGElement | HTMLElement) & Plot.Plot }>;

  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;justify-content:center;";
  const inner = document.createElement("div");
  inner.style.cssText = "display:flex;align-items:stretch;font-family:Inter,sans-serif;";

  const greyStrip = document.createElement("div");
  greyStrip.style.cssText =
    "width:22px;background:#999;border-radius:10px 0 0 10px;flex-shrink:0;margin-right:3px;display:flex;align-items:center;justify-content:center;";
  greyStrip.innerHTML =
    `<span style="writing-mode:vertical-rl;transform:rotate(180deg);font-size:10px;font-weight:700;color:white;letter-spacing:2px;">CONCEPTS</span>`;
  inner.appendChild(greyStrip);

  const col = document.createElement("div");
  col.style.cssText = "display:flex;flex-direction:column;gap:16px;";
  for (const p of bcPanels) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:stretch;border-radius:0 10px 10px 0;overflow:hidden;";
    const strip = document.createElement("div");
    strip.style.cssText =
      `width:22px;background:${catColors[p.cat]};flex-shrink:0;border-radius:10px 0 0 10px;display:flex;align-items:center;justify-content:center;`;
    strip.innerHTML =
      `<span style="writing-mode:vertical-rl;transform:rotate(180deg);font-size:9px;font-weight:700;color:white;letter-spacing:1.5px;text-transform:uppercase;">${esc(catLabel(p.cat))}</span>`;
    const chartBox = document.createElement("div");
    chartBox.style.lineHeight = "0";
    chartBox.appendChild(p.panel);
    row.appendChild(strip);
    row.appendChild(chartBox);
    col.appendChild(row);
  }
  inner.appendChild(col);
  wrap.appendChild(inner);
  return wrap;
}

// ── Chart 2: Concept Co-occurrence heatmap ───────────────────────────────────
export function cooccurrenceChart(model: VizModel, hmMin: number): HTMLElement {
  const { allConcepts, cooc } = model;
  const hmRowConcepts = allConcepts.filter((r) => r.cnt >= hmMin);

  const hmColGroups: Record<string, Array<{ id: string; cnt: number; name: string; category: string }>> =
    Object.fromEntries(catOrder.map((cat) => [
      cat,
      allConcepts.filter((r) => r.category === cat && r.cnt >= hmMin).slice(0, 5)
        .map((r) => ({ id: r.id, cnt: r.cnt, name: r.name, category: cat })),
    ]));
  const hmColList = catOrder.flatMap((cat) => hmColGroups[cat]);

  const hmPanelMax: Record<string, number> = Object.fromEntries(catOrder.map((cat) => {
    const vals = (hmColGroups[cat] || []).flatMap((col) => hmRowConcepts.map((row) => cooc(row.id, col.id)));
    return [cat, Math.max(...vals, 1)];
  }));

  const hmYDomain: string[] = [];
  let hmPrevCat: string | null = null;
  for (const row of hmRowConcepts) {
    if (row.category !== hmPrevCat) { hmYDomain.push(`__hdr__${row.category}`); hmPrevCat = row.category; }
    hmYDomain.push(row.name);
  }
  const hmXDomain = catOrder.flatMap((cat, i) => [
    ...(i > 0 ? [`__sep__${i}`] : []),
    ...(hmColGroups[cat] || []).map((c) => c.name),
  ]);
  const hmCells = hmRowConcepts.flatMap((row) =>
    hmColList.map((col) => ({
      rowName: row.name, colName: col.name, rowCat: row.category, colCat: col.category,
      value: cooc(row.id, col.id),
      normalized: cooc(row.id, col.id) / hmPanelMax[col.category],
    })));
  const hmHdrEntries = hmYDomain.filter((d) => d.startsWith("__hdr__")).map((d) => ({ y: d, cat: d.replace("__hdr__", "") }));
  const hmColHeaders = catOrder
    .map((cat) => { const cols = hmColGroups[cat] ?? []; return { cat, x: cols[Math.floor(cols.length / 2)]?.name }; })
    .filter((d) => d.x);
  const hmRowBoundaries = hmYDomain.filter((d) => d.startsWith("__hdr__") && hmYDomain.indexOf(d) > 0);

  const HM_CELL = 14;
  const hmChart = Plot.plot({
    width: 300 + hmXDomain.length * HM_CELL + 20,
    height: 100 + hmYDomain.length * HM_CELL + 20,
    marginLeft: 300, marginRight: 20, marginTop: 100, marginBottom: 20,
    style: { overflow: "visible", fontFamily: "Inter, sans-serif" },
    x: { domain: hmXDomain, axis: null },
    y: { domain: hmYDomain, axis: null },
    marks: [
      Plot.cell(
        hmHdrEntries.flatMap((h) => hmXDomain.filter((x) => !x.startsWith("__sep__")).map((col) => ({ ...h, col }))),
        { x: "col", y: "y", fill: (d: { cat: string }) => catColors[d.cat], fillOpacity: 0.12 }),
      Plot.cell(hmCells, {
        x: "colName", y: "rowName",
        fill: (d: { colCat: string; normalized: number }) =>
          d3.interpolateRgb("white", catColors[d.colCat])(d.normalized),
      }),
      Plot.axisY(hmYDomain, {
        y: (d: string) => d, anchor: "left", tickSize: 0, fontSize: 9,
        fill: (d: string) => (d.startsWith("__hdr__") ? catColors[d.replace("__hdr__", "")] : "#333"),
        tickFormat: (d: string) => (d.startsWith("__hdr__") ? catLabel(d.replace("__hdr__", "")).toUpperCase() : trunc(d, 40)),
      }),
      Plot.axisX(hmXDomain.filter((d) => !d.startsWith("__sep__")), {
        x: (d: string) => d, anchor: "top", tickSize: 0, fontSize: 8.5,
        tickFormat: (d: string) => trunc(d, 22), tickRotate: -55,
      }),
      Plot.text(hmColHeaders, {
        x: "x", y: hmYDomain[0], text: (d: { cat: string }) => catLabel(d.cat),
        fill: (d: { cat: string }) => catColors[d.cat], fontWeight: "bold", fontSize: 11, textAnchor: "middle", dy: -82,
      }),
      ...catOrder.slice(1).map((_, i) =>
        Plot.ruleX([`__sep__${i + 1}`], { stroke: "#e0e0e0", strokeWidth: HM_CELL * 0.7 })),
      ...hmRowBoundaries.map((name) =>
        Plot.ruleY([name], { stroke: "#ccc", strokeWidth: 1, dy: -HM_CELL / 2 })),
    ],
  });
  attachAxisTooltips(hmChart, new Map([
    ...hmYDomain.filter((d) => !d.startsWith("__hdr__")).map((d) => [trunc(d, 40), d] as [string, string]),
    ...hmXDomain.filter((d) => !d.startsWith("__sep__")).map((d) => [trunc(d, 22), d] as [string, string]),
  ]));
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;justify-content:center;overflow-x:auto;";
  wrap.appendChild(hmChart);
  return wrap;
}

// ── Chart 3: Concept Landscape (bubble by domain) ────────────────────────────
export function landscapeChart(model: VizModel): HTMLElement {
  const { allConcepts, nInterviews } = model;
  const N = nInterviews;
  const lsMin = 1;

  const lsDomainAvg = d3.rollup(allConcepts, (v) => d3.mean(v, (d) => d.cnt)!, (d) => d.domain);
  const lsDomainOrder = [...lsDomainAvg.keys()].sort((a, b) => {
    const catA = allConcepts.find((c) => c.domain === a)?.category ?? "";
    const catB = allConcepts.find((c) => c.domain === b)?.category ?? "";
    const ci = catOrder.indexOf(catA) - catOrder.indexOf(catB);
    return ci !== 0 ? ci : lsDomainAvg.get(b)! - lsDomainAvg.get(a)!;
  });

  const MIN_CAT_SLOTS = 9, CAT_GAP = 2;
  const lsDomainPos = new Map<string, number>();
  const lsCatBandPos: Array<{ cat: string; x1: number; x2: number; nDomains: number }> = [];
  let lsCursor = 0;
  for (const cat of catOrder) {
    const catDoms = lsDomainOrder.filter((dom) => allConcepts.some((c) => c.domain === dom && c.category === cat));
    if (!catDoms.length) continue;
    const nSlots = Math.max(catDoms.length, MIN_CAT_SLOTS), step = nSlots / catDoms.length;
    catDoms.forEach((dom, i) => lsDomainPos.set(dom, lsCursor + i * step + step / 2));
    lsCatBandPos.push({ cat, x1: lsCursor, x2: lsCursor + nSlots, nDomains: catDoms.length });
    lsCursor += nSlots + CAT_GAP;
  }
  const lsTotalSlots = lsCursor - CAT_GAP;

  const lsBinSize = new Map<string, number>(), lsBinRank = new Map<string, number>();
  for (const d of allConcepts) {
    const key = `${d.domain}|${d.cnt}`;
    lsBinRank.set(d.id, lsBinSize.get(key) ?? 0);
    lsBinSize.set(key, (lsBinSize.get(key) ?? 0) + 1);
  }
  const LS_PX_PER_SLOT = (1400 - 50 - 20) / lsTotalSlots;
  const lsRPx = (c: number) => 3 + ((c - 1) / 11) * 14;
  const lsJittered = allConcepts.map((d) => {
    const key = `${d.domain}|${d.cnt}`, n = lsBinSize.get(key)!, rank = lsBinRank.get(d.id)!;
    const step = (2 * lsRPx(d.cnt) + 4) / LS_PX_PER_SLOT;
    const xOff = n === 1 ? 0 : (rank - (n - 1) / 2) * step;
    const yOff = n <= 2 ? 0 : rank % 2 === 0 ? 0.1 : -0.1;
    return { ...d, dx: lsDomainPos.get(d.domain)! + xOff, dy: d.cnt + yOff };
  });
  const lsDomainMarkers = lsDomainOrder.map((dom) => ({
    dom, xPos: lsDomainPos.get(dom)!,
    cat: allConcepts.find((c) => c.domain === dom)?.category ?? "",
  }));

  const yMax = N + 1;
  const lsVisible = lsJittered.filter((d) => d.cnt >= lsMin);
  const lsChart = Plot.plot({
    width: 1400, height: 520,
    marginLeft: 50, marginRight: 20, marginTop: 36, marginBottom: 155,
    style: { overflow: "visible", fontFamily: "Inter, sans-serif" },
    x: { domain: [-0.5, lsTotalSlots + 0.5], axis: null },
    y: { domain: [0.3, yMax + 1], label: null, grid: true },
    r: { domain: [1, N], range: [3, 17] },
    marks: [
      ...lsCatBandPos.map((b) => Plot.rect([b], { x1: "x1", x2: "x2", y1: 0.3, y2: yMax + 1, fill: (d: { cat: string }) => catColors[d.cat], opacity: 0.07 })),
      ...lsCatBandPos.map((b) => Plot.text([b], {
        x: (d: { x1: number; x2: number }) => (d.x1 + d.x2) / 2, y: yMax + 1,
        text: (d: { cat: string; nDomains: number }) => `${catLabel(d.cat)} (${d.nDomains})`,
        fill: (d: { cat: string }) => catColors[d.cat], fontWeight: "bold", fontSize: 11, textAnchor: "middle", dy: -6,
      })),
      Plot.ruleX(lsDomainMarkers, { x: "xPos", y1: yMax - 0.45, y2: yMax - 0.1, stroke: (d: { cat: string }) => catColors[d.cat] || "#999", strokeWidth: 1.5, strokeOpacity: 0.55 }),
      Plot.ruleY([N], { stroke: "#c0392b", strokeDasharray: "5,4", strokeWidth: 1.5 }),
      Plot.dot(lsVisible, {
        x: "dx", y: "dy", r: "cnt",
        fill: (d: { category: string }) => catColors[d.category], fillOpacity: 0.78, stroke: "white", strokeWidth: 0.8,
        channels: {
          Concept: "name", Domain: "domain",
          Category: (d: { category: string }) => catLabel(d.category),
          "Coded in": (d: { cnt: number }) => `${d.cnt} of ${N} caregivers`,
        },
        tip: { format: { x: false, y: false, r: false, fill: false }, lineWidth: 55 },
      }),
      Plot.text(lsDomainOrder.map((dom) => ({ dom, xPos: lsDomainPos.get(dom)! })), {
        x: "xPos", y: 0.3, text: (d: { dom: string }) => trunc(d.dom, 28), fontSize: 9,
        fill: "#555", textAnchor: "end", rotate: -70, dy: 14,
      }),
      ...lsCatBandPos.slice(1).map((b) => Plot.ruleX([b.x1 - CAT_GAP / 2], { stroke: "#ccc", strokeWidth: 1 })),
    ],
  });
  attachAxisTooltips(lsChart, new Map(lsDomainOrder.map((dom) => [trunc(dom, 28), dom])));
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex;justify-content:center;overflow-x:auto;";
  wrap.appendChild(lsChart);
  return wrap;
}

// ── Chart 4: Concept Hierarchy (drill-down treemap) ──────────────────────────
export function hierarchyChart(model: VizModel): HTMLElement {
  const { allConcepts, nInterviews } = model;
  const N = nInterviews;
  const W = 820, H = 520;

  const tmData = {
    name: "root",
    children: catOrder.map((cat) => ({
      name: cat, color: catColors[cat],
      children: [...new Set(allConcepts.filter((c) => c.category === cat).map((c) => c.domain))].map((dom) => ({
        name: dom, category: cat,
        children: allConcepts.filter((c) => c.category === cat && c.domain === dom)
          .map((c) => ({ name: c.name, value: c.cnt, id: c.id, category: cat, domain: dom })),
      })),
    })),
  };

  const root = d3.hierarchy(tmData).sum((d: any) => d.value ?? 0).sort((a, b) => b.value! - a.value!);
  d3.treemap().tile(d3.treemapBinary).size([W, H]).paddingOuter(4).paddingTop(22).paddingInner(2).round(true)(root as any);

  const catColorOf = (d: any) => { let n = d; while (n.depth > 1) n = n.parent; return n.data.color ?? "#aaa"; };

  const wrap = document.createElement("div");
  wrap.style.cssText = "font-family:Inter,sans-serif;user-select:none;";
  const bc = document.createElement("div");
  bc.style.cssText = "font-size:12px;color:#888;margin-bottom:7px;min-height:18px;";
  wrap.appendChild(bc);

  const svgSel = d3.select(wrap).append("svg")
    .attr("width", W).attr("height", H)
    .style("border-radius", "12px").style("overflow", "hidden").style("display", "block");

  function draw(focus: any) {
    const xS = d3.scaleLinear([focus.x0, focus.x1], [0, W]);
    const yS = d3.scaleLinear([focus.y0, focus.y1], [0, H]);
    const nodes = focus.descendants().filter((d: any) => d !== focus && d.depth <= focus.depth + 2);
    svgSel.selectAll("*").remove();

    svgSel.append("rect").attr("width", W).attr("height", H).attr("fill", "#efefef")
      .attr("cursor", focus.parent ? "pointer" : "default")
      .on("click", () => { if (focus.parent) draw(focus.parent); });

    const gEl = svgSel.selectAll("g.node").data(nodes).join("g").attr("class", "node")
      .attr("transform", (d: any) => `translate(${xS(d.x0).toFixed(1)},${yS(d.y0).toFixed(1)})`);

    const rw = (d: any) => Math.max(0, xS(d.x1) - xS(d.x0) - 1);
    const rh = (d: any) => Math.max(0, yS(d.y1) - yS(d.y0) - 1);
    const relDepth = (d: any) => d.depth - focus.depth;

    gEl.append("rect").attr("width", rw).attr("height", rh).attr("fill", catColorOf)
      .attr("fill-opacity", (d: any) => (relDepth(d) === 1 ? 0.88 : 0.52)).attr("rx", 5)
      .attr("stroke", "white").attr("stroke-width", 1.5)
      .attr("cursor", (d: any) => (d.children ? "pointer" : "default"))
      .on("click", (e: any, d: any) => { if (!d.children) return; e.stopPropagation(); draw(d); });

    gEl.each(function (this: any, d: any) {
      const w = rw(d), h = rh(d);
      if (w < 20 || h < 13) return;
      const lvl = relDepth(d);
      const fz = lvl === 1 ? 11 : 9;
      const maxC = Math.max(3, Math.floor(w / (fz * 0.58)));
      d3.select(this).append("text").attr("x", 5).attr("y", fz + 4)
        .attr("font-size", fz).attr("font-weight", lvl === 1 ? "700" : "400")
        .attr("fill", "white").attr("pointer-events", "none").text(trunc(d.data.name, maxC));
      if (!d.children && h > 26 && w > 36) {
        d3.select(this).append("text").attr("x", 5).attr("y", fz * 2 + 5)
          .attr("font-size", 8).attr("fill", "rgba(255,255,255,0.75)").attr("pointer-events", "none")
          .text(`${d.value}/${N}`);
      }
      d3.select(this).select("rect").append("title")
        .text(d.data.name + (d.value ? ` · ${d.value} of ${N} caregivers` : ""));
    });

    const path = focus.ancestors().reverse().filter((n: any) => n.depth > 0).map((n: any) => catLabel(n.data.name) || n.data.name);
    bc.innerHTML = ["<span style='color:#444;font-weight:600'>All Concepts</span>", ...path.map((p: string) => `<span style='color:#888'> › ${p}</span>`)].join("") +
      (focus.parent ? `<span style='color:#bbb;font-style:italic;'> — click background to go back</span>` : "");
  }

  draw(root);
  const centered = document.createElement("div");
  centered.style.cssText = "display:flex;justify-content:center;";
  centered.appendChild(wrap);
  return centered;
}

// ── Chart 5: Concept Saturation (cumulative curve + per-caregiver stacked) ───
export function saturationChart(model: VizModel): HTMLElement {
  const { caregivers, codebook } = model;
  const seen = new Set<string>();
  const satCurve: Array<{ n: number; newConcepts: number; total: number }> = [];
  const satByCategory: Array<{ n: number; category: string; newConcepts: number }> = [];
  caregivers.forEach((cg, i) => {
    const ids = new Set((cg.expected || []).map(String));
    const newIds = [...ids].filter((id) => !seen.has(id) && codebook.has(id) && codebook.get(id)!.category !== "DEMOGRAPHICS");
    const catCounts: Record<string, number> = Object.fromEntries(catOrder.map((c) => [c, 0]));
    for (const id of newIds) catCounts[codebook.get(id)!.category]++;
    newIds.forEach((id) => seen.add(id));
    satCurve.push({ n: i + 1, newConcepts: newIds.length, total: seen.size });
    catOrder.forEach((cat) => satByCategory.push({ n: i + 1, category: cat, newConcepts: catCounts[cat] }));
  });

  const nCg = caregivers.length;
  const finalTotal = satCurve.length ? satCurve[satCurve.length - 1].total : 0;
  const sat90n = satCurve.find((d) => d.total >= finalTotal * 0.9)?.n;

  const curveChart = Plot.plot({
    width: 960, height: 360,
    marginLeft: 55, marginRight: 45, marginBottom: 20, marginTop: 24,
    style: { fontFamily: "Inter, sans-serif" },
    x: { domain: [0.5, nCg + 0.5], axis: null },
    y: { domain: [0, Math.ceil(finalTotal * 1.1) || 1], label: "Cumulative unique concepts", grid: true },
    marks: [
      Plot.areaY(satCurve, { x: "n", y: "total", curve: "monotone-x", fill: "#4472C4", fillOpacity: 0.08 }),
      sat90n ? Plot.ruleY([Math.round(finalTotal * 0.9)], { stroke: "#e67e22", strokeDasharray: "5,4", strokeWidth: 1.5 }) : null,
      sat90n ? Plot.text([{}], { x: () => nCg + 0.4, y: () => Math.round(finalTotal * 0.9), text: () => "90 %", fontSize: 9, fill: "#e67e22", textAnchor: "start", dy: -5 }) : null,
      Plot.line(satCurve, { x: "n", y: "total", curve: "monotone-x", stroke: "#4472C4", strokeWidth: 2.5 }),
      Plot.dot(satCurve, { x: "n", y: "total", fill: "#4472C4", r: 4.5, stroke: "white", strokeWidth: 1.5 }),
      Plot.text(satCurve, { x: "n", y: "total", text: (d: { total: number }) => String(d.total), dy: -12, fontSize: 9, fill: "#333" }),
    ],
  });

  const barsChart = Plot.plot({
    width: 960, height: 260,
    marginLeft: 55, marginRight: 45, marginBottom: 48, marginTop: 4,
    style: { fontFamily: "Inter, sans-serif" },
    x: { domain: d3.range(1, nCg + 1), label: "Caregiver added", labelAnchor: "center", tickFormat: (d: number) => `CG ${d}`, tickRotate: -30 },
    y: { label: null, grid: true },
    marks: [
      Plot.barY(satByCategory, Plot.stackY({ x: "n", y: "newConcepts", fill: (d: { category: string }) => catColors[d.category], rx: 3, order: catOrder })),
      Plot.text(satCurve, { x: "n", y: "newConcepts", text: (d: { newConcepts: number }) => (d.newConcepts > 0 ? String(d.newConcepts) : ""), dy: -7, fontSize: 8.5, fill: "#555" }),
    ],
  });

  const wrap = document.createElement("div");
  wrap.style.cssText = "font-family:Inter,sans-serif;display:flex;flex-direction:column;align-items:center;";
  const c1 = document.createElement("div"); c1.style.lineHeight = "0"; c1.appendChild(curveChart);
  const c2 = document.createElement("div"); c2.style.lineHeight = "0"; c2.appendChild(barsChart);
  const summary = document.createElement("div");
  summary.style.cssText = "font-size:12px;color:#475569;margin-top:10px;text-align:center;max-width:640px;";
  summary.textContent = `${finalTotal} unique concepts identified across ${nCg} caregivers.` +
    (sat90n ? ` 90% of concepts emerged by caregiver ${sat90n}, indicating saturation.` : "");
  wrap.appendChild(c1); wrap.appendChild(c2); wrap.appendChild(summary);
  return wrap;
}

export function legendRow(): HTMLElement {
  const el = document.createElement("div");
  el.style.cssText = "display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;font-size:11px;color:#666;justify-content:center;";
  el.innerHTML = catOrder.map((cat) =>
    `<span style="display:inline-flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:${catColors[cat]};display:inline-block;"></span><span>${catLabel(cat)}</span></span>`
  ).join("");
  return el;
}
