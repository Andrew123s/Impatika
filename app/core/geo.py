"""Geometry helpers built on shapely + pyproj.

All public geometry in Impatika is EPSG:4326 (lon/lat degrees). Degrees are
useless for distances and areas, so anything metric is computed by projecting
to the local UTM zone, measuring there, and (where needed) projecting back.

Using shapely + pyproj rather than geopandas/GDAL keeps the install light and
avoids the fiona/GDAL build pain that is common on Windows.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

WGS84 = "EPSG:4326"


def to_shape(geojson_geom: dict[str, Any]) -> BaseGeometry:
    return shape(geojson_geom)


def to_geojson(geom: BaseGeometry) -> dict[str, Any]:
    return mapping(geom)


def utm_epsg_for(lon: float, lat: float) -> str:
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = int((lon + 180) / 6) + 1
    zone = min(max(zone, 1), 60)
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


@lru_cache(maxsize=64)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)


def project(geom: BaseGeometry, src: str, dst: str) -> BaseGeometry:
    if src == dst:
        return geom
    return shp_transform(_transformer(src, dst).transform, geom)


def reference_point(geom: BaseGeometry) -> tuple[float, float]:
    """A representative (lon, lat) for picking a UTM zone. Uses a guaranteed
    interior point so it works for polygons, lines and points alike."""
    p = geom.representative_point()
    return p.x, p.y


def buffer_metres(geom_wgs84: BaseGeometry, metres: float) -> BaseGeometry:
    """Buffer a WGS84 geometry by a distance in metres, returned in WGS84."""
    lon, lat = reference_point(geom_wgs84)
    utm = utm_epsg_for(lon, lat)
    projected = project(geom_wgs84, WGS84, utm)
    return project(projected.buffer(metres), utm, WGS84)


def area_hectares(geom_wgs84: BaseGeometry) -> float:
    lon, lat = reference_point(geom_wgs84)
    utm = utm_epsg_for(lon, lat)
    return project(geom_wgs84, WGS84, utm).area / 10_000.0


def distance_metres(a_wgs84: BaseGeometry, b_wgs84: BaseGeometry) -> float:
    """Minimum distance between two WGS84 geometries, in metres. 0 if they
    intersect. Both are projected to the UTM zone of `a` for the measurement."""
    if a_wgs84.intersects(b_wgs84):
        return 0.0
    lon, lat = reference_point(a_wgs84)
    utm = utm_epsg_for(lon, lat)
    return project(a_wgs84, WGS84, utm).distance(project(b_wgs84, WGS84, utm))


def intersection_area_hectares(a_wgs84: BaseGeometry, b_wgs84: BaseGeometry) -> float:
    if not a_wgs84.intersects(b_wgs84):
        return 0.0
    lon, lat = reference_point(a_wgs84)
    utm = utm_epsg_for(lon, lat)
    inter = project(a_wgs84, WGS84, utm).intersection(project(b_wgs84, WGS84, utm))
    return inter.area / 10_000.0 if not inter.is_empty else 0.0
