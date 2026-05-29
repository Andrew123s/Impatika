"""FastAPI surface for Impatika.

Endpoints:
    GET  /health        — liveness + whether LLM drafting is enabled.
    GET  /example       — the demo project body you can POST to /assess.
    POST /aoi           — just the buffered AOI for a project (steps 1–2).
    POST /assess        — full EIA: metrics, risk scores and report (steps 1–7).
    GET  /assess/{fmt}  — not used; see /assess?format=markdown.
"""
from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse

from app import __version__
from app.core import aoi as aoi_mod
from app.examples import EXAMPLE_PROJECT
from app.llm import client as llm_client
from app.models.schemas import AOI, AssessmentResult, ProjectInput
from app.pipeline import run_assessment

app = FastAPI(
    title="Impatika",
    version=__version__,
    description="AI Environmental Impact Assessment engine — GIS overlays, rule-based scoring, and LLM-drafted EIA reports.",
)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "llm_drafting": llm_client.is_available()}


@app.get("/example", response_model=ProjectInput)
def example() -> ProjectInput:
    return EXAMPLE_PROJECT


@app.post("/aoi", response_model=AOI)
def aoi_endpoint(project: ProjectInput = Body(..., examples={"demo": {"value": EXAMPLE_PROJECT.model_dump()}})) -> AOI:
    try:
        return aoi_mod.build_aoi(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/assess")
def assess(
    project: ProjectInput = Body(..., examples={"demo": {"value": EXAMPLE_PROJECT.model_dump()}}),
    format: str = Query("json", pattern="^(json|markdown)$"),
):
    try:
        result: AssessmentResult = run_assessment(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if format == "markdown":
        return PlainTextResponse(result.markdown, media_type="text/markdown")
    return result
