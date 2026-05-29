"""Step 3 — Retrieve environmental layers.

Loads GeoJSON layers from a data directory into in-memory shapely geometries.
The bundled sample layers live in data/sample; point IMPATIKA_DATA_DIR at a
different directory (same filenames) to swap in real WDPA/HydroRIVERS/WorldCover
exports without touching the metrics code.

A missing layer is not an error: the corresponding `Layer.available` is False,
which the metrics step surfaces as an explicit "data unavailable" note rather
than fabricating values.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry

from app.config import settings
from app.core import geo

# Logical layer name -> filename in the data directory.
LAYER_FILES: dict[str, str] = {
    "protected_areas": "protected_areas.geojson",
    "rivers": "rivers.geojson",
    "land_cover": "land_cover.geojson",
    "settlements": "settlements.geojson",
    "species": "species.geojson",
    "elevation": "elevation_points.geojson",
}


@dataclass
class Feature:
    geom: BaseGeometry
    props: dict[str, Any]


@dataclass
class Layer:
    name: str
    available: bool
    features: list[Feature] = field(default_factory=list)
    note: str | None = None


def _load_layer(name: str, path: Path) -> Layer:
    if not path.exists():
        return Layer(name=name, available=False, note=f"Layer file not found: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return Layer(name=name, available=False, note=f"Failed to read {path.name}: {exc}")

    features: list[Feature] = []
    for feat in data.get("features", []):
        geom_json = feat.get("geometry")
        if not geom_json:
            continue
        try:
            geom = geo.to_shape(geom_json)
        except (ValueError, TypeError):
            continue
        if geom.is_empty:
            continue
        features.append(Feature(geom=geom, props=feat.get("properties", {}) or {}))

    return Layer(name=name, available=True, features=features)


class LayerStore:
    """Holds all environmental layers for one assessment run.

    Any object exposing `.get(name) -> Layer` can stand in here, which is the
    seam where a production data backend (PostGIS, cloud-hosted rasters, live
    APIs) would replace the file loader.
    """

    def __init__(self, layers: dict[str, Layer]):
        self._layers = layers

    def get(self, name: str) -> Layer:
        return self._layers.get(name, Layer(name=name, available=False, note="Unknown layer."))

    def available_names(self) -> list[str]:
        return [n for n, layer in self._layers.items() if layer.available]

    def unavailable_names(self) -> list[str]:
        return [n for n, layer in self._layers.items() if not layer.available]


def load_layers(data_dir: Path | str | None = None) -> LayerStore:
    base = Path(data_dir) if data_dir else settings.data_dir
    layers = {name: _load_layer(name, base / fname) for name, fname in LAYER_FILES.items()}
    return LayerStore(layers)
