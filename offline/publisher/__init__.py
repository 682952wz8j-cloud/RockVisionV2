"""Immutable COS Publisher v1.

Separate capability from backend runtime COS read and from package validation.
Fake COS is required for tests. Real COS write is not performed by tests.
"""

from .pipeline import PublishResult, publish_localization_package
from .schema import PublicationState, ReasonCode

__all__ = [
    "PublicationState",
    "PublishResult",
    "ReasonCode",
    "publish_localization_package",
]
