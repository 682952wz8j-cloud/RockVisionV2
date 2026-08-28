"""Generic Stage 2 input discovery, grouping, and selection.

This layer changes source selection and parameterization only.
It does not reimplement COLMAP or metric-registration mathematics.
"""

from .select import select_stage2_inputs
from .sources import Stage2SelectedSources, sources_from_selection

__all__ = [
    "select_stage2_inputs",
    "Stage2SelectedSources",
    "sources_from_selection",
]
