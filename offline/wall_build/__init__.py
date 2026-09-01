"""Gate-aware wall build orchestrator.

Executable stages: DISCOVERY, PREFLIGHT, INGEST, QUALIFY,
STAGE2_SELECTION, HEIGHT_VERTICAL_DATUM, POSITIONING_QUALITY,
RECONSTRUCTION, METRIC_REGISTRATION.
Stage 3 / route stages remain locked.
"""

from .orchestrator import run_wall_build

__all__ = ["run_wall_build"]
