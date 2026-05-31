"use strict";

const LEVEL_COLORS = { High: "#e5484d", Medium: "#f5a623", Low: "#3fb950", Unknown: "#6b7684" };
const THREATENED = new Set(["CR", "EN", "VU"]);
const STORAGE_PROJECTS = "impatika_projects_v1";
const STORAGE_HISTORY = "impatika_history_v1";
const STORAGE_THEME = "impatika_theme_v1";
const STORAGE_PIN = "impatika_pin_v1";
const MAX_HISTORY = 8;

const BASEMAPS = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    opts: { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" },
  },
  light: {
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    opts: { maxZoom: 20, attribution: "&copy; OpenStreetMap &copy; CARTO" },
  },
  dark: {
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    opts: { maxZoom: 20, attribution: "&copy; OpenStreetMap &copy; CARTO" },
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    opts: { maxZoom: 19, attribution: "&copy; Esri" },
  },
};

const RISK_RANK = { Unknown: 0, Low: 1, Medium: 2, High: 3 };

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

const ACTIVITY_PRESETS = {
  road: ["land clearing", "earthworks", "excavation", "pavement", "bridge construction"],
  pipeline: ["trenching", "welding", "hydrotesting", "land restoration"],
  solar_farm: ["site grading", "panel installation", "cable trenching", "fencing"],
  wind_farm: ["foundation works", "turbine erection", "access roads", "cable laying"],
  dam: ["reservoir clearing", "concrete works", "spillway construction", "impoundment"],
  mine: ["overburden removal", "drilling", "blasting", "ore processing", "tailings management"],
  building: ["site preparation", "foundation", "structural works", "utilities"],
  other: ["site preparation", "construction", "operation"],
};

const LAND_COVER_COLORS = {
  "Tree cover": "#22863a",
  Grassland: "#7cb342",
  Shrubland: "#8d6e63",
  Cropland: "#f9a825",
  "Built-up": "#9e9e9e",
  Wetland: "#0288d1",
};

const METRIC_GROUPS = [
  { key: "biodiversity", title: "Biodiversity" },
  { key: "water", title: "Water" },
  { key: "land_soil", title: "Land & soil" },
  { key: "climate", title: "Climate" },
  { key: "social", title: "Social" },
];

let map, drawnItems, aoiLayer, baseTileLayer, currentGeometry = null;
let thresholdDefaults = {};
let lastRequest = null;
let lastResult = null;
let pinnedResult = null;
let bufferHints = {};
const envLayers = {};

// ---- Map setup -------------------------------------------------------------
function initMap() {
  map = L.map("map", { zoomControl: true }).setView([-1.37, 36.86], 11);
  setBasemap(localStorage.getItem(STORAGE_THEME) === "light" ? "light" : "osm");

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

function setBasemap(key) {
  const cfg = BASEMAPS[key] || BASEMAPS.osm;
  if (baseTileLayer) map.removeLayer(baseTileLayer);
  baseTileLayer = L.tileLayer(cfg.url, cfg.opts).addTo(map);
  baseTileLayer.bringToBack();
  const sel = document.getElementById("basemap-select");
  if (sel) sel.value = key;
}

function setGeometry(geom) {
  currentGeometry = geom;
  const el = document.getElementById("geom-status");
  if (geom) {
    el.textContent = geom.type + " set ✓";
    el.classList.remove("muted");
    showOnMap(geom);
  } else {
    el.textContent = "none — draw on map or load demo";
    el.classList.add("muted");
    drawnItems.clearLayers();
  }
}

function showOnMap(geom) {
  drawnItems.clearLayers();
  const layer = L.geoJSON(geom, { style: { color: "#e6edf3", weight: 3 } });
  layer.eachLayer((l) => drawnItems.addLayer(l));
  const b = drawnItems.getBounds();
  if (b.isValid()) map.fitBounds(b, { padding: [40, 40] });
}

// ---- Environmental layers --------------------------------------------------
function addEnvLayer(key, label, layerGroup, defaultOn) {
  envLayers[key] = { label, group: layerGroup, defaultOn };
  if (defaultOn) layerGroup.addTo(map);
}

async function loadLayers() {
  let data;
  try { data = await (await fetch("/layers")).json(); }
  catch (err) { console.warn("layers load failed", err); return; }

  if (data.protected_areas) {
    addEnvLayer("protected_areas", "Protected areas",
      L.geoJSON(data.protected_areas, {
        style: { color: "#3fb950", weight: 1, fillColor: "#3fb950", fillOpacity: 0.12 },
        onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name}</b><br>${f.properties.designation || ""}`),
      }), true);
  }
  if (data.rivers) {
    addEnvLayer("rivers", "Rivers",
      L.geoJSON(data.rivers, {
        style: { color: "#2f81f7", weight: 2 },
        onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name}</b><br>${f.properties.flow || ""}`),
      }), true);
  }
  if (data.settlements) {
    addEnvLayer("settlements", "Settlements",
      L.geoJSON(data.settlements, {
        pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 5, color: "#f5a623", fillColor: "#f5a623", fillOpacity: 0.8, weight: 1 }),
        onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.name}</b><br>pop. ${(f.properties.population || 0).toLocaleString()}`),
      }), true);
  }
  if (data.species) {
    addEnvLayer("species", "Species",
      L.geoJSON(data.species, {
        pointToLayer: (f, ll) => {
          const threat = THREATENED.has(f.properties.iucn_status);
          return L.circleMarker(ll, {
            radius: 5,
            color: threat ? "#e5484d" : "#a371f7",
            fillColor: threat ? "#e5484d" : "#a371f7",
            fillOpacity: 0.85,
            weight: 1,
          });
        },
        onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.common_name}</b> (${f.properties.iucn_status})<br><i>${f.properties.species}</i>`),
      }), true);
  }
  if (data.land_cover) {
    addEnvLayer("land_cover", "Land cover",
      L.geoJSON(data.land_cover, {
        style: (f) => {
          const cls = f.properties.class || "Other";
          const c = LAND_COVER_COLORS[cls] || "#6b7684";
          return { color: c, weight: 1, fillColor: c, fillOpacity: 0.2 };
        },
        onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.class}</b>`),
      }), false);
  }
  if (data.elevation_points) {
    addEnvLayer("elevation_points", "Elevation samples",
      L.geoJSON(data.elevation_points, {
        pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4, color: "#8b97a6", fillColor: "#8b97a6", fillOpacity: 0.7, weight: 1 }),
        onEachFeature: (f, l) => l.bindPopup(`Elevation: <b>${f.properties.elevation_m} m</b>`),
      }), false);
  }

  buildLayerToggles();
  buildLegend();
}

function buildLayerToggles() {
  const box = document.getElementById("layer-toggles");
  box.innerHTML = Object.entries(envLayers).map(([key, cfg]) => `
    <label class="layer-toggle">
      <input type="checkbox" data-layer="${key}" ${cfg.defaultOn ? "checked" : ""} />
      ${cfg.label}
    </label>`).join("");

  box.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const cfg = envLayers[cb.dataset.layer];
      if (!cfg) return;
      if (cb.checked) cfg.group.addTo(map);
      else map.removeLayer(cfg.group);
    });
  });
}

function buildLegend() {
  document.getElementById("legend").innerHTML = `
    <div class="row"><span class="swatch" style="background:#3fb950"></span> Protected area</div>
    <div class="row"><span class="swatch" style="background:#2f81f7"></span> River</div>
    <div class="row"><span class="dot" style="background:#f5a623"></span> Settlement</div>
    <div class="row"><span class="dot" style="background:#e5484d"></span> Threatened species</div>
    <div class="row"><span class="dot" style="background:#a371f7"></span> Other species</div>
    <div class="row"><span class="swatch" style="background:#22863a;height:8px"></span> Land cover</div>
    <div class="row"><span class="swatch" style="background:#2f81f7;height:0;border-top:2px dashed #2f81f7"></span> Area of influence</div>`;
}

// ---- Demo & buffers ----------------------------------------------------------
async function loadBuffers() {
  try { bufferHints = await (await fetch("/buffers")).json(); }
  catch { bufferHints = {}; }
}

async function loadDemo() {
  const ex = await (await fetch("/example")).json();
  fillFormFromProject(ex);
  drawnItems.clearLayers();
  if (ex.geometry) {
    showOnMap(ex.geometry);
    setGeometry(ex.geometry);
  }
  setStatus("Demo project loaded. Preview AOI or run assessment.", "ok");
}

function fillFormFromProject(ex) {
  document.getElementById("f-name").value = ex.name;
  document.getElementById("f-type").value = ex.project_type;
  document.getElementById("f-description").value = ex.description || "";
  document.getElementById("f-length").value = ex.scale?.length_km ?? "";
  document.getElementById("f-area").value = ex.scale?.area_ha ?? "";
  document.getElementById("f-capacity").value = ex.scale?.capacity_mw ?? "";
  document.getElementById("f-activities").value = (ex.activities || []).join(", ");
  document.getElementById("f-receptors").value = (ex.sensitive_receptors || []).join(", ");
}

// ---- Activity presets --------------------------------------------------------
function applyActivityPreset(force) {
  const type = document.getElementById("f-type").value;
  const field = document.getElementById("f-activities");
  const hint = document.getElementById("activity-hint");
  if (!force && field.value.trim()) return;
  const preset = ACTIVITY_PRESETS[type] || ACTIVITY_PRESETS.other;
  field.value = preset.join(", ");
  hint.classList.remove("hidden");
}

// ---- GeoJSON import ----------------------------------------------------------
function applyGeoJsonText(text) {
  let parsed;
  try { parsed = JSON.parse(text); }
  catch { throw new Error("Invalid JSON."); }

  let geom = parsed;
  if (parsed.type === "Feature") geom = parsed.geometry;
  if (parsed.type === "FeatureCollection") {
    const feats = parsed.features;
    if (!feats?.length) throw new Error("FeatureCollection is empty.");
    geom = feats[0].geometry;
  }
  if (!geom?.type || !geom.coordinates) throw new Error("No geometry found in GeoJSON.");
  const allowed = ["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"];
  if (!allowed.includes(geom.type)) throw new Error("Unsupported geometry type: " + geom.type);
  setGeometry(geom);
  setStatus(geom.type + " imported.", "ok");
}

function onGeoJsonFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try { applyGeoJsonText(reader.result); }
    catch (err) { setStatus(err.message, "error"); }
  };
  reader.readAsText(file);
}

// ---- Save / load projects ----------------------------------------------------
function getSavedProjects() {
  try { return JSON.parse(localStorage.getItem(STORAGE_PROJECTS) || "{}"); }
  catch { return {}; }
}

function refreshSavedSelect() {
  const sel = document.getElementById("saved-projects");
  const saved = getSavedProjects();
  const keys = Object.keys(saved).sort();
  sel.innerHTML = '<option value="">— select —</option>' +
    keys.map((k) => `<option value="${escapeHtml(k)}">${escapeHtml(k)}</option>`).join("");
}

function saveCurrentProject() {
  const name = document.getElementById("save-name").value.trim() || document.getElementById("f-name").value.trim();
  if (!name) { setStatus("Enter a name to save the project.", "error"); return; }
  const saved = getSavedProjects();
  saved[name] = buildProject();
  localStorage.setItem(STORAGE_PROJECTS, JSON.stringify(saved));
  refreshSavedSelect();
  document.getElementById("save-name").value = name;
  setStatus('Project "' + name + '" saved.', "ok");
}

function loadSelectedProject() {
  const key = document.getElementById("saved-projects").value;
  if (!key) { setStatus("Select a saved project.", "error"); return; }
  const proj = getSavedProjects()[key];
  if (!proj) { setStatus("Saved project not found.", "error"); return; }
  fillFormFromProject(proj);
  if (proj.geometry) setGeometry(proj.geometry);
  else setGeometry(null);
  setStatus('Loaded "' + key + '".', "ok");
}

function deleteSelectedProject() {
  const key = document.getElementById("saved-projects").value;
  if (!key) return;
  const saved = getSavedProjects();
  delete saved[key];
  localStorage.setItem(STORAGE_PROJECTS, JSON.stringify(saved));
  refreshSavedSelect();
  setStatus('Deleted "' + key + '".', "ok");
}

// ---- Assessment history ------------------------------------------------------
function pushHistory(result) {
  let hist;
  try { hist = JSON.parse(localStorage.getItem(STORAGE_HISTORY) || "[]"); }
  catch { hist = []; }
  const entry = {
    id: Date.now(),
    name: result.project.name,
    overall: result.overall_risk,
    at: new Date().toISOString(),
    request: lastRequest,
    snapshot: result,
  };
  hist.unshift(entry);
  hist = hist.slice(0, MAX_HISTORY);
  localStorage.setItem(STORAGE_HISTORY, JSON.stringify(hist));
  renderHistory(hist);
}

function renderHistory(hist) {
  const bar = document.getElementById("history-bar");
  const chips = document.getElementById("history-chips");
  if (!hist?.length) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  chips.innerHTML = hist.map((h) => `
    <button type="button" class="history-chip" data-id="${h.id}" title="${escapeHtml(h.at)} — Shift+click to pin">
      ${escapeHtml(h.name)} <span class="chip-risk ${h.overall}">${h.overall}</span>
    </button>`).join("");
  chips.querySelectorAll(".history-chip").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const entry = hist.find((x) => x.id === Number(btn.dataset.id));
      if (!entry?.request) return;
      if (e.shiftKey && entry.snapshot) {
        pinAssessment(entry.snapshot, entry.name);
        setStatus('Pinned "' + entry.name + '" for comparison (Shift+click).', "ok");
        return;
      }
      lastRequest = entry.request;
      fillFormFromProject(entry.request.project);
      if (entry.request.project.geometry) setGeometry(entry.request.project.geometry);
      setStatus("Re-running saved assessment…", "");
      await rerunFromRequest(entry.request);
    });
  });
}

function loadHistoryOnBoot() {
  let hist;
  try { hist = JSON.parse(localStorage.getItem(STORAGE_HISTORY) || "[]"); }
  catch { hist = []; }
  renderHistory(hist);
}

// ---- Thresholds --------------------------------------------------------------
async function loadThresholds() {
  try { thresholdDefaults = await (await fetch("/thresholds")).json(); }
  catch { thresholdDefaults = {}; }
  document.getElementById("thresholds-grid").innerHTML = THRESHOLD_FIELDS.map((f) => `
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

// ---- Project / request builders ----------------------------------------------
function buildProject() {
  const num = (id) => { const v = parseFloat(document.getElementById(id).value); return Number.isFinite(v) ? v : null; };
  const splitList = (id) => document.getElementById(id).value.split(",").map((s) => s.trim()).filter(Boolean);
  return {
    name: document.getElementById("f-name").value || "Untitled project",
    description: document.getElementById("f-description").value,
    project_type: document.getElementById("f-type").value,
    geometry: currentGeometry,
    scale: { length_km: num("f-length"), area_ha: num("f-area"), capacity_mw: num("f-capacity") },
    activities: splitList("f-activities"),
    sensitive_receptors: splitList("f-receptors"),
  };
}

function buildRequest() {
  return { project: buildProject(), thresholds: readThresholds() };
}

// ---- Preview AOI -------------------------------------------------------------
async function previewAoi() {
  if (!currentGeometry) { setStatus("Add a geometry first.", "error"); return; }
  const btn = document.getElementById("btn-preview-aoi");
  btn.disabled = true;
  setStatus("Computing AOI…", "");
  try {
    const res = await fetch("/aoi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildProject()),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "AOI preview failed.");
    }
    const aoi = await res.json();
    aoiLayer.clearLayers();
    L.geoJSON(aoi.geometry, {
      style: { color: "#2f81f7", weight: 2, dashArray: "6 5", fillColor: "#2f81f7", fillOpacity: 0.06 },
    }).addTo(aoiLayer);
    const b = aoiLayer.getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [40, 40] });

    const info = document.getElementById("aoi-preview-info");
    const buf = bufferHints[document.getElementById("f-type").value] ?? aoi.buffer_m;
    info.textContent = `AOI: ${aoi.buffer_m} m buffer (${buf} m for this type) · ${aoi.area_ha.toLocaleString()} ha`;
    info.classList.remove("hidden");
    setStatus("AOI preview shown on map.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// ---- Assessment --------------------------------------------------------------
async function rerunFromRequest(request) {
  const res = await fetch("/assess", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error("Assessment failed.");
  renderResult(await res.json());
  lastRequest = request;
  enableExports(true);
}

async function runAssessment(evt) {
  evt.preventDefault();
  if (!currentGeometry) { setStatus("Add a geometry first (draw, import, or load demo).", "error"); return; }

  const btn = document.getElementById("btn-assess");
  btn.disabled = true;
  setStatus("Assessing…", "");
  const request = buildRequest();
  try {
    const res = await fetch("/assess", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : "Assessment failed (" + res.status + ").");
    }
    const result = await res.json();
    renderResult(result);
    lastRequest = request;
    lastResult = result;
    enableExports(true);
    pushHistory(result);
    setStatus("Assessment complete.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function enableExports(on) {
  ["btn-md", "btn-print", "btn-docx", "btn-pdf", "btn-copy", "btn-geojson", "btn-json-dl", "btn-pin-header"].forEach((id) => {
    document.getElementById(id).disabled = !on;
  });
}

// ---- Export ------------------------------------------------------------------
async function exportReport(fmt) {
  if (!lastRequest) return;
  if (fmt === "md" && lastResult?.markdown) {
    downloadBlob(new Blob([lastResult.markdown], { type: "text/markdown" }), slugName() + ".md");
    setStatus("Markdown downloaded.", "ok");
    return;
  }
  const btn = document.getElementById("btn-" + fmt);
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Preparing…";
  try {
    const res = await fetch("/export/" + fmt, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastRequest),
    });
    if (!res.ok) throw new Error("Export failed (" + res.status + ").");
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    downloadBlob(blob, match ? match[1] : "impatika_eia." + fmt);
    setStatus("Export downloaded.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

function slugName() {
  const n = (lastResult?.project?.name || "impatika_eia").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_|_$/g, "");
  return n || "impatika_eia";
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function printReport() {
  document.body.classList.add("printing");
  window.print();
  setTimeout(() => document.body.classList.remove("printing"), 500);
}

async function copyMarkdown() {
  if (!lastResult?.markdown) return;
  try {
    await navigator.clipboard.writeText(lastResult.markdown);
    setStatus("Report copied to clipboard.", "ok");
  } catch {
    setStatus("Clipboard access denied.", "error");
  }
}

function exportJsonDownload() {
  if (!lastResult) return;
  downloadBlob(
    new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" }),
    slugName() + "_assessment.json"
  );
  setStatus("JSON assessment downloaded.", "ok");
}

async function exportGeoJson() {
  if (!lastRequest) return;
  const btn = document.getElementById("btn-geojson");
  btn.disabled = true;
  try {
    const res = await fetch("/export/geojson", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastRequest),
    });
    if (!res.ok) throw new Error("GeoJSON export failed.");
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    downloadBlob(await res.blob(), match ? match[1] : slugName() + "_aoi.geojson");
    setStatus("AOI GeoJSON downloaded.", "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// ---- Theme -------------------------------------------------------------------
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(STORAGE_THEME, theme);
  const btn = document.getElementById("btn-theme");
  if (btn) btn.textContent = theme === "light" ? "☀" : "◐";
  if (theme === "light" && document.getElementById("basemap-select")?.value === "dark") {
    setBasemap("light");
  } else if (theme === "dark" && document.getElementById("basemap-select")?.value === "light") {
    setBasemap("osm");
  }
}

function toggleTheme() {
  const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
  applyTheme(next);
}

function initTheme() {
  applyTheme(localStorage.getItem(STORAGE_THEME) || "dark");
}

// ---- Share URL ---------------------------------------------------------------
function encodeSharePayload() {
  const payload = { project: buildProject(), thresholds: readThresholds() };
  return "#p=" + btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
}

async function shareProject() {
  if (!currentGeometry) {
    setStatus("Add geometry before sharing.", "error");
    return;
  }
  const hash = encodeSharePayload();
  const url = location.origin + location.pathname + hash;
  try {
    await navigator.clipboard.writeText(url);
    history.replaceState(null, "", hash);
    setStatus("Share link copied to clipboard.", "ok");
  } catch {
    history.replaceState(null, "", hash);
    setStatus("Link updated in address bar (copy manually).", "ok");
  }
}

function loadFromHash() {
  const m = location.hash.match(/^#p=(.+)$/);
  if (!m) return;
  try {
    const payload = JSON.parse(decodeURIComponent(escape(atob(m[1]))));
    if (payload.project) {
      fillFormFromProject(payload.project);
      if (payload.project.geometry) setGeometry(payload.project.geometry);
    }
    if (payload.thresholds) {
      THRESHOLD_FIELDS.forEach((f) => {
        const el = document.getElementById("t-" + f.key);
        if (el && payload.thresholds[f.key] != null) el.value = payload.thresholds[f.key];
      });
    }
    setStatus("Project loaded from share link.", "ok");
  } catch {
    setStatus("Invalid share link in URL.", "error");
  }
}

// ---- Comparison --------------------------------------------------------------
function loadPinnedFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_PIN);
    if (raw) pinnedResult = JSON.parse(raw);
  } catch { pinnedResult = null; }
}

function pinAssessment(result, label) {
  pinnedResult = result;
  localStorage.setItem(STORAGE_PIN, JSON.stringify(result));
  updatePinUI(label || result?.project?.name || "Pinned");
}

function clearPin() {
  pinnedResult = null;
  localStorage.removeItem(STORAGE_PIN);
  updatePinUI(null);
}

function updatePinUI(label) {
  const ind = document.getElementById("pin-indicator");
  const btn = document.getElementById("btn-pin");
  const hdr = document.getElementById("btn-pin-header");
  if (!pinnedResult) {
    ind.classList.add("hidden");
    btn.classList.add("hidden");
    if (hdr) hdr.textContent = "Pin";
    renderCompareTab(null);
    return;
  }
  const name = label || pinnedResult.project?.name || "Pinned";
  ind.textContent = "Pinned baseline: " + name + " (overall " + pinnedResult.overall_risk + ")";
  ind.classList.remove("hidden");
  btn.classList.remove("hidden");
  btn.textContent = "Unpin";
  if (hdr) hdr.textContent = "Unpin";
  if (lastResult) renderCompareFromResults();
}

async function renderCompareFromResults() {
  if (!pinnedResult || !lastResult) {
    renderCompareTab(null);
    return;
  }
  try {
    const res = await fetch("/compare/results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseline: pinnedResult, current: lastResult }),
    });
    if (!res.ok) throw new Error("Compare failed.");
    renderCompareTab(await res.json());
  } catch (err) {
    renderCompareTab(clientCompare(pinnedResult, lastResult));
  }
}

function clientCompare(baseline, current) {
  const baseBy = Object.fromEntries(baseline.risk_scores.map((s) => [s.category, s.level]));
  const currBy = Object.fromEntries(current.risk_scores.map((s) => [s.category, s.level]));
  const cats = [...new Set([...Object.keys(baseBy), ...Object.keys(currBy)])];
  const deltas = cats.map((category) => {
    const b = baseBy[category] || "Unknown";
    const c = currBy[category] || "Unknown";
    let direction = "same";
    if (b !== c) {
      if (b === "Unknown" || c === "Unknown") direction = "unknown";
      else direction = (RISK_RANK[c] || 0) > (RISK_RANK[b] || 0) ? "up" : "down";
    }
    return { category, baseline_level: b, current_level: c, changed: b !== c, direction };
  });
  return {
    baseline_name: baseline.project.name,
    current_name: current.project.name,
    baseline_overall: baseline.overall_risk,
    current_overall: current.overall_risk,
    overall_changed: baseline.overall_risk !== current.overall_risk,
    deltas,
  };
}

function renderCompareTab(comparison) {
  const body = document.getElementById("compare-body");
  const tab = document.querySelector('.tab[data-tab="compare"]');
  if (!comparison) {
    body.innerHTML = pinnedResult
      ? "<p class='muted'>Run another assessment to compare against the pinned baseline.</p>"
      : "<p class='muted'>Pin an assessment (Pin button or Shift+click a history chip), then run a new scenario.</p>";
    if (tab) tab.classList.remove("has-changes");
    return;
  }
  const dirIcon = { up: "↑", down: "↓", same: "→", unknown: "?" };
  const rows = comparison.deltas.map((d) => `
    <tr class="${d.changed ? "changed-" + d.direction : ""}">
      <td>${escapeHtml(d.category)}</td>
      <td><span class="badge ${d.baseline_level}">${d.baseline_level}</span></td>
      <td class="delta-arrow">${dirIcon[d.direction] || "?"}</td>
      <td><span class="badge ${d.current_level}">${d.current_level}</span></td>
    </tr>`).join("");
  body.innerHTML = `
    <div class="compare-header">
      <div><span class="muted">Baseline</span><br><strong>${escapeHtml(comparison.baseline_name)}</strong>
        <span class="badge ${comparison.baseline_overall}">${comparison.baseline_overall}</span></div>
      <div class="compare-vs">vs</div>
      <div><span class="muted">Current</span><br><strong>${escapeHtml(comparison.current_name)}</strong>
        <span class="badge ${comparison.current_overall}">${comparison.current_overall}</span></div>
    </div>
    ${comparison.overall_changed ? "<p class='compare-alert'>Overall risk changed between scenarios.</p>" : "<p class='muted'>Overall risk unchanged.</p>"}
    <table class="compare-table">
      <thead><tr><th>Theme</th><th>Baseline</th><th></th><th>Current</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  if (tab) tab.classList.toggle("has-changes", comparison.deltas.some((d) => d.changed));
}

function renderRiskChart(scores) {
  const el = document.getElementById("risk-chart");
  if (!scores?.length) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  const max = 3;
  el.innerHTML = scores.map((s) => {
    const w = ((RISK_RANK[s.level] ?? 0) / max) * 100;
    const col = LEVEL_COLORS[s.level] || LEVEL_COLORS.Unknown;
    return `<div class="risk-bar-row" title="${escapeHtml(s.reason)}">
      <span class="risk-bar-label">${escapeHtml(s.category)}</span>
      <div class="risk-bar-track"><div class="risk-bar-fill" style="width:${w}%;background:${col}"></div></div>
      <span class="risk-bar-lvl">${s.level}</span>
    </div>`;
  }).join("");
}

// ---- Shortcuts ---------------------------------------------------------------
function setupShortcuts() {
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select") && e.key !== "Enter") return;
    if (e.key === "?" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      document.getElementById("shortcuts-dialog").showModal();
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      if (e.key === "Enter") {
        e.preventDefault();
        document.getElementById("project-form").requestSubmit();
      } else if (e.shiftKey && (e.key === "p" || e.key === "P")) {
        e.preventDefault();
        previewAoi();
      } else if (e.shiftKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        shareProject();
      }
    }
  });
  document.getElementById("btn-close-shortcuts").addEventListener("click", () => {
    document.getElementById("shortcuts-dialog").close();
  });
}

// ---- Render results ----------------------------------------------------------
function renderResult(result) {
  lastResult = result;

  aoiLayer.clearLayers();
  if (result.aoi?.geometry) {
    L.geoJSON(result.aoi.geometry, {
      style: { color: "#2f81f7", weight: 2, dashArray: "6 5", fillColor: "#2f81f7", fillOpacity: 0.06 },
    }).addTo(aoiLayer);
    const b = aoiLayer.getBounds();
    if (b.isValid()) map.fitBounds(b, { padding: [40, 40] });
    const info = document.getElementById("aoi-preview-info");
    info.textContent = `AOI: ${result.aoi.buffer_m} m buffer · ${result.aoi.area_ha.toLocaleString()} ha`;
    info.classList.remove("hidden");
  }

  const warnEl = document.getElementById("warnings-banner");
  if (result.warnings?.length) {
    warnEl.textContent = result.warnings.join(" ");
    warnEl.classList.remove("hidden");
  } else {
    warnEl.classList.add("hidden");
  }

  document.getElementById("risk-summary").classList.remove("hidden");
  const overall = result.overall_risk;
  const ob = document.getElementById("overall-badge");
  ob.textContent = overall;
  ob.className = "badge " + overall;

  document.getElementById("risk-list").innerHTML = result.risk_scores.map((s) => `
    <div class="risk-item ${s.level}">
      <div class="cat"><span>${s.category}</span><span class="lvl">${s.level}</span></div>
      <div class="reason">${escapeHtml(s.reason)}</div>
    </div>`).join("");

  renderRiskChart(result.risk_scores);
  document.getElementById("btn-pin").classList.remove("hidden");
  if (pinnedResult) renderCompareFromResults();
  else renderCompareTab(null);

  renderMitigationsSidebar(result.mitigations || []);
  renderMitigationsTab(result.mitigations || []);
  renderMetricsTab(result.metrics);

  document.getElementById("report-panel").classList.remove("hidden");
  document.getElementById("llm-badge").textContent = "prose: " + result.report.generator;
  document.getElementById("report-body").innerHTML = marked.parse(result.markdown || "");
  document.getElementById("json-body").textContent = JSON.stringify(result, null, 2);
}

function renderMitigationsSidebar(items) {
  const panel = document.getElementById("mitigations-panel");
  const list = document.getElementById("mitigations-list");
  if (!items.length) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  list.innerHTML = items.slice(0, 6).map((m) => `
    <div class="mitigation-card priority-${m.priority}">
      <span class="mit-cat">${escapeHtml(m.category)}</span>
      <span class="mit-pri">${m.priority}</span>
      <p>${escapeHtml(m.measure)}</p>
    </div>`).join("") +
    (items.length > 6 ? `<p class="hint">+${items.length - 6} more in the Mitigations tab</p>` : "");
}

function renderMitigationsTab(items) {
  const body = document.getElementById("mitigations-body");
  if (!items.length) {
    body.innerHTML = "<p class='muted'>No mitigations — all themes scored Low.</p>";
    return;
  }
  const byCat = {};
  items.forEach((m) => {
    if (!byCat[m.category]) byCat[m.category] = [];
    byCat[m.category].push(m);
  });
  body.innerHTML = Object.entries(byCat).map(([cat, measures]) => `
    <section class="metrics-section">
      <h3>${escapeHtml(cat)}</h3>
      <ul class="mitigation-list">
        ${measures.map((m) => `
          <li class="priority-${m.priority}">
            <span class="mit-tag">${m.priority}</span> (${m.linked_risk})
            ${escapeHtml(m.measure)}
          </li>`).join("")}
      </ul>
    </section>`).join("");
}

function renderMetricsTab(metrics) {
  const body = document.getElementById("metrics-body");
  body.innerHTML = METRIC_GROUPS.map(({ key, title }) => {
    const g = metrics[key];
    if (!g) return "";
    const rows = Object.entries(g.values || {}).map(([k, v]) => {
      let display = v;
      if (Array.isArray(v)) display = v.length ? JSON.stringify(v) : "—";
      else if (typeof v === "object" && v !== null) display = JSON.stringify(v);
      else if (typeof v === "number") display = Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
      return `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(display))}</td></tr>`;
    }).join("");
    const status = g.available
      ? `<span class="metric-ok">Available</span>`
      : `<span class="metric-gap">Unavailable</span>${g.note ? " — " + escapeHtml(g.note) : ""}`;
    return `
      <section class="metrics-section">
        <h3>${title} ${status}</h3>
        ${rows ? `<table class="metrics-table"><tbody>${rows}</tbody></table>` : "<p class='muted'>No values computed.</p>"}
      </section>`;
  }).join("");
}

// ---- UI helpers --------------------------------------------------------------
function setStatus(msg, kind) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className = "status " + (kind || "");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function setupTabs() {
  const panels = {
    report: "report-body",
    metrics: "metrics-body",
    mitigations: "mitigations-body",
    compare: "compare-body",
    json: "json-body",
  };
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const active = tab.dataset.tab;
      Object.entries(panels).forEach(([name, id]) => {
        document.getElementById(id).classList.toggle("hidden", name !== active);
      });
    });
  });
}

async function loadHealth() {
  try {
    const h = await (await fetch("/health")).json();
    document.getElementById("llm-badge").textContent = "prose: " + (h.llm_drafting ? "LLM" : "template");
  } catch { /* ignore */ }
}

// ---- Boot --------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initMap();
  loadLayers();
  loadHealth();
  loadThresholds();
  loadBuffers();
  loadPinnedFromStorage();
  setupTabs();
  setupShortcuts();
  refreshSavedSelect();
  loadHistoryOnBoot();
  loadFromHash();
  updatePinUI();
  enableExports(false);

  document.getElementById("basemap-select").addEventListener("change", (e) => setBasemap(e.target.value));
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  document.getElementById("btn-shortcuts").addEventListener("click", () => {
    document.getElementById("shortcuts-dialog").showModal();
  });
  document.getElementById("btn-share").addEventListener("click", shareProject);

  document.getElementById("btn-demo").addEventListener("click", loadDemo);
  document.getElementById("btn-preview-aoi").addEventListener("click", previewAoi);
  document.getElementById("btn-reset-thresholds").addEventListener("click", resetThresholds);
  document.getElementById("btn-md").addEventListener("click", () => exportReport("md"));
  document.getElementById("btn-print").addEventListener("click", printReport);
  document.getElementById("btn-copy").addEventListener("click", copyMarkdown);
  document.getElementById("btn-json-dl").addEventListener("click", exportJsonDownload);
  document.getElementById("btn-geojson").addEventListener("click", exportGeoJson);
  document.getElementById("btn-docx").addEventListener("click", () => exportReport("docx"));
  document.getElementById("btn-pdf").addEventListener("click", () => exportReport("pdf"));

  const pinHandler = () => {
    if (pinnedResult) clearPin();
    else if (lastResult) pinAssessment(lastResult);
  };
  document.getElementById("btn-pin").addEventListener("click", pinHandler);
  document.getElementById("btn-pin-header").addEventListener("click", pinHandler);
  document.getElementById("project-form").addEventListener("submit", runAssessment);

  document.getElementById("f-type").addEventListener("change", () => applyActivityPreset(false));
  document.getElementById("btn-apply-geojson").addEventListener("click", () => {
    try { applyGeoJsonText(document.getElementById("geojson-paste").value); }
    catch (err) { setStatus(err.message, "error"); }
  });
  document.getElementById("geojson-file").addEventListener("change", (e) => {
    if (e.target.files[0]) onGeoJsonFile(e.target.files[0]);
    e.target.value = "";
  });

  document.getElementById("btn-save-project").addEventListener("click", saveCurrentProject);
  document.getElementById("btn-load-saved").addEventListener("click", loadSelectedProject);
  document.getElementById("btn-delete-saved").addEventListener("click", deleteSelectedProject);
});
