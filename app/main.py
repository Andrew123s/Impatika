"""FastAPI surface for Impatika.

Serves the single-page web frontend at `/` and the JSON/markdown API:
    GET  /health        — liveness + whether LLM drafting is enabled.
    GET  /example       — the demo project body.
    GET  /layers        — available environmental layers as GeoJSON (for the map).
    POST /aoi           — buffered AOI for a project (steps 1–2).
    POST /assess        — full EIA (steps 1–7). `?format=json|markdown`.
    POST /compare       — run two scenarios and return risk deltas.
    POST /export/geojson — AOI + footprint FeatureCollection download.
Interactive API docs remain at `/docs`.
"""
from __future__ import annotations

import json
import re

from shapely.geometry import mapping

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__, export
from app.config import BASE_DIR, BUFFER_METRES, DEFAULT_BUFFER_METRES
from app.core import aoi as aoi_mod
from app.core.compare import compare_results
from app.core.data_layers import load_layers
from app.examples import EXAMPLE_PROJECT
from app.llm import client as llm_client
from app.models.schemas import (
    AOI,
    AssessmentResult,
    AssessRequest,
    CompareRequest,
    CompareResultsBody,
    ComparisonResult,
    ProjectInput,
    Thresholds,
)
from app.pipeline import run_assessment

STATIC_DIR = BASE_DIR / "static"
_DEMO_REQUEST = {"demo": {"value": {"project": EXAMPLE_PROJECT.model_dump()}}}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "impatika_eia"

app = FastAPI(
    title="Impatika",
    version=__version__,
    description="AI Environmental Impact Assessment engine — GIS overlays, rule-based scoring, and LLM-drafted EIA reports.",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "llm_drafting": llm_client.is_available()}


@app.get("/example", response_model=ProjectInput)
def example() -> ProjectInput:
    return EXAMPLE_PROJECT


@app.get("/layers")
def layers() -> dict:
    """Available environmental layers as GeoJSON FeatureCollections, for the map."""
    store = load_layers()
    out: dict[str, dict] = {}
    for name in store.available_names():
        layer = store.get(name)
        out[name] = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": f.props, "geometry": mapping(f.geom)}
                for f in layer.features
            ],
        }
    return out


@app.get("/thresholds", response_model=Thresholds)
def thresholds() -> Thresholds:
    """Default risk-scoring thresholds (used to populate the UI editor)."""
    return Thresholds()


@app.get("/buffers")
def buffers() -> dict:
    """AOI buffer distances (metres) by project type — used for AOI preview in the UI."""
    out = dict(BUFFER_METRES)
    out["default"] = DEFAULT_BUFFER_METRES
    return out


@app.post("/aoi", response_model=AOI)
def aoi_endpoint(project: ProjectInput = Body(..., examples={"demo": {"value": EXAMPLE_PROJECT.model_dump()}})) -> AOI:
    try:
        return aoi_mod.build_aoi(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _assess(req: AssessRequest) -> AssessmentResult:
    try:
        return run_assessment(req.project, thresholds=req.thresholds)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _footprint_geometry(project: ProjectInput) -> dict | None:
    if project.geometry is not None:
        return project.geometry
    if project.location is not None:
        return {"type": "Point", "coordinates": [project.location.lon, project.location.lat]}
    return None


def _aoi_feature_collection(result: AssessmentResult) -> dict:
    features = [
        {
            "type": "Feature",
            "properties": {
                "role": "aoi",
                "name": result.project.name,
                "buffer_m": result.aoi.buffer_m,
                "area_ha": result.aoi.area_ha,
                "project_type": result.project.project_type.value,
            },
            "geometry": result.aoi.geometry,
        },
    ]
    footprint = _footprint_geometry(result.project)
    if footprint is not None:
        features.insert(
            0,
            {
                "type": "Feature",
                "properties": {"role": "footprint", "name": result.project.name},
                "geometry": footprint,
            },
        )
    return {"type": "FeatureCollection", "features": features}


@app.post("/compare", response_model=ComparisonResult)
def compare_scenarios(body: CompareRequest = Body(...)) -> ComparisonResult:
    """Run two assessments (e.g. different thresholds) and return risk deltas."""
    baseline = _assess(body.baseline)
    current = _assess(body.current)
    return compare_results(baseline, current)


@app.post("/compare/results", response_model=ComparisonResult)
def compare_existing(body: CompareResultsBody = Body(...)) -> ComparisonResult:
    """Compare two cached assessment results without re-running the pipeline."""
    return compare_results(body.baseline, body.current)


@app.post("/assess")
def assess(
    req: AssessRequest = Body(..., examples=_DEMO_REQUEST),
    format: str = Query("json", pattern="^(json|markdown)$"),
):
    result = _assess(req)
    if format == "markdown":
        return PlainTextResponse(result.markdown, media_type="text/markdown")
    return result


@app.post("/export/docx")
def export_docx(req: AssessRequest = Body(..., examples=_DEMO_REQUEST)) -> Response:
    result = _assess(req)
    data = export.to_docx(result)
    filename = f"{_slug(result.project.name)}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/export/geojson")
def export_geojson(req: AssessRequest = Body(..., examples=_DEMO_REQUEST)) -> Response:
    """AOI and project footprint as a GeoJSON FeatureCollection download."""
    result = _assess(req)
    data = json.dumps(_aoi_feature_collection(result), indent=2)
    filename = f"{_slug(result.project.name)}_aoi.geojson"
    return Response(
        content=data,
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/export/pdf")
def export_pdf(req: AssessRequest = Body(..., examples=_DEMO_REQUEST)) -> Response:
    result = _assess(req)
    data = export.to_pdf(result)
    filename = f"{_slug(result.project.name)}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
