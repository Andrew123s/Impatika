"use strict";

const LEVEL_COLORS = { High: "#e5484d", Medium: "#f5a623", Low: "#3fb950", Unknown: "#6b7684" };
const THREATENED = new Set(["CR", "EN", "VU"]);

let map, drawnItems, aoiLayer, currentGeometry = null;

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

// ---- Assessment ------------------------------------------------------------
function buildPayload() {
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

async function runAssessment(evt) {
  evt.preventDefault();
  if (!currentGeometry) { setStatus("Add a geometry first (draw on the map or load the demo).", "error"); return; }

  const btn = document.getElementById("btn-assess");
  btn.disabled = true; setStatus("Assessing…", "");
  try {
    const res = await fetch("/assess", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "Assessment failed (" + res.status + ").");
    }
    renderResult(await res.json());
    setStatus("Assessment complete.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false;
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
  setupTabs();
  document.getElementById("btn-demo").addEventListener("click", loadDemo);
  document.getElementById("project-form").addEventListener("submit", runAssessment);
});
