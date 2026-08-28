"""Development-only Generic Stage 2 entry. Not ordinary production build."""

from .runner import (
    DEVELOPMENT_ONLY,
    NOT_PRODUCTION_BUILD,
    run_register_selected,
    run_select,
)

__all__ = [
    "DEVELOPMENT_ONLY",
    "NOT_PRODUCTION_BUILD",
    "run_select",
    "run_register_selected",
]
