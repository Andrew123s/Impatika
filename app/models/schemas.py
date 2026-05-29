"""Pydantic models forming the data contract across the Impatika pipeline.

Flow of data:
    ProjectInput  -> AOI -> LayerMetrics -> RiskScores -> EIAReport
all bundled into AssessmentResult (the machine-readable output) which also
carries the human-readable markdown draft.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    road = "road"
    pipeline = "pipeline"
    solar_farm = "solar_farm"
    wind_farm = "wind_farm"
    dam = "dam"
    mine = "mine"
    building = "building"
    other = "other"


class RiskLevel(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    unknown = "Unknown"


# --- Input -------------------------------------------------------------------
class Location(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude in EPSG:4326.")
    lon: float = Field(..., ge=-180, le=180, description="Longitude in EPSG:4326.")
    region: Optional[str] = Field(None, description="Optional human-readable region name.")


class ProjectScale(BaseModel):
    length_km: Optional[float] = Field(None, ge=0, description="Linear extent (roads, pipelines).")
    area_ha: Optional[float] = Field(None, ge=0, description="Footprint area in hectares.")
    capacity_mw: Optional[float] = Field(None, ge=0, description="Generation capacity, if energy project.")


class ProjectInput(BaseModel):
    name: str
    description: str = ""
    project_type: ProjectType = ProjectType.other
    location: Optional[Location] = Field(
        None, description="Point location. Provide this OR geometry."
    )
    geometry: Optional[dict[str, Any]] = Field(
        None, description="GeoJSON geometry (Point/LineString/Polygon). Overrides location if set."
    )
    scale: ProjectScale = Field(default_factory=ProjectScale)
    activities: list[str] = Field(
        default_factory=list,
        description="e.g. ['land clearing', 'excavation', 'water abstraction'].",
    )
    sensitive_receptors: list[str] = Field(
        default_factory=list,
        description="Known nearby communities, rivers, or habitats the proponent flagged.",
    )


# --- AOI ---------------------------------------------------------------------
class AOI(BaseModel):
    geometry: dict[str, Any] = Field(..., description="Buffered area of influence as GeoJSON geometry (EPSG:4326).")
    buffer_m: float = Field(..., description="Buffer distance applied, in metres.")
    area_ha: float = Field(..., description="AOI area in hectares.")
    crs: str = "EPSG:4326"


# --- Metrics -----------------------------------------------------------------
class MetricGroup(BaseModel):
    """A category of metrics plus a flag for whether its source layer was found."""

    available: bool = True
    note: Optional[str] = None
    values: dict[str, Any] = Field(default_factory=dict)


class LayerMetrics(BaseModel):
    biodiversity: MetricGroup
    water: MetricGroup
    land_soil: MetricGroup
    climate: MetricGroup
    social: MetricGroup


# --- Scoring -----------------------------------------------------------------
class RiskScore(BaseModel):
    category: str
    level: RiskLevel
    reason: str = Field(..., description="Plain-language justification tied to the computed metric.")
    metric_basis: dict[str, Any] = Field(
        default_factory=dict, description="The specific metric value(s) behind this score."
    )


# --- Report ------------------------------------------------------------------
class ReportSection(BaseModel):
    title: str
    body: str


class EIAReport(BaseModel):
    generator: str = Field(..., description="'llm' or 'template' — how the prose was produced.")
    sections: list[ReportSection]


# --- Result ------------------------------------------------------------------
class AssessmentResult(BaseModel):
    project: ProjectInput
    aoi: AOI
    metrics: LayerMetrics
    risk_scores: list[RiskScore]
    overall_risk: RiskLevel
    report: EIAReport
    markdown: str = Field(..., description="Human-readable EIA draft.")
    warnings: list[str] = Field(default_factory=list)
