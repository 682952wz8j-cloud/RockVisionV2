"""Catalog Promotion v1.

Separate explicit operation after immutable publication.
Fake-store tests only in this phase. No real COS catalog write.
"""

from .pipeline import PromotionResult, promote_localization_release
from .schema import PromotionState, ReasonCode

__all__ = [
    "PromotionResult",
    "PromotionState",
    "ReasonCode",
    "promote_localization_release",
]
