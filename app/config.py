"""Configuration: environment settings plus the deterministic constants
(buffer distances and risk thresholds) that drive Impatika's rule-based core.

Keeping thresholds here — not scattered through the code — makes the scoring
auditable and easy to tune, which matters for a transparent EIA tool.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data" / "sample"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore"
    )

    anthropic_api_key: str = ""
    impatika_model: str = "claude-opus-4-7"
    impatika_data_dir: str = ""

    @property
    def data_dir(self) -> Path:
        return Path(self.impatika_data_dir) if self.impatika_data_dir else DEFAULT_DATA_DIR


settings = Settings()


# --- AOI buffer distances (metres) keyed by project type ---------------------
# Sourced from the Impatika spec. Linear projects buffer wider than point/area
# projects because their impact corridor is longer.
BUFFER_METRES: dict[str, float] = {
    "road": 1000.0,
    "pipeline": 1000.0,
    "solar_farm": 500.0,
    "wind_farm": 1000.0,
    "dam": 5000.0,
    "mine": 2000.0,
    "building": 300.0,
    "other": 500.0,
}
DEFAULT_BUFFER_METRES = 500.0


# --- Risk thresholds ---------------------------------------------------------
# Each entry documents the rule applied in scoring.py. Editing a number here
# changes the published risk logic — intentionally the single source of truth.

# Biodiversity: protected-area overlap as a fraction of AOI area.
PROTECTED_OVERLAP_HIGH = 0.10   # >10% overlap -> High
PROTECTED_OVERLAP_MEDIUM = 0.01  # >1% overlap -> Medium

# Water: distance from project geometry to nearest river (metres).
RIVER_DISTANCE_HIGH_M = 100.0    # <100 m -> High
RIVER_DISTANCE_MEDIUM_M = 500.0  # <500 m -> Medium

# Social: distance to nearest settlement (metres).
SETTLEMENT_DISTANCE_HIGH_M = 500.0     # <500 m -> High
SETTLEMENT_DISTANCE_MEDIUM_M = 2000.0  # <2 km -> Medium

# Land/soil: mean terrain slope (degrees) as an erosion-sensitivity proxy.
SLOPE_HIGH_DEG = 25.0    # steep -> High erosion sensitivity
SLOPE_MEDIUM_DEG = 10.0

# Climate: estimated land-use-change + activity emissions (tonnes CO2e).
EMISSIONS_HIGH_TCO2E = 50_000.0
EMISSIONS_MEDIUM_TCO2E = 5_000.0
