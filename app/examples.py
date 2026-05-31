"""A worked example project that overlaps the bundled sample layers, used as
the default request body in the API docs and by the test suite."""
from __future__ import annotations

from app.models.schemas import ProjectInput, ProjectScale

EXAMPLE_PROJECT = ProjectInput(
    name="Southern Bypass Road Extension (demo)",
    description=(
        "A two-lane bypass road extension passing along the edge of a national park "
        "and crossing a perennial river, near a peri-urban settlement."
    ),
    project_type="road",
    geometry={
        "type": "LineString",
        "coordinates": [[36.78, -1.33], [36.85, -1.37], [36.92, -1.40]],
    },
    scale=ProjectScale(length_km=17.5),
    activities=["land clearing", "earthworks", "excavation", "bridge construction"],
    sensitive_receptors=["adjacent national park", "perennial river crossing"],
)
