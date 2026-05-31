"""Step 2 — Define the Area of Influence (AOI).

Takes a project's point location or GeoJSON geometry, normalises it to WGS84,
and buffers it by a project-type-specific distance to produce the AOI polygon
that every downstream overlay is computed against.
"""
from __future__ import annotations

from shapely.geometry import Point

from app.config import BUFFER_METRES, DEFAULT_BUFFER_METRES
from app.core import geo
from app.models.schemas import AOI, ProjectInput


def buffer_for(project_type: str) -> float:
    return BUFFER_METRES.get(project_type, DEFAULT_BUFFER_METRES)


def build_aoi(project: ProjectInput) -> AOI:
    """Construct the buffered AOI for a project.

    Precedence: explicit GeoJSON geometry > point location. One of the two
    must be present (validated here so the API can return a clear 422).
    """
    if project.geometry is not None:
        base = geo.to_shape(project.geometry)
    elif project.location is not None:
        base = Point(project.location.lon, project.location.lat)
    else:
        raise ValueError("Project must include either a `location` or a GeoJSON `geometry`.")

    if base.is_empty:
        raise ValueError("Project geometry is empty.")

    buffer_m = buffer_for(project.project_type.value)
    aoi_geom = geo.buffer_metres(base, buffer_m)

    return AOI(
        geometry=geo.to_geojson(aoi_geom),
        buffer_m=buffer_m,
        area_ha=round(geo.area_hectares(aoi_geom), 2),
    )
