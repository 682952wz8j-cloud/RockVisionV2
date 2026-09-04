"""High-friction CLI for immutable promotion records.

Requires exact wallId, exact releaseId, --name, and --approve.
Does not infer latest. Does not rewrite immutable releases.
Does not write published/catalog.json.
"""

from __future__ import annotations

import os

from offline.publisher.config import PublisherConfigError, load_publisher_config, redact_text, resolve_env_file
from offline.publisher.keys import PublisherKeyError, published_promotion_key
from offline.publisher.store import PromotionStore
from offline.publisher.tencent_promotion_store import TencentPromotionStore

from .pipeline import PromotionResult, promote_localization_release
from .schema import TERMINAL_SUCCESS


def run_promote_localization_release(
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
        result = promote_localization_release(
            wall_id=wall_id,
            release_id=release_id,
            name=name,
            approve=False,
            store=None,
        )
        print("STOP: catalog promotion not authorized")
        print("Exact wallId, exact releaseId, --name, and --approve are required.")
        print("No COS writes were made.")
        _print_result(result, env)
        return 1

    print("PRODUCTION LOCALIZATION RELEASE PROMOTION")
    print("Immutable promotion record. published/catalog.json is not written.")
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

    result = promote_localization_release(
        wall_id=wall_id,
        release_id=release_id,
        name=name,
        approve=True,
        store=store,
    )
    _print_result(result, env)
    return 0 if result.state in {item.value for item in TERMINAL_SUCCESS} else 1


def _print_result(result: PromotionResult, environ: dict[str, str]) -> None:
    line = f"promotionState: {result.state}"
    if result.reason_code:
        line += f" reasonCode: {result.reason_code}"
    print(redact_text(line, environ))
    print(f"REMOTE_RELEASE_VALIDATED: {_yn(result.remote_release_validated)}")
    print(f"PROMOTION_RECORD_CREATED: {_yn(result.promotion_record_created)}")
    print(f"CATALOG_DISCOVERABLE: {_yn(result.catalog_discoverable)}")
    print(f"promotionPuts: {len(result.puts)}")


def _yn(value: bool) -> str:
    return "YES" if value else "NO"
