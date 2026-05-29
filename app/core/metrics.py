"""Step 4 — Compute impact metrics (rule-based GIS overlays).

Every metric is derived from the AOI/footprint geometry and the loaded layers.
Where a layer is unavailable the corresponding MetricGroup is marked
`available=False` with a note, and no values are invented.

`base_geom` is the project footprint (point/line/polygon); `aoi_geom` is its
buffered area of influence. Distances to receptors are measured from the
footprint; overlaps and exposure counts use the AOI.
"""
from __future__ import annotations

import math
from typing import Any

from shapely.geometry.base import BaseGeometry

from app.core import geo
from app.core.data_layers import Layer, LayerStore
from app.models.schemas import LayerMetrics, MetricGroup, ProjectInput, ProjectScale

THREATENED_IUCN = {"CR", "EN", "VU"}
NATURAL_LAND_COVER = {"Tree cover", "Shrubland", "Grassland", "Wetland"}

# --- Emission factors (first-order estimates, tonnes CO2e) -------------------
# Documented constants so the climate figure is reproducible. These are coarse
# planning-stage factors, NOT a substitute for a full GHG inventory.
TREE_REMOVAL_TCO2E_PER_HA = 450.0       # biomass + soil carbon, woodland
NONFOREST_VEG_TCO2E_PER_HA = 40.0       # grass/shrub conversion
ACTIVITY_TCO2E_PER_KM = 1500.0          # linear construction (roads/pipelines)
ACTIVITY_TCO2E_PER_FOOTPRINT_HA = 60.0  # generic earthworks / site works
ACTIVITY_TCO2E_PER_MW = 50.0            # equipment manufacture + install

# Assumed clearing corridor widths (m) when only a length is given.
CORRIDOR_WIDTH_M = {"road": 30.0, "pipeline": 25.0}
DEFAULT_CORRIDOR_WIDTH_M = 20.0


def _round(value: float | None, ndigits: int = 2) -> float | None:
    return round(value, ndigits) if value is not None else None


def _footprint_hectares(project: ProjectInput) -> float | None:
    s: ProjectScale = project.scale
    if s.area_ha:
        return s.area_ha
    if s.length_km:
        width = CORRIDOR_WIDTH_M.get(project.project_type.value, DEFAULT_CORRIDOR_WIDTH_M)
        return s.length_km * 1000.0 * width / 10_000.0
    return None


# --- Biodiversity ------------------------------------------------------------
def _biodiversity(aoi: BaseGeometry, base: BaseGeometry, layers: LayerStore, project: ProjectInput) -> MetricGroup:
    pa = layers.get("protected_areas")
    sp = layers.get("species")
    if not pa.available:
        return MetricGroup(available=False, note=pa.note or "Protected areas layer unavailable.")

    aoi_area = geo.area_hectares(aoi) or 1e-9
    overlap_total = 0.0
    pa_records: list[dict[str, Any]] = []
    nearest_pa = math.inf
    for f in pa.features:
        overlap = geo.intersection_area_hectares(aoi, f.geom)
        dist = geo.distance_metres(base, f.geom)
        nearest_pa = min(nearest_pa, dist)
        overlap_total += overlap
        if overlap > 0 or dist < (project.scale.length_km or 0) * 1000 + 5000:
            pa_records.append({
                "name": f.props.get("name", "unnamed"),
                "designation": f.props.get("designation"),
                "iucn_category": f.props.get("iucn_category"),
                "overlap_ha": _round(overlap),
                "distance_m": _round(dist, 1),
            })

    overlap_pct = min(overlap_total / aoi_area * 100.0, 100.0)

    threatened: list[dict[str, Any]] = []
    species_in_aoi = 0
    if sp.available:
        for f in sp.features:
            if aoi.contains(f.geom) or aoi.intersects(f.geom):
                species_in_aoi += 1
                if f.props.get("iucn_status") in THREATENED_IUCN:
                    threatened.append({
                        "common_name": f.props.get("common_name"),
                        "species": f.props.get("species"),
                        "iucn_status": f.props.get("iucn_status"),
                    })

    linear = project.project_type.value in {"road", "pipeline"}
    fragmentation = "elevated" if linear and overlap_total > 0 else "low"

    note = None if sp.available else "Species layer unavailable; threatened-species check skipped."
    return MetricGroup(available=True, note=note, values={
        "protected_area_overlap_pct": _round(overlap_pct),
        "protected_area_overlap_ha": _round(overlap_total),
        "protected_areas": pa_records,
        "nearest_protected_area_m": _round(0.0 if nearest_pa == math.inf else nearest_pa, 1),
        "species_occurrences_in_aoi": species_in_aoi,
        "threatened_species": threatened,
        "threatened_species_count": len(threatened),
        "habitat_fragmentation": fragmentation,
    })


# --- Water -------------------------------------------------------------------
def _water(aoi: BaseGeometry, base: BaseGeometry, layers: LayerStore) -> MetricGroup:
    rv = layers.get("rivers")
    if not rv.available:
        return MetricGroup(available=False, note=rv.note or "Rivers layer unavailable.")

    nearest = math.inf
    nearest_name = None
    crossed: list[str] = []
    perennial_in_aoi = False
    for f in rv.features:
        dist = geo.distance_metres(base, f.geom)
        if dist < nearest:
            nearest = dist
            nearest_name = f.props.get("name")
        if aoi.intersects(f.geom):
            crossed.append(f.props.get("name", "unnamed"))
            if f.props.get("flow") == "perennial":
                perennial_in_aoi = True

    return MetricGroup(available=True, values={
        "nearest_river_m": _round(0.0 if nearest == math.inf else nearest, 1),
        "nearest_river_name": nearest_name,
        "rivers_within_aoi": crossed,
        "perennial_river_within_aoi": perennial_in_aoi,
        "floodplain": "not assessed (no floodplain layer)",
        "water_scarcity_index": "not assessed (no water-stress layer)",
    })


# --- Land & soil -------------------------------------------------------------
def _land_soil(aoi: BaseGeometry, layers: LayerStore, project: ProjectInput) -> MetricGroup:
    lc = layers.get("land_cover")
    el = layers.get("elevation")
    if not lc.available:
        return MetricGroup(available=False, note=lc.note or "Land cover layer unavailable.")

    aoi_area = geo.area_hectares(aoi) or 1e-9
    by_class: dict[str, float] = {}
    for f in lc.features:
        area = geo.intersection_area_hectares(aoi, f.geom)
        if area <= 0:
            continue
        cls = f.props.get("class", "Unknown")
        by_class[cls] = by_class.get(cls, 0.0) + area

    composition = [
        {"class": cls, "area_ha": _round(area), "pct": _round(area / aoi_area * 100.0)}
        for cls, area in sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
    ]
    dominant = composition[0]["class"] if composition else None
    natural_ha = sum(a for c, a in by_class.items() if c in NATURAL_LAND_COVER)
    natural_pct = natural_ha / aoi_area * 100.0
    tree_ha = by_class.get("Tree cover", 0.0)

    footprint_ha = _footprint_hectares(project)
    veg_removal_ha = None
    tree_removal_ha = None
    if footprint_ha is not None:
        veg_removal_ha = footprint_ha * (natural_ha / aoi_area)
        tree_removal_ha = footprint_ha * (tree_ha / aoi_area)

    # Slope proxy from sampled elevations within the AOI.
    mean_slope_deg = None
    relief_m = None
    slope_note = None
    if el.available:
        elevs = [
            f.props.get("elevation_m")
            for f in el.features
            if aoi.intersects(f.geom) and isinstance(f.props.get("elevation_m"), (int, float))
        ]
        if len(elevs) >= 2:
            relief_m = max(elevs) - min(elevs)
            char_length_m = math.sqrt(aoi_area * 10_000.0)
            mean_slope_deg = math.degrees(math.atan2(relief_m, char_length_m))
        else:
            slope_note = "Insufficient elevation samples in AOI for a slope estimate."
    else:
        slope_note = "Elevation layer unavailable; slope not estimated."

    return MetricGroup(available=True, note=slope_note, values={
        "land_cover_composition": composition,
        "dominant_land_cover": dominant,
        "natural_vegetation_pct": _round(natural_pct),
        "estimated_footprint_ha": _round(footprint_ha),
        "vegetation_removal_ha": _round(veg_removal_ha),
        "tree_removal_ha": _round(tree_removal_ha),
        "mean_slope_deg": _round(mean_slope_deg, 1),
        "terrain_relief_m": _round(relief_m, 1),
    })


# --- Climate -----------------------------------------------------------------
def _climate(land_soil: MetricGroup, project: ProjectInput) -> MetricGroup:
    tree_removal = (land_soil.values.get("tree_removal_ha") or 0.0) if land_soil.available else 0.0
    veg_removal = (land_soil.values.get("vegetation_removal_ha") or 0.0) if land_soil.available else 0.0
    nonforest_removal = max(veg_removal - tree_removal, 0.0)

    lulc = tree_removal * TREE_REMOVAL_TCO2E_PER_HA + nonforest_removal * NONFOREST_VEG_TCO2E_PER_HA

    s = project.scale
    activity = 0.0
    if s.length_km and project.project_type.value in {"road", "pipeline"}:
        activity += s.length_km * ACTIVITY_TCO2E_PER_KM
    footprint = _footprint_hectares(project)
    if footprint:
        activity += footprint * ACTIVITY_TCO2E_PER_FOOTPRINT_HA
    if s.capacity_mw:
        activity += s.capacity_mw * ACTIVITY_TCO2E_PER_MW

    total = lulc + activity
    return MetricGroup(available=True, note="First-order estimate; not a full GHG inventory.", values={
        "land_use_change_emissions_tco2e": _round(lulc),
        "activity_emissions_tco2e": _round(activity),
        "total_estimated_emissions_tco2e": _round(total),
    })


# --- Social ------------------------------------------------------------------
def _social(aoi: BaseGeometry, base: BaseGeometry, layers: LayerStore) -> MetricGroup:
    st = layers.get("settlements")
    if not st.available:
        return MetricGroup(available=False, note=st.note or "Settlements layer unavailable.")

    nearest = math.inf
    nearest_name = None
    in_aoi: list[dict[str, Any]] = []
    pop_exposed = 0
    for f in st.features:
        dist = geo.distance_metres(base, f.geom)
        if dist < nearest:
            nearest = dist
            nearest_name = f.props.get("name")
        if aoi.intersects(f.geom):
            pop = f.props.get("population", 0) or 0
            pop_exposed += int(pop)
            in_aoi.append({
                "name": f.props.get("name"),
                "population": pop,
                "type": f.props.get("type"),
            })

    return MetricGroup(available=True, values={
        "nearest_settlement_m": _round(0.0 if nearest == math.inf else nearest, 1),
        "nearest_settlement_name": nearest_name,
        "settlements_in_aoi": in_aoi,
        "population_exposed": pop_exposed,
        "cultural_heritage": "not assessed (no heritage layer)",
    })


def compute_metrics(
    aoi_geom: BaseGeometry,
    base_geom: BaseGeometry,
    project: ProjectInput,
    layers: LayerStore,
) -> LayerMetrics:
    biodiversity = _biodiversity(aoi_geom, base_geom, layers, project)
    water = _water(aoi_geom, base_geom, layers)
    land_soil = _land_soil(aoi_geom, layers, project)
    climate = _climate(land_soil, project)
    social = _social(aoi_geom, base_geom, layers)
    return LayerMetrics(
        biodiversity=biodiversity,
        water=water,
        land_soil=land_soil,
        climate=climate,
        social=social,
    )
