"""Catalog Promotion: append-only immutable promotion records.

Separate explicit operation after immutable publication.
Catalog v1 is a projection, not a mutable COS object.
Fake-store tests only in this phase. No real COS promotion write.
"""

from .pipeline import PromotionResult, promote_localization_release
from .projector import ProjectionError, project_catalog
from .schema import PromotionState, ReasonCode

__all__ = [
    "ProjectionError",
    "PromotionResult",
    "PromotionState",
    "ReasonCode",
    "project_catalog",
    "promote_localization_release",
]
