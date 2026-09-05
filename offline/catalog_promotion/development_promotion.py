"""Future development_test promotion contract.

D6A defines the classified environment vocabulary only. This module is
the separate boundary for a later development_test promotion path.

It is not wired to the production promoter. It is not a hidden
bypass flag on the production promoter. Production qualification gates stay
on the production path.
"""

from __future__ import annotations

from offline.localization_package.schema import ENVIRONMENT_DEVELOPMENT_TEST


class DevelopmentPromotionNotImplemented(RuntimeError):
    """development_test promotion is a later explicit phase."""


def promote_development_test_release(**_kwargs):
    """Do not call this from the production promoter.

    Future D6B may implement immutable development_test promotion records
    after production qualification remains fail-closed.
    """
    raise DevelopmentPromotionNotImplemented(
        "development_test promotion is a separate contract; not implemented in D6A"
    )


DEVELOPMENT_TEST_ENVIRONMENT = ENVIRONMENT_DEVELOPMENT_TEST
DEVELOPMENT_TEST_NOT_PRODUCTION_QUALIFIED = True
