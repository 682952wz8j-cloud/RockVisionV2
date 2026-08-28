"""Machine-readable and human-readable Phase 1 run reports."""

from __future__ import annotations

import json
from pathlib import Path


def write_reports(run_dir: Path, report: dict) -> tuple[Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    machine = run_dir / "wall_build_report.json"
    human = run_dir / "wall_build_report.md"
    machine.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    human.write_text(render_markdown(report), encoding="utf-8")
    return machine, human


def render_markdown(report: dict) -> str:
    stages = report.get("stageStatuses") or {}
    lines = [
        "# Wall build report (Phase 1)",
        "",
        f"- runId: `{report.get('runId')}`",
        f"- wallId: `{report.get('wallId')}`",
        f"- runStartTime: {report.get('runStartTime')}",
        f"- runEndTime: {report.get('runEndTime')}",
        f"- runDurationSeconds: {report.get('runDurationSeconds')}",
        f"- RUN_TERMINAL_STATUS: **{report.get('runTerminalStatus')}**",
        f"- AUTOMATION_REACHED: `{report.get('automationReached')}`",
        f"- NEXT_STAGE: `{report.get('nextStage')}`",
        f"- NEXT_STAGE_STATUS: `{report.get('nextStageStatus')}`",
        f"- FIELD_TEST_READY: `{report.get('fieldTestReady')}`",
        f"- JINSHIDONG_UNATTENDED_TO_FIELD_TEST_READY: `{report.get('jinshidongUnattendedToFieldTestReady')}`",
        "",
        "## Stage statuses",
        "",
    ]
    for name, payload in stages.items():
        status = payload.get("status") if isinstance(payload, dict) else payload
        reason = ""
        if isinstance(payload, dict):
            reason = payload.get("reasonCode") or ""
        extra = f" ({reason})" if reason else ""
        lines.append(f"- {name}: `{status}`{extra}")
    lines.extend(
        [
            "",
            "## Inventory",
            "",
            f"- discoveredFileCount: {report.get('discoveredFileCount')}",
            f"- captureCandidates: {len(report.get('captureCandidates') or [])}",
            f"- mrkCandidates: {len(report.get('mrkCandidates') or [])}",
            f"- metadataCandidates: {len(report.get('metadataCandidates') or [])}",
            f"- modelCandidates: {len(report.get('modelCandidates') or [])}",
            f"- dxfFiles: {len(report.get('dxfFiles') or [])}",
            f"- ignoredUnknownFiles: {len(report.get('ignoredUnknownFiles') or [])}",
            "",
            "## Reason codes",
            "",
        ]
    )
    for code in report.get("reasonCodes") or []:
        lines.append(f"- `{code}`")
    if report.get("blockingEvidence"):
        lines.extend(["", "## Blocking evidence", ""])
        for item in report["blockingEvidence"]:
            lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Efficiency",
            "",
        ]
    )
    eff = report.get("efficiency") or {}
    for key, value in eff.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)
