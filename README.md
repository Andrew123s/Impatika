# Impatika — AI Environmental Impact Assessment Engine

Impatika analyses a proposed project, computes its environmental impacts from
GIS layers using transparent rule-based logic, and drafts a structured
Environmental Impact Assessment (EIA) report.

The pipeline is **deterministic where it matters** (geometry, metrics, risk
scoring) and uses an LLM **only for prose**, grounded strictly in the computed
numbers — it never invents environmental data.

## Pipeline

```
ProjectInput → AOI → Environmental layers → Impact metrics → Risk scores → EIA report
   (step 1)   (2)         (3)                   (4)             (5)          (6–7)
```

| Step | Module | What it does |
|---|---|---|
| 1 | `models/schemas.py` | Structured project input (type, location/geometry, scale, activities). |
| 2 | `core/aoi.py` | Buffers the footprint by a project-type distance → Area of Influence (EPSG:4326). |
| 3 | `core/data_layers.py` | Loads environmental layers (protected areas, rivers, land cover, settlements, species, elevation). |
| 4 | `core/metrics.py` | GIS overlays → biodiversity / water / land & soil / climate / social metrics. |
| 5 | `core/scoring.py` | Deterministic thresholds → Low / Medium / High, each with a reason and metric basis. |
| 6–7 | `core/report.py` | Seven EIA sections via Claude (or templates), plus a markdown draft. |

All buffer distances and risk thresholds live in `app/config.py` — the single,
auditable source of the scoring logic.

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# Run the tests (fully offline)
pytest -q

# Serve the API
uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs
```

Then open **http://127.0.0.1:8000** for the web UI, or `/docs` for the
interactive API.

### Web UI

The root path serves a single-page frontend (Leaflet map + project form). Draw
a point/line/polygon or click **Load demo**, run the assessment, and the map
shows the environmental layers and computed Area of Influence alongside a
colour-coded risk summary and the rendered EIA report. It is plain
HTML/CSS/JS served by FastAPI — no build step.

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Web UI (single-page frontend). |
| GET | `/health` | Liveness + whether LLM drafting is enabled. |
| GET | `/example` | A demo project body you can POST to `/assess`. |
| GET | `/layers` | Available environmental layers as GeoJSON (used by the map). |
| POST | `/aoi` | Just the buffered AOI (steps 1–2). |
| POST | `/assess` | Full EIA. `?format=json` (default) or `?format=markdown`. |

```bash
curl -s http://127.0.0.1:8000/example | \
  curl -s -X POST http://127.0.0.1:8000/assess -H "Content-Type: application/json" -d @-
```

## Output

`/assess` returns a machine-readable `AssessmentResult`: extracted project
metadata, AOI geometry, environmental metrics, risk scores (each with its
reason and metric basis), the report sections, and a ready-to-export markdown
draft. `?format=markdown` returns just the human-readable draft.

## LLM drafting (optional)

```bash
cp .env.example .env
# set ANTHROPIC_API_KEY=...   (and optionally IMPATIKA_MODEL)
```

With a key set, the seven EIA sections are drafted by Claude from the computed
assessment. Without a key — or if a call fails — Impatika falls back to
deterministic templates, so the whole pipeline runs offline. The report records
which generator was used (`report.generator`).

## Swapping in real data

The bundled layers under `data/sample/` are **illustrative only** (centred near
Nairobi so the demo project overlaps real features). To use authoritative data
(WDPA, HydroRIVERS, ESA WorldCover, GHSL/WorldPop, GBIF/IUCN, SRTM), export each
as GeoJSON with the same filenames into a directory and point `IMPATIKA_DATA_DIR`
at it — no code changes needed. A missing layer is reported as a data gap and
its theme is scored `Unknown` rather than guessed.

## Design notes

- **shapely + pyproj** (not geopandas/GDAL) for light, Windows-friendly installs.
  Metric distances/areas are computed by projecting to the local UTM zone.
- **Transparency first**: every risk score carries the metric value behind it;
  thresholds are centralised; the LLM is constrained to the computed facts.
- This is a **screening-level** tool providing environmental guidance, not legal
  advice, and the sample datasets are not authoritative.
