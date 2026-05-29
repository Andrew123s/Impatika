"""Step 6 & 7 — Generate EIA report sections and the human-readable draft.

Produces the seven standard EIA sections. When an Anthropic key is configured
the prose is drafted by Claude (grounded strictly in the computed assessment);
otherwise deterministic templates render the same sections from the metrics and
risk scores. Either way the section set and ordering are identical.
"""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.llm import client as llm_client
from app.models.schemas import (
    AOI,
    EIAReport,
    LayerMetrics,
    ProjectInput,
    ReportSection,
    RiskLevel,
    RiskScore,
)

SECTIONS: list[dict[str, str]] = [
    {"id": "project_description", "title": "1. Project Description",
     "guidance": "Summarise project type, location, scale, key activities and proponent-flagged receptors."},
    {"id": "baseline_environment", "title": "2. Baseline Environment",
     "guidance": "Describe the AOI and the baseline land cover, protected areas, hydrology, settlements and species; note data gaps."},
    {"id": "impact_assessment", "title": "3. Impact Assessment",
     "guidance": "Assess impacts per environmental/social theme, citing each computed risk level and its basis."},
    {"id": "mitigation_measures", "title": "4. Mitigation Measures",
     "guidance": "Recommend mitigation following the hierarchy avoid > minimise > restore > offset, focused on Medium/High risks."},
    {"id": "esmp", "title": "5. Environmental & Social Management Plan (ESMP)",
     "guidance": "Set out management actions, responsibilities and phases addressing the identified impacts."},
    {"id": "monitoring_plan", "title": "6. Monitoring Plan",
     "guidance": "Define indicators, methods and frequencies to monitor the key impacts over the project life."},
    {"id": "conclusion", "title": "7. Conclusion & Recommendations",
     "guidance": "State the overall risk, summarise the main findings and give a clear go/conditional/further-study recommendation."},
]

# Mitigation and monitoring libraries keyed by risk category.
_MITIGATION: dict[str, list[str]] = {
    "Biodiversity": [
        "Avoid: re-align the footprint to exclude designated protected-area land where feasible.",
        "Minimise: schedule vegetation clearing outside breeding/migration seasons and retain wildlife corridors.",
        "Restore: progressively rehabilitate cleared natural habitat with indigenous species.",
        "Offset: where residual loss of critical habitat remains, develop a quantified biodiversity offset.",
    ],
    "Water": [
        "Maintain vegetated buffer strips along watercourses and prohibit works within the riparian zone.",
        "Install sediment and erosion controls (silt fences, settlement ponds) before earthworks begin.",
        "Manage construction runoff and spill risk with bunded storage and a drainage management plan.",
    ],
    "Land & Soil": [
        "Strip and stockpile topsoil for reuse; minimise the area cleared at any one time.",
        "Apply slope stabilisation and re-vegetation on disturbed ground; avoid works in heavy rain.",
        "Implement a soil erosion and sediment control plan proportionate to terrain steepness.",
    ],
    "Climate": [
        "Reduce land-use-change emissions by minimising clearing of woody vegetation and protecting carbon stocks.",
        "Adopt low-carbon construction practices and source materials locally where practical.",
        "Where material woody-biomass loss occurs, plan compensatory afforestation/restoration.",
    ],
    "Social": [
        "Conduct stakeholder consultation and disclosure with affected communities early in design.",
        "Establish a grievance redress mechanism and manage construction nuisance (dust, noise, traffic).",
        "Assess and, where unavoidable, plan resettlement/livelihood restoration in line with good practice.",
    ],
}

_MONITORING: dict[str, list[str]] = {
    "Biodiversity": ["Habitat extent and condition within AOI — quarterly during construction.",
                     "Target/threatened species presence — seasonal surveys."],
    "Water": ["Surface-water turbidity/sediment up- and down-stream — monthly during earthworks.",
              "Riparian buffer integrity — quarterly inspection."],
    "Land & Soil": ["Erosion features and rehabilitation success — after major rain events and quarterly.",
                    "Topsoil stockpile condition — monthly."],
    "Climate": ["Area of vegetation cleared vs. permitted — continuous logging.",
                "Fuel/energy use as an emissions proxy — monthly."],
    "Social": ["Grievances logged and resolved — continuous, reported monthly.",
               "Dust/noise at nearest receptors — periodic during construction."],
}


def _g(metrics: LayerMetrics, name: str) -> dict[str, Any]:
    group = getattr(metrics, name)
    return group.values if group.available else {}


def build_context(project: ProjectInput, aoi: AOI, metrics: LayerMetrics,
                  scores: list[RiskScore], overall: RiskLevel) -> dict[str, Any]:
    return {
        "project": project.model_dump(exclude={"geometry"}),
        "aoi": {"buffer_m": aoi.buffer_m, "area_ha": aoi.area_ha},
        "metrics": metrics.model_dump(),
        "risk_scores": [s.model_dump() for s in scores],
        "overall_risk": overall.value,
    }


# --- Deterministic templates -------------------------------------------------
def _t_project_description(project: ProjectInput, aoi: AOI, *_: Any) -> str:
    loc = project.location
    where = (f"{loc.lat:.4f}, {loc.lon:.4f}" if loc else "a supplied geometry")
    region = f" ({loc.region})" if loc and loc.region else ""
    scale_bits = []
    if project.scale.length_km:
        scale_bits.append(f"{project.scale.length_km} km length")
    if project.scale.area_ha:
        scale_bits.append(f"{project.scale.area_ha} ha footprint")
    if project.scale.capacity_mw:
        scale_bits.append(f"{project.scale.capacity_mw} MW capacity")
    scale = "; ".join(scale_bits) or "scale not specified"
    activities = ", ".join(project.activities) or "not specified"
    receptors = ", ".join(project.sensitive_receptors) or "none flagged by the proponent"
    return (
        f"**{project.name}** is a *{project.project_type.value.replace('_', ' ')}* project located at {where}{region}. "
        f"{project.description.strip() or ''}\n\n"
        f"Reported scale: {scale}. Key activities: {activities}. "
        f"Proponent-flagged sensitive receptors: {receptors}. "
        f"The area of influence is a {aoi.buffer_m:.0f} m buffer of the project footprint, "
        f"covering approximately {aoi.area_ha:.0f} ha."
    )


def _t_baseline(project: ProjectInput, aoi: AOI, metrics: LayerMetrics, *_: Any) -> str:
    bio, water, land, social = (
        _g(metrics, "biodiversity"), _g(metrics, "water"), _g(metrics, "land_soil"), _g(metrics, "social")
    )
    lines = [f"The baseline is characterised within the {aoi.area_ha:.0f} ha AOI."]

    if land:
        comp = land.get("land_cover_composition", [])
        top = "; ".join(f"{c['class']} ({c['pct']:.0f}%)" for c in comp[:4])
        lines.append(f"- **Land cover**: dominated by {land.get('dominant_land_cover')}. Composition: {top}. "
                     f"Natural vegetation makes up ~{land.get('natural_vegetation_pct', 0):.0f}% of the AOI.")
        if land.get("mean_slope_deg") is not None:
            lines.append(f"- **Terrain**: mean slope ~{land['mean_slope_deg']:.1f}° (relief ~{land.get('terrain_relief_m', 0):.0f} m).")
    else:
        lines.append("- **Land cover/terrain**: data unavailable.")

    if bio:
        pas = bio.get("protected_areas", [])
        if pas:
            names = "; ".join(f"{p['name']} ({p['overlap_ha'] or 0:.0f} ha overlap)" for p in pas)
            lines.append(f"- **Protected areas**: {names}. AOI overlap {bio.get('protected_area_overlap_pct', 0):.1f}%.")
        ts = bio.get("threatened_species", [])
        if ts:
            lines.append("- **Species**: threatened taxa recorded — " +
                         ", ".join(f"{s['common_name']} ({s['iucn_status']})" for s in ts) + ".")
    else:
        lines.append("- **Biodiversity**: protected-area data unavailable.")

    if water:
        lines.append(f"- **Hydrology**: nearest watercourse is {water.get('nearest_river_name')} "
                     f"at ~{water.get('nearest_river_m', 0):.0f} m. "
                     f"Rivers within AOI: {', '.join(water.get('rivers_within_aoi', [])) or 'none'}.")
    if social:
        lines.append(f"- **Settlements**: nearest is {social.get('nearest_settlement_name')} "
                     f"at ~{social.get('nearest_settlement_m', 0):.0f} m; "
                     f"~{social.get('population_exposed', 0):,} people within AOI.")
    lines.append("\n*Data gaps*: floodplain, water-scarcity and cultural-heritage layers were not available and are flagged as not assessed.")
    return "\n".join(lines)


def _t_impact(_p: ProjectInput, _a: AOI, _m: LayerMetrics, scores: list[RiskScore], *_: Any) -> str:
    lines = ["Impacts are assessed per theme using rule-based thresholds on the computed metrics:\n"]
    for s in scores:
        lines.append(f"- **{s.category} — {s.level.value} risk**: {s.reason}")
    return "\n".join(lines)


def _t_mitigation(_p: ProjectInput, _a: AOI, _m: LayerMetrics, scores: list[RiskScore], *_: Any) -> str:
    relevant = [s for s in scores if s.level in (RiskLevel.high, RiskLevel.medium)]
    if not relevant:
        return "All themes scored Low risk; standard good-practice construction controls are sufficient. No theme-specific mitigation is triggered."
    blocks = ["Mitigation follows the hierarchy **avoid > minimise > restore > offset**, prioritising Medium/High themes:\n"]
    for s in relevant:
        measures = _MITIGATION.get(s.category, [])
        blocks.append(f"**{s.category} ({s.level.value})**")
        blocks.extend(f"  - {m}" for m in measures)
    return "\n".join(blocks)


def _t_esmp(_p: ProjectInput, _a: AOI, _m: LayerMetrics, scores: list[RiskScore], *_: Any) -> str:
    lines = ["The ESMP assigns management actions across project phases. Suggested responsibilities:\n",
             "| Theme | Risk | Lead responsibility | Phase |",
             "|---|---|---|---|"]
    role = {"Biodiversity": "Environmental Officer", "Water": "Environmental Officer",
            "Land & Soil": "Site/Civil Engineer", "Climate": "Environmental Officer",
            "Social": "Community Liaison Officer"}
    for s in scores:
        phase = "Pre-construction & construction" if s.level in (RiskLevel.high, RiskLevel.medium) else "Construction"
        lines.append(f"| {s.category} | {s.level.value} | {role.get(s.category, 'Environmental Officer')} | {phase} |")
    lines.append("\nAn overarching Environmental & Social Management System should integrate these actions, "
                 "with a designated Environmental Manager accountable for implementation and reporting.")
    return "\n".join(lines)


def _t_monitoring(_p: ProjectInput, _a: AOI, _m: LayerMetrics, scores: list[RiskScore], *_: Any) -> str:
    lines = ["Monitoring indicators and frequencies, focused on the themes carrying material risk:\n"]
    for s in scores:
        if s.level == RiskLevel.low:
            continue
        items = _MONITORING.get(s.category, [])
        lines.append(f"**{s.category}**")
        lines.extend(f"  - {it}" for it in items)
    if len(lines) == 1:
        lines.append("All themes Low risk; baseline compliance monitoring (clearing extents, runoff, grievances) is sufficient.")
    return "\n".join(lines)


def _t_conclusion(_p: ProjectInput, _a: AOI, _m: LayerMetrics, scores: list[RiskScore], overall: RiskLevel) -> str:
    highs = [s.category for s in scores if s.level == RiskLevel.high]
    meds = [s.category for s in scores if s.level == RiskLevel.medium]
    unknowns = [s.category for s in scores if s.level == RiskLevel.unknown]
    if overall == RiskLevel.high:
        rec = ("The project carries **High** overall environmental risk. It should proceed only subject to detailed "
               "studies on the high-risk themes and implementation of the full mitigation and monitoring measures above.")
    elif overall == RiskLevel.medium:
        rec = ("The project carries **Medium** overall environmental risk and may proceed subject to the recommended "
               "mitigation, an approved ESMP and the monitoring plan.")
    elif overall == RiskLevel.low:
        rec = "The project carries **Low** overall environmental risk; standard good-practice controls and routine monitoring are recommended."
    else:
        rec = "Overall risk could not be fully determined owing to data gaps; further data collection is recommended before a decision."
    parts = [rec]
    if highs:
        parts.append(f"High-risk themes requiring particular attention: {', '.join(highs)}.")
    if meds:
        parts.append(f"Medium-risk themes: {', '.join(meds)}.")
    if unknowns:
        parts.append(f"Themes not scored due to missing data: {', '.join(unknowns)} — collect these datasets to close the gap.")
    parts.append("This is a screening-level assessment and environmental guidance only; it is not legal advice.")
    return " ".join(parts)


_TEMPLATES = {
    "project_description": _t_project_description,
    "baseline_environment": _t_baseline,
    "impact_assessment": _t_impact,
    "mitigation_measures": _t_mitigation,
    "esmp": _t_esmp,
    "monitoring_plan": _t_monitoring,
    "conclusion": _t_conclusion,
}


def generate_report(project: ProjectInput, aoi: AOI, metrics: LayerMetrics,
                    scores: list[RiskScore], overall: RiskLevel) -> EIAReport:
    context = build_context(project, aoi, metrics, scores, overall)
    llm_sections = llm_client.generate_report_sections(context, SECTIONS, model=settings.impatika_model)

    sections: list[ReportSection] = []
    used_llm = bool(llm_sections)
    for spec in SECTIONS:
        body = (llm_sections or {}).get(spec["id"])
        if not body:
            body = _TEMPLATES[spec["id"]](project, aoi, metrics, scores, overall)
        sections.append(ReportSection(title=spec["title"], body=body.strip()))

    return EIAReport(generator="llm" if used_llm else "template", sections=sections)
