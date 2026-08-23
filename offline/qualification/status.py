from __future__ import annotations

from enum import Enum


class ProvenanceStatus(str, Enum):
    PROVEN = "PROVEN"
    SUPPORTED = "SUPPORTED"
    UNKNOWN = "UNKNOWN"
    CONTRADICTED = "CONTRADICTED"


def claim(status: ProvenanceStatus | str, statement: str, evidence: list[str]) -> dict:
    value = status.value if isinstance(status, ProvenanceStatus) else status
    return {"status": value, "statement": statement, "evidence": evidence}
