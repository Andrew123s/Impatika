"""End-to-end and unit tests for the Impatika pipeline.

These run fully offline (no ANTHROPIC_API_KEY needed): the report generator
falls back to deterministic templates, so assertions are stable.
"""
from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Point

from app import export
from app.core import aoi as aoi_mod
from app.core import geo
from app.core.data_layers import load_layers
from app.examples import EXAMPLE_PROJECT
from app.models.schemas import ProjectInput, ProjectScale, RiskLevel, Thresholds
from app.pipeline import run_assessment


# --- geo helpers -------------------------------------------------------------
def test_buffer_area_is_metric_accurate():
    # A 1000 m buffer of a point should enclose ~pi*1km^2 = ~314 ha.
    aoi = geo.buffer_metres(Point(36.85, -1.37), 1000.0)
    area = geo.area_hectares(aoi)
    assert math.isclose(area, math.pi * 100, rel_tol=0.05)


def test_distance_metres_zero_on_intersection():
    line = LineString([(36.78, -1.33), (36.92, -1.40)])
    pt_on = Point(36.85, -1.37)
    assert geo.distance_metres(line, pt_on) < 2000  # near the line
    poly = geo.buffer_metres(line, 100)
    assert geo.distance_metres(line, poly) == 0.0


def test_utm_zone_hemisphere():
    assert geo.utm_epsg_for(36.85, -1.37).endswith(("37",))  # zone 37
    assert geo.utm_epsg_for(36.85, -1.37) == "EPSG:32737"     # southern hemisphere
    assert geo.utm_epsg_for(36.85, 1.37) == "EPSG:32637"      # northern hemisphere


# --- AOI ---------------------------------------------------------------------
def test_aoi_buffer_by_type():
    assert aoi_mod.buffer_for("road") == 1000.0
    assert aoi_mod.buffer_for("solar_farm") == 500.0
    assert aoi_mod.buffer_for("dam") == 5000.0


def test_aoi_requires_geometry_or_location():
    with pytest.raises(ValueError):
        aoi_mod.build_aoi(ProjectInput(name="x"))


# --- full pipeline on the demo project --------------------------------------
def test_demo_assessment_is_high_risk():
    result = run_assessment(EXAMPLE_PROJECT)

    # Report shape
    assert len(result.report.sections) == 7
    assert result.report.generator == "template"  # no API key in test env
    assert result.markdown.startswith("# Environmental Impact Assessment")

    by_cat = {s.category: s.level for s in result.risk_scores}
    # Road crosses the national park -> high biodiversity; passes a village -> high social.
    assert by_cat["Biodiversity"] == RiskLevel.high
    assert by_cat["Social"] == RiskLevel.high
    assert result.overall_risk == RiskLevel.high

    # Every score carries a non-empty justification.
    assert all(s.reason for s in result.risk_scores)


def test_demo_metrics_detect_protected_overlap_and_species():
    result = run_assessment(EXAMPLE_PROJECT)
    bio = result.metrics.biodiversity
    assert bio.available
    assert bio.values["protected_area_overlap_pct"] > 0
    assert bio.values["threatened_species_count"] >= 1


# --- remote project: nothing nearby -> low/unknown, still runs ---------------
def test_remote_project_runs_and_scores_low():
    remote = ProjectInput(
        name="Remote solar (demo)",
        project_type="solar_farm",
        location={"lat": 10.0, "lon": -40.0},  # mid-Atlantic; no sample features near
        scale=ProjectScale(area_ha=50),
    )
    result = run_assessment(remote)
    assert len(result.report.sections) == 7
    by_cat = {s.category: s.level for s in result.risk_scores}
    # Far from rivers/settlements -> Low on those themes.
    assert by_cat["Water"] == RiskLevel.low
    assert by_cat["Social"] == RiskLevel.low


# --- missing layers -> graceful Unknown -------------------------------------
def test_thresholds_override_reclassifies_climate():
    base = {s.category: s.level for s in run_assessment(EXAMPLE_PROJECT).risk_scores}
    assert base["Climate"] == RiskLevel.medium  # ~31k tCO2e in the 5k–50k band

    # Raise the Medium emissions band above the project's estimate -> Low.
    t = Thresholds(emissions_medium_tco2e=40_000)
    over = {s.category: s.level for s in run_assessment(EXAMPLE_PROJECT, thresholds=t).risk_scores}
    assert over["Climate"] == RiskLevel.low


def test_exports_produce_valid_files():
    result = run_assessment(EXAMPLE_PROJECT)
    docx_bytes = export.to_docx(result)
    pdf_bytes = export.to_pdf(result)
    assert docx_bytes[:2] == b"PK"        # docx is a zip container
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(docx_bytes) > 5_000 and len(pdf_bytes) > 1_000


def test_parse_blocks_handles_tables_and_lists():
    blocks = export.parse_blocks("intro para\n\n- one\n- two\n\n| A | B |\n|---|---|\n| 1 | 2 |")
    kinds = [b["type"] for b in blocks]
    assert kinds == ["para", "list", "table"]
    assert blocks[1]["items"] == ["one", "two"]
    assert blocks[2]["rows"] == [["A", "B"], ["1", "2"]]  # separator row dropped


def test_missing_layers_yield_unknown(tmp_path):
    empty_store = load_layers(tmp_path)  # no geojson files here
    result = run_assessment(EXAMPLE_PROJECT, layers=empty_store)
    levels = {s.category: s.level for s in result.risk_scores}
    assert levels["Biodiversity"] == RiskLevel.unknown
    assert levels["Water"] == RiskLevel.unknown
    assert result.warnings  # warns about unavailable layers
