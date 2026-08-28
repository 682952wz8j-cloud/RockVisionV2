"""Deterministic wall_id path checks. Same rules for every wall."""

from __future__ import annotations

import re

from .states import ReasonCode

# Applied equally to every wall. Not a Jinshidong special case.
WALL_ID_PATTERN = re.compile(r"^wall_[A-Za-z0-9][A-Za-z0-9_-]*$")


def wall_id_error(wall_id: str) -> ReasonCode | None:
    if not wall_id or not isinstance(wall_id, str):
        return ReasonCode.INVALID_WALL_ID
    if wall_id in {".", ".."}:
        return ReasonCode.UNSAFE_WALL_PATH
    if "/" in wall_id or "\\" in wall_id or ".." in wall_id:
        return ReasonCode.UNSAFE_WALL_PATH
    if wall_id.startswith(".") or wall_id.startswith("-"):
        return ReasonCode.INVALID_WALL_ID
    if not WALL_ID_PATTERN.fullmatch(wall_id):
        return ReasonCode.INVALID_WALL_ID
    return None
