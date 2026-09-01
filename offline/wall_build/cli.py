"""CLI adapter for `rockvision build <wall_id>`."""

from __future__ import annotations

from pathlib import Path

from .orchestrator import run_wall_build
from .states import RunTerminalStatus


def run_build(wall_id: str, root: Path) -> int:
    report = run_wall_build(wall_id, root)
    terminal = report.get("runTerminalStatus")
    print(f"Wall ID: {report.get('wallId')}")
    print(f"runId: {report.get('runId')}")
    print(f"RUN_TERMINAL_STATUS: {terminal}")
    print(f"AUTOMATION_REACHED: {report.get('automationReached')}")
    print(f"NEXT_STAGE: {report.get('nextStage')}")
    print(f"NEXT_STAGE_STATUS: {report.get('nextStageStatus')}")
    print(f"FIELD_TEST_READY: {report.get('fieldTestReadyLabel')}")
    print(f"genericStage2Pass: {report.get('genericStage2Pass')}")
    print(f"productionBuildStage2Enabled: {report.get('productionBuildStage2Enabled')}")
    print(f"Wrote {report.get('runOutputDir')}/wall_build_report.json")
    print(f"Wrote {report.get('runOutputDir')}/wall_build_report.md")
    if terminal == RunTerminalStatus.AUTO_FAIL.value:
        return 1
    if terminal == RunTerminalStatus.HUMAN_REVIEW_REQUIRED.value:
        return 2
    return 0
