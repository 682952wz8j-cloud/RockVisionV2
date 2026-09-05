"""Catalog Promotion: append-only immutable promotion records.

Separate explicit operation after immutable publication.
Catalog v1 is a projection, not a mutable COS object.

Production promotion and development_test promotion are separate
fail-closed paths. Development promotion does not qualify production.
"""

from .development_promotion import promote_development_test_release
from .pipeline import PromotionResult, promote_localization_release
from .projector import ProjectionError, project_catalog
from .schema import PromotionState, ReasonCode

__all__ = [
    "ProjectionError",
    "PromotionResult",
    "PromotionState",
    "ReasonCode",
    "project_catalog",
    "promote_development_test_release",
    "promote_localization_release",
]
