"""Step 5 — Convert metrics into deterministic risk scores.

Each scorer reads one MetricGroup, applies the thresholds (overridable per
request via the Thresholds model, defaulting to app.config), and returns a
RiskScore carrying the level, a plain-language reason, and the exact metric
value(s) behind it (`metric_basis`) so any score can be audited to its input.

Unavailable metrics yield RiskLevel.unknown rather than an assumed level.
"""
from __future__ import annotations

from app.models.schemas import LayerMetrics, MetricGroup, RiskLevel, RiskScore, Thresholds

_RANK = {RiskLevel.unknown: -1, RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}


def _max_level(*levels: RiskLevel) -> RiskLevel:
    known = [lv for lv in levels if lv != RiskLevel.unknown]
    if not known:
        return RiskLevel.unknown
    return max(known, key=lambda lv: _RANK[lv])


def _unknown(category: str, group: MetricGroup) -> RiskScore:
    return RiskScore(
        category=category,
        level=RiskLevel.unknown,
        reason=group.note or f"{category} data unavailable; risk could not be scored.",
    )


def _score_biodiversity(g: MetricGroup, t: Thresholds) -> RiskScore:
    if not g.available:
        return _unknown("Biodiversity", g)
    v = g.values
    overlap = v.get("protected_area_overlap_pct", 0.0) or 0.0
    threatened = v.get("threatened_species_count", 0) or 0

    if overlap > t.protected_overlap_high_pct:
        overlap_level = RiskLevel.high
        overlap_reason = f"AOI overlaps protected areas by {overlap:.1f}% (>{t.protected_overlap_high_pct:g}%)."
    elif overlap > t.protected_overlap_medium_pct:
        overlap_level = RiskLevel.medium
        overlap_reason = (f"AOI overlaps protected areas by {overlap:.1f}% "
                          f"({t.protected_overlap_medium_pct:g}–{t.protected_overlap_high_pct:g}%).")
    else:
        overlap_level = RiskLevel.low
        overlap_reason = f"Negligible protected-area overlap ({overlap:.1f}%)."

    if threatened > 0:
        names = ", ".join(s.get("common_name") or s.get("species") for s in v.get("threatened_species", []))
        species_level = RiskLevel.high
        species_reason = f"{threatened} threatened species recorded in AOI ({names})."
    else:
        species_level = RiskLevel.low
        species_reason = "No threatened species recorded in AOI."

    level = _max_level(overlap_level, species_level)
    reason = f"{overlap_reason} {species_reason}"
    if v.get("habitat_fragmentation") == "elevated":
        reason += " Linear project crossing protected habitat raises fragmentation risk."
    return RiskScore(category="Biodiversity", level=level, reason=reason, metric_basis={
        "protected_area_overlap_pct": overlap,
        "threatened_species_count": threatened,
        "nearest_protected_area_m": v.get("nearest_protected_area_m"),
    })


def _score_water(g: MetricGroup, t: Thresholds) -> RiskScore:
    if not g.available:
        return _unknown("Water", g)
    v = g.values
    dist = v.get("nearest_river_m")
    name = v.get("nearest_river_name") or "nearest watercourse"
    if dist is None:
        return _unknown("Water", g)

    if dist < t.river_distance_high_m:
        level, reason = RiskLevel.high, f"Project lies {dist:.0f} m from {name} (<{t.river_distance_high_m:g} m)."
    elif dist < t.river_distance_medium_m:
        level, reason = RiskLevel.medium, (f"Project lies {dist:.0f} m from {name} "
                                           f"({t.river_distance_high_m:g}–{t.river_distance_medium_m:g} m).")
    else:
        level, reason = RiskLevel.low, f"Nearest watercourse ({name}) is {dist:.0f} m away (>{t.river_distance_medium_m:g} m)."
    if v.get("perennial_river_within_aoi"):
        reason += " A perennial river falls within the AOI, increasing hydrological sensitivity."
        level = _max_level(level, RiskLevel.medium)
    return RiskScore(category="Water", level=level, reason=reason, metric_basis={
        "nearest_river_m": dist,
        "perennial_river_within_aoi": v.get("perennial_river_within_aoi"),
    })


def _score_land_soil(g: MetricGroup, t: Thresholds) -> RiskScore:
    if not g.available:
        return _unknown("Land & Soil", g)
    v = g.values
    slope = v.get("mean_slope_deg")
    natural_pct = v.get("natural_vegetation_pct", 0.0) or 0.0
    veg_removal = v.get("vegetation_removal_ha")

    if slope is not None:
        if slope > t.slope_high_deg:
            slope_level, slope_reason = RiskLevel.high, f"Steep mean slope (~{slope:.1f}°) implies high erosion sensitivity."
        elif slope > t.slope_medium_deg:
            slope_level, slope_reason = RiskLevel.medium, f"Moderate mean slope (~{slope:.1f}°) implies some erosion sensitivity."
        else:
            slope_level, slope_reason = RiskLevel.low, f"Gentle terrain (~{slope:.1f}° mean slope); low erosion sensitivity."
    else:
        slope_level, slope_reason = RiskLevel.unknown, (g.note or "Slope not estimated.")

    veg_level = RiskLevel.low
    veg_reason = ""
    if veg_removal and veg_removal > 50:
        veg_level = RiskLevel.medium
        veg_reason = f" Estimated vegetation removal ~{veg_removal:.0f} ha across natural cover ({natural_pct:.0f}% of AOI)."

    level = _max_level(slope_level, veg_level)
    if level == RiskLevel.unknown:
        level = veg_level  # fall back to vegetation signal if slope missing
    return RiskScore(category="Land & Soil", level=level, reason=(slope_reason + veg_reason).strip(), metric_basis={
        "mean_slope_deg": slope,
        "vegetation_removal_ha": veg_removal,
        "natural_vegetation_pct": natural_pct,
    })


def _score_climate(g: MetricGroup, t: Thresholds) -> RiskScore:
    if not g.available:
        return _unknown("Climate", g)
    v = g.values
    total = v.get("total_estimated_emissions_tco2e", 0.0) or 0.0
    if total > t.emissions_high_tco2e:
        level, band = RiskLevel.high, f">{t.emissions_high_tco2e:,.0f}"
    elif total > t.emissions_medium_tco2e:
        level, band = RiskLevel.medium, f"{t.emissions_medium_tco2e:,.0f}–{t.emissions_high_tco2e:,.0f}"
    else:
        level, band = RiskLevel.low, f"<{t.emissions_medium_tco2e:,.0f}"
    reason = (
        f"Estimated emissions ~{total:,.0f} tCO2e ({band} tCO2e band), "
        f"of which {v.get('land_use_change_emissions_tco2e', 0):,.0f} from land-use change."
    )
    return RiskScore(category="Climate", level=level, reason=reason, metric_basis={
        "total_estimated_emissions_tco2e": total,
    })


def _score_social(g: MetricGroup, t: Thresholds) -> RiskScore:
    if not g.available:
        return _unknown("Social", g)
    v = g.values
    dist = v.get("nearest_settlement_m")
    name = v.get("nearest_settlement_name") or "nearest settlement"
    pop = v.get("population_exposed", 0) or 0
    if dist is None:
        return _unknown("Social", g)

    if dist < t.settlement_distance_high_m:
        level, reason = RiskLevel.high, f"{name} lies {dist:.0f} m from the project (<{t.settlement_distance_high_m:g} m)."
    elif dist < t.settlement_distance_medium_m:
        level, reason = RiskLevel.medium, (f"{name} lies {dist:.0f} m from the project "
                                           f"({t.settlement_distance_high_m:g}–{t.settlement_distance_medium_m:g} m).")
    else:
        level, reason = RiskLevel.low, f"Nearest settlement ({name}) is {dist:.0f} m away (>{t.settlement_distance_medium_m:g} m)."
    if pop > 0:
        reason += f" ~{pop:,} people fall within the AOI."
    return RiskScore(category="Social", level=level, reason=reason, metric_basis={
        "nearest_settlement_m": dist,
        "population_exposed": pop,
    })


def score(metrics: LayerMetrics, thresholds: Thresholds | None = None) -> tuple[list[RiskScore], RiskLevel]:
    t = thresholds or Thresholds()
    scores = [
        _score_biodiversity(metrics.biodiversity, t),
        _score_water(metrics.water, t),
        _score_land_soil(metrics.land_soil, t),
        _score_climate(metrics.climate, t),
        _score_social(metrics.social, t),
    ]
    overall = _max_level(*[s.level for s in scores])
    return scores, overall
