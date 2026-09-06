"""Gate-aware wall build orchestrator.

Executable stages: DISCOVERY through METRIC_REGISTRATION, then this-run
REFERENCE_MAP / REFERENCE_MATCH / pinned PnP. Stops before publish.
Legacy register and route stages remain locked.
"""

from .orchestrator import run_wall_build

__all__ = ["run_wall_build"]
