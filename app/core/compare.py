"""Compare two assessment results — risk deltas for scenario / threshold analysis."""
from __future__ import annotations

from app.models.schemas import AssessmentResult, ComparisonResult, RiskDelta, RiskLevel

_RANK = {RiskLevel.unknown: -1, RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}


def _direction(baseline: RiskLevel, current: RiskLevel) -> str:
    if baseline == current:
        return "same"
    if baseline == RiskLevel.unknown or current == RiskLevel.unknown:
        return "unknown"
    if _RANK[current] > _RANK[baseline]:
        return "up"
    return "down"


def compare_results(baseline: AssessmentResult, current: AssessmentResult) -> ComparisonResult:
    base_by = {s.category: s for s in baseline.risk_scores}
    curr_by = {s.category: s for s in current.risk_scores}
    categories = list(dict.fromkeys(list(base_by) + list(curr_by)))

    deltas: list[RiskDelta] = []
    for cat in categories:
        b = base_by.get(cat)
        c = curr_by.get(cat)
        b_level = b.level if b else RiskLevel.unknown
        c_level = c.level if c else RiskLevel.unknown
        deltas.append(
            RiskDelta(
                category=cat,
                baseline_level=b_level,
                current_level=c_level,
                changed=b_level != c_level,
                direction=_direction(b_level, c_level),
            )
        )

    return ComparisonResult(
        baseline_name=baseline.project.name,
        current_name=current.project.name,
        baseline_overall=baseline.overall_risk,
        current_overall=current.overall_risk,
        overall_changed=baseline.overall_risk != current.overall_risk,
        deltas=deltas,
    )
