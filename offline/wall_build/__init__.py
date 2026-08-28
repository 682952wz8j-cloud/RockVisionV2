"""Phase 1 gate-aware wall build orchestrator.

Executable stages: DISCOVERY, PREFLIGHT, INGEST, QUALIFY.
Later stages are capability / Gate checks only and are never invoked.
"""

from .orchestrator import run_wall_build

__all__ = ["run_wall_build"]
