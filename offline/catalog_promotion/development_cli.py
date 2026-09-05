"""High-friction CLI for development_test promotion records.

Separate from promote-localization-release. Always environment=development_test.
Requires exact wallId, exact releaseId, --name, and --approve.
Does not infer latest. Does not rewrite immutable releases.
Does not write published/catalog.json. Does not claim production qualification.
"""

from __future__ import annotations

import os

from offline.publisher.config import PublisherConfigError, load_publisher_config, resolve_env_file
from offline.publisher.keys import PublisherKeyError, published_promotion_key
from offline.publisher.store import PromotionStore
from offline.publisher.tencent_promotion_store import TencentPromotionStore

from .cli import _print_result
from .development_promotion import (
    DEVELOPMENT_TEST_ENVIRONMENT,
    DEVELOPMENT_TEST_NOT_PRODUCTION_QUALIFIED,
    promote_development_test_release,
)
from .schema import TERMINAL_SUCCESS


def run_promote_development_test_release(
    wall_id: str,
    release_id: str,
    *,
    name: str,
    approve: bool,
    store: PromotionStore | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    env = environ if environ is not None else dict(os.environ)
    if not approve:
        result = promote_development_test_release(
            wall_id=wall_id,
            release_id=release_id,
            name=name,
            approve=False,
            store=None,
        )
        print("STOP: development_test catalog promotion not authorized")
        print("Exact wallId, exact releaseId, --name, and --approve are required.")
        print("This command does not qualify production.")
        print("No COS writes were made.")
        _print_result(result, env)
        return 1

    print("DEVELOPMENT_TEST LOCALIZATION RELEASE PROMOTION")
    print("This is NOT a production promotion.")
    print("LOCALIZATION_CAPABLE != PRODUCTION_QUALIFIED")
    print("Immutable promotion record. published/catalog.json is not written.")
    print(f"environment: {DEVELOPMENT_TEST_ENVIRONMENT}")
    print(f"PRODUCTION_QUALIFIED: {'NO' if DEVELOPMENT_TEST_NOT_PRODUCTION_QUALIFIED else 'YES'}")
    print(f"wallId: {wall_id}")
    print(f"releaseId: {release_id}")
    print(f"name: {name}")
    print("PROMOTION_APPROVED: YES")
    try:
        print(f"PROMOTION_KEY: {published_promotion_key(wall_id, release_id)}")
    except PublisherKeyError:
        print("PROMOTION_KEY: (invalid wallId or releaseId)")

    if store is None:
        try:
            env_file = resolve_env_file(env, default_if_exists=True)
            config = load_publisher_config(env, env_file=env_file)
            store = TencentPromotionStore.from_config(config)
        except PublisherConfigError:
            print("STOP: publisher CAM configuration missing")
            print("Runtime TENCENT_* identity is not a publisher identity.")
            return 1

    result = promote_development_test_release(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        approve=True,
        store=store,
    )
    _print_result(result, env)
    return 0 if result.state in {item.value for item in TERMINAL_SUCCESS} else 1
