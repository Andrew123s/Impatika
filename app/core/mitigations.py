"""Deterministic mitigation measures derived from risk scores.

Each recommendation is tied to a scored theme and priority level. Measures are
template-based (no LLM) so they stay auditable alongside the rule-based scores.
"""
from __future__ import annotations

from app.models.schemas import Mitigation, ProjectInput, RiskLevel, RiskScore

# category -> risk level -> list of measure strings
_MEASURES: dict[str, dict[RiskLevel, list[str]]] = {
    "Biodiversity": {
        RiskLevel.high: [
            "Avoid or reroute works to minimise overlap with protected areas; seek offset or restoration if unavoidable.",
            "Commission a qualified ecologist for a biodiversity baseline and species-specific management plan.",
            "Implement construction exclusion zones, wildlife crossings, and seasonal work restrictions during breeding periods.",
        ],
        RiskLevel.medium: [
            "Conduct a rapid biodiversity survey and update the species register before ground-breaking.",
            "Restore disturbed habitats with native species and monitor recolonisation for at least two growing seasons.",
        ],
        RiskLevel.low: [
            "Maintain routine ecological monitoring and report any unexpected species records to regulators.",
        ],
        RiskLevel.unknown: [
            "Obtain authoritative biodiversity layers and complete a screening survey before detailed design.",
        ],
    },
    "Water": {
        RiskLevel.high: [
            "Design erosion and sediment control (silt fences, settlement ponds) sized for peak flows at river crossings.",
            "Prohibit fuel, chemicals, and spoil storage within riparian buffers; prepare a spill response plan.",
            "Schedule in-stream works only in agreed low-flow windows with fisheries/water-agency approval.",
        ],
        RiskLevel.medium: [
            "Install and maintain temporary drainage diversions to keep turbid runoff out of surface waters.",
            "Monitor downstream turbidity during earthworks and suspend works if thresholds are exceeded.",
        ],
        RiskLevel.low: [
            "Inspect drainage controls weekly during construction and after major rainfall events.",
        ],
        RiskLevel.unknown: [
            "Map surface water features from authoritative hydrography before finalising the drainage design.",
        ],
    },
    "Land & Soil": {
        RiskLevel.high: [
            "Stabilise steep slopes with geotextiles, terracing, or retaining structures before bulk earthworks.",
            "Stockpile topsoil separately and respread to support revegetation on completion.",
            "Limit simultaneous disturbance footprint and phase works to reduce erosion exposure.",
        ],
        RiskLevel.medium: [
            "Apply cover crops or mulch on exposed soils within 48 hours of stripping vegetation.",
            "Revegetate disturbed areas with locally appropriate species matched to land-cover classes.",
        ],
        RiskLevel.low: [
            "Document soil handling procedures in the construction environmental management plan.",
        ],
        RiskLevel.unknown: [
            "Commission a terrain and soils desk study using a current DEM and land-cover dataset.",
        ],
    },
    "Climate": {
        RiskLevel.high: [
            "Prioritise low-carbon materials, renewable on-site power, and efficient equipment to cut construction emissions.",
            "Quantify land-use-change GHG losses and evaluate avoidance, minimisation, and compensation options.",
            "Set measurable GHG reduction targets and report progress in quarterly environmental reports.",
        ],
        RiskLevel.medium: [
            "Prepare a simplified GHG inventory for construction and early operations; track against benchmarks.",
            "Protect high-carbon land covers (woodland, wetland) and prefer previously disturbed sites.",
        ],
        RiskLevel.low: [
            "Include energy-efficiency measures in facility design and track operational emissions post-commissioning.",
        ],
        RiskLevel.unknown: [
            "Complete a screening-level GHG estimate once land-cover and activity data are confirmed.",
        ],
    },
    "Social": {
        RiskLevel.high: [
            "Establish a stakeholder engagement plan with affected communities before construction starts.",
            "Implement noise, dust, and traffic management with complaint hotline and response timelines.",
            "Develop a livelihood restoration or compensation framework where displacement or access loss occurs.",
        ],
        RiskLevel.medium: [
            "Communicate construction schedules, haul routes, and safety measures to nearby settlements.",
            "Provide local employment and procurement opportunities where feasible.",
        ],
        RiskLevel.low: [
            "Maintain a community liaison officer and publish periodic project environmental updates.",
        ],
        RiskLevel.unknown: [
            "Update settlement and population datasets (e.g. GHSL/WorldPop) for the AOI before social baselining.",
        ],
    },
}


def recommend(scores: list[RiskScore], project: ProjectInput | None = None) -> list[Mitigation]:
    """Return prioritised mitigation measures for non-low risk themes."""
    out: list[Mitigation] = []
    priority_for = {
        RiskLevel.high: "High",
        RiskLevel.medium: "Medium",
        RiskLevel.low: "Low",
        RiskLevel.unknown: "Medium",
    }
    for score in scores:
        if score.level == RiskLevel.low:
            continue
        measures = _MEASURES.get(score.category, {}).get(score.level, [])
        for measure in measures:
            out.append(
                Mitigation(
                    category=score.category,
                    priority=priority_for[score.level],
                    measure=measure,
                    linked_risk=score.level.value,
                )
            )
    if project and project.sensitive_receptors:
        for receptor in project.sensitive_receptors:
            out.append(
                Mitigation(
                    category="Cross-cutting",
                    priority="High",
                    measure=f"Proponent-flagged sensitive receptor: {receptor}. Document specific avoidance, monitoring, and contingency measures.",
                    linked_risk="Flagged",
                )
            )
    return out
