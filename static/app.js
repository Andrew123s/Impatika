"use strict";

const LEVEL_COLORS = { High: "#e5484d", Medium: "#f5a623", Low: "#3fb950", Unknown: "#6b7684" };
const THREATENED = new Set(["CR", "EN", "VU"]);

const THRESHOLD_FIELDS = [
  { key: "protected_overlap_high_pct", label: "Protected overlap High (%)" },
  { key: "protected_overlap_medium_pct", label: "Protected overlap Med (%)" },
  { key: "river_distance_high_m", label: "River dist High (m)" },
  { key: "river_distance_medium_m", label: "River dist Med (m)" },
  { key: "settlement_distance_high_m", label: "Settlement High (m)" },
  { key: "settlement_distance_medium_m", label: "Settlement Med (m)" },
  { key: "slope_high_deg", label: "Slope High (°)" },
  { key: "slope_medium_deg", label: "Slope Med (°)" },
  { key: "emissions_high_tco2e", label: "Emissions High (tCO₂e)" },
  { key: "emissions_medium_tco2e", label: "Emissions Med (tCO₂e)" },
];

let map, drawnItems, aoiLayer, currentGeometry = null;
let thresholdDefaults = {};
let lastRequest = null;

// ---- Map setup -------------------------------------------------------------
function initMap() {
  map = L.map("map", { zoomControl: true }).setView([-1.37, 36.86], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  drawnItems = new L.FeatureGroup().addTo(map);
  aoiLayer = new L.FeatureGroup().addTo(map);

  const drawControl = new L.Control.Draw({
    position: "topleft",
    edit: { featureGroup: drawnItems, edit: false },
    draw: {
      marker: true, polyline: true, polygon: true,
      rectangle: false, circle: false, circlemarker: false,
    },
  });
  map.addControl(drawControl);

  map.on(L.Draw.Event.CREATED, (e) => {
    drawnItems.clearLayers();
    drawnItems.addLayer(e.layer);
    setGeometry(e.layer.toGeoJSON().geometry);
  });
  map.on(L.Draw.Event.DELETED, () => setGeometry(null));
}

function setGeometry(geom) {
  currentGeometry = geom;
  const el = document.getElementById("geom-status");
  if (geom) { el.textContent = geom.type + " set ✓"; el.classList.remove("muted"); }
  else { el.textContent = "none — draw on map or load demo"; el.classList.add("muted"); }
}

// ---- Environmental layers --------------------------------------------------
async function loadLayers() {
  let data;
  try { data = await (await fetch("/layers")).json(); }
  catch (err) { console.warn("layers load failed", err); return; }

  if (data.protected_areas) {
    L.geoJSON(data.protected_areas, {
      style: { color: "#3fb950", weight: 1, fillColor: "#3fb950", fillOpacity: 0.12 },
      onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name}</b><br>${f.properties.designation || ""}`),
    }).addTo(map);
  }
  if (data.rivers) {
    L.geoJSON(data.rivers, {
      style: { color: "#2f81f7", weight: 2 },
      onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name}</b><br>${f.properties.flow || ""}`),
    }).addTo(map);
  }
  if (data.settlements) {
    L.geoJSON(data.settlements, {
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 5, color: "#f5a623", fillColor: "#f5a623", fillOpacity: 0.8, weight: 1 }),
      onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name}</b><br>pop. ${(f.properties.population || 0).toLocaleString()}`),
    }).addTo(map);
  }
  if (data.species) {
    L.geoJSON(data.species, {
      pointToLayer: (f, ll) => {
        const threat = THREATENED.has(f.properties.iucn_status);
        return L.circleMarker(ll, { radius: 5, color: threat ? "#e5484d" : "#a371f7", fillColor: threat ? "#e5484d" : "#a371f7", fillOpacity: 0.85, weight: 1 });
      },
      onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.common_name}</b> (${f.properties.iucn_status})<br><i>${f.properties.species}</i>`),
    }).addTo(map);
  }
  buildLegend();
}

function buildLegend() {
  document.getElementById("legend").innerHTML = `
    <div class="row"><span class="swatch" style="background:#3fb950"></span> Protected area</div>
    <div class="row"><span class="swatch" style="background:#2f81f7"></span> River</div>
    <div class="row"><span class="dot" style="background:#f5a623"></span> Settlement</div>
    <div class="row"><span class="dot" style="background:#e5484d"></span> Threatened species</div>
    <div class="row"><span class="dot" style="background:#a371f7"></span> Other species</div>
    <div class="row"><span class="swatch" style="background:#2f81f7;height:0;border-top:2px dashed #2f81f7"></span> Area of influence</div>`;
}

// ---- Demo ------------------------------------------------------------------
async function loadDemo() {
  const ex = await (await fetch("/example")).json();
  document.getElementById("f-name").value = ex.name;
  document.getElementById("f-type").value = ex.project_type;
  document.getElementById("f-description").value = ex.description || "";
  document.getElementById("f-length").value = ex.scale?.length_km ?? "";
  document.getElementById("f-area").value = ex.scale?.area_ha ?? "";
  document.getElementById("f-capacity").value = ex.scale?.capacity_mw ?? "";
  document.getElementById("f-activities").value = (ex.activities || []).join(", ");

  drawnItems.clearLayers();
  if (ex.geometry) {
    const layer = L.geoJSON(ex.geometry, { style: { color: "#e6edf3", weight: 3 } });
    layer.eachLayer((l) => drawnItems.addLayer(l));
    setGeometry(ex.geometry);
    map.fitBounds(drawnItems.getBounds(), { padding: [40, 40] });
  }
  setStatus("Demo project loaded. Click Run assessment.", "ok");
}

// ---- Thresholds ------------------------------------------------------------
async function loadThresholds() {
  try { thresholdDefaults = await (await fetch("/thresholds")).json(); }
  catch { thresholdDefaults = {}; }
  const grid = document.getElementById("thresholds-grid");
  grid.innerHTML = THRESHOLD_FIELDS.map((f) => `
    <label>${f.label}
      <input type="number" step="any" min="0" id="t-${f.key}" value="${thresholdDefaults[f.key] ?? ""}" />
    </label>`).join("");
}

function resetThresholds() {
  THRESHOLD_FIELDS.forEach((f) => {
    const el = document.getElementById("t-" + f.key);
    if (el) el.value = thresholdDefaults[f.key] ?? "";
  });
}

function readThresholds() {
  const t = {};
  THRESHOLD_FIELDS.forEach((f) => {
    const v = parseFloat(document.getElementById("t-" + f.key).value);
    t[f.key] = Number.isFinite(v) ? v : thresholdDefaults[f.key];
  });
  return t;
}

// ---- Assessment ------------------------------------------------------------
function buildProject() {
  const num = (id) => { const v = parseFloat(document.getElementById(id).value); return Number.isFinite(v) ? v : null; };
  return {
    name: document.getElementById("f-name").value || "Untitled project",
    description: document.getElementById("f-description").value,
    project_type: document.getElementById("f-type").value,
    geometry: currentGeometry,
    scale: { length_km: num("f-length"), area_ha: num("f-area"), capacity_mw: num("f-capacity") },
    activities: document.getElementById("f-activities").value.split(",").map((s) => s.trim()).filter(Boolean),
    sensitive_receptors: [],
  };
}

function buildRequest() {
  return { project: buildProject(), thresholds: readThresholds() };
}

async function runAssessment(evt) {
  evt.preventDefault();
  if (!currentGeometry) { setStatus("Add a geometry first (draw on the map or load the demo).", "error"); return; }

  const btn = document.getElementById("btn-assess");
  btn.disabled = true; setStatus("Assessing…", "");
  const request = buildRequest();
  try {
    const res = await fetch("/assess", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "Assessment failed (" + res.status + ").");
    }
    renderResult(await res.json());
    lastRequest = request;
    document.getElementById("btn-docx").disabled = false;
    document.getElementById("btn-pdf").disabled = false;
    setStatus("Assessment complete.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// ---- Export ----------------------------------------------------------------
async function exportReport(fmt) {
  if (!lastRequest) return;
  const btn = document.getElementById("btn-" + fmt);
  const original = btn.textContent;
  btn.disabled = true; btn.textContent = "Preparing…";
  try {
    const res = await fetch("/export/" + fmt, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastRequest),
    });
    if (!res.ok) throw new Error("Export failed (" + res.status + ").");
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    const name = match ? match[1] : "impatika_eia." + fmt;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
    setStatus(name + " downloaded.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = original;
  }
}

function renderResult(result) {
  // AOI on map
  aoiLayer.clearLayers();
  if (result.aoi?.geometry) {
    L.geoJSON(result.aoi.geometry, { style: { color: "#2f81f7", weight: 2, dashArray: "6 5", fillColor: "#2f81f7", fillOpacity: 0.06 } }).addTo(aoiLayer);
    const b = aoiLayer.getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [40, 40] });
  }

  // Risk summary
  document.getElementById("risk-summary").classList.remove("hidden");
  const overall = result.overall_risk;
  const ob = document.getElementById("overall-badge");
  ob.textContent = overall; ob.className = "badge " + overall;

  document.getElementById("risk-list").innerHTML = result.risk_scores.map((s) => `
    <div class="risk-item ${s.level}">
      <div class="cat"><span>${s.category}</span><span class="lvl">${s.level}</span></div>
      <div class="reason">${escapeHtml(s.reason)}</div>
    </div>`).join("");

  // Report + JSON
  document.getElementById("report-panel").classList.remove("hidden");
  document.getElementById("llm-badge").textContent = "prose: " + result.report.generator;
  document.getElementById("report-body").innerHTML = marked.parse(result.markdown || "");
  document.getElementById("json-body").textContent = JSON.stringify(result, null, 2);
}

// ---- UI helpers ------------------------------------------------------------
function setStatus(msg, kind) {
  const el = document.getElementById("status");
  el.textContent = msg; el.className = "status " + (kind || "");
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const isReport = tab.dataset.tab === "report";
    document.getElementById("report-body").classList.toggle("hidden", !isReport);
    document.getElementById("json-body").classList.toggle("hidden", isReport);
  }));
}
async function loadHealth() {
  try {
    const h = await (await fetch("/health")).json();
    document.getElementById("llm-badge").textContent = "prose: " + (h.llm_drafting ? "LLM" : "template");
  } catch { /* ignore */ }
}

// ---- Boot ------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadLayers();
  loadHealth();
  loadThresholds();
  setupTabs();
  document.getElementById("btn-docx").disabled = true;
  document.getElementById("btn-pdf").disabled = true;
  document.getElementById("btn-demo").addEventListener("click", loadDemo);
  document.getElementById("btn-reset-thresholds").addEventListener("click", resetThresholds);
  document.getElementById("btn-docx").addEventListener("click", () => exportReport("docx"));
  document.getElementById("btn-pdf").addEventListener("click", () => exportReport("pdf"));
  document.getElementById("project-form").addEventListener("submit", runAssessment);
});
