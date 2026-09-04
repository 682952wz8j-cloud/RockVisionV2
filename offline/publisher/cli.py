"""High-friction CLI for immutable localization-package publish.

Requires exact wallId, exact releaseId, and --approve.
Does not infer latest. Does not update catalog.
"""

from __future__ import annotations

import os
from pathlib import Path

from offline.localization_package.layout import package_dir as default_package_dir

from .config import PublisherConfigError, load_publisher_config, redact_text, resolve_env_file
from .pipeline import PublishResult, evaluate_local_publish_gate, execute_remote_publish, publish_localization_package
from .schema import TERMINAL_SUCCESS
from .store import ObjectStore
from .tencent_store import TencentPublisherStore


def run_publish_localization_package(
    wall_id: str,
    release_id: str,
    *,
    approve: bool,
    root: Path,
    package_dir: Path | None = None,
    store: ObjectStore | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    dest = package_dir if package_dir is not None else default_package_dir(root, wall_id, release_id)
    env = environ if environ is not None else dict(os.environ)
    if not approve:
        result = publish_localization_package(
            wall_id=wall_id,
            release_id=release_id,
            package_dir=dest,
            approve=False,
            store=None,
        )
        _print_not_authorized(wall_id, release_id, dest)
        _print_result(result, env)
        return 1

    gate = evaluate_local_publish_gate(
        wall_id=wall_id,
        release_id=release_id,
        package_dir=dest,
        approve=True,
    )
    _print_prewrite_summary(gate.result, dest)
    if not gate.local_ok:
        _print_result(gate.result, env)
        return 1

    if store is None:
        try:
            env_file = resolve_env_file(env, default_if_exists=True)
            config = load_publisher_config(env, env_file=env_file)
            store = TencentPublisherStore.from_config(config)
        except PublisherConfigError:
            print("STOP: publisher CAM configuration missing")
            print("Use CRAGPAL_PUBLISHER_* or an explicit publisher env file.")
            print("Runtime TENCENT_* identity is not a publisher identity.")
            return 1

    result = execute_remote_publish(gate, store)
    _print_result(result, env)
    return 0 if result.state in {item.value for item in TERMINAL_SUCCESS} else 1


def _print_not_authorized(wall_id: str, release_id: str, package_dir: Path) -> None:
    print("STOP: publish not authorized")
    print("Exact wallId, exact releaseId, and --approve are required.")
    print("No COS calls were made.")
    print(f"wallId: {wall_id}")
    print(f"releaseId: {release_id}")
    print(f"package path: {package_dir}")


def _print_prewrite_summary(result: PublishResult, package_dir: Path) -> None:
    print("PRODUCTION LOCALIZATION PACKAGE PUBLISH")
    print("Immutable COS release. Catalog is NOT updated.")
    print(f"wallId: {result.wall_id}")
    print(f"releaseId: {result.release_id}")
    print(f"package path: {package_dir}")
    print(f"asset count: {result.asset_count}")
    print(f"destination prefix: {result.destination_prefix}")
    print(f"PACKAGE_READY: {_yn(result.package_ready)}")
    print(f"LOCALIZATION_READY: {_yn(result.localization_ready)}")
    print(f"ROUTE_AR_READY: {_yn(result.route_ar_ready)}")
    print(f"PUBLISH_APPROVED: {_yn(result.publish_approved)}")
    print(f"CATALOG_DISCOVERABLE: {_yn(result.catalog_discoverable)}")


def _print_result(result: PublishResult, environ: dict[str, str]) -> None:
    line = f"publicationState: {result.state}"
    if result.reason_code:
        line += f" reasonCode: {result.reason_code}"
    print(redact_text(line, environ))
    print(f"PUBLISHED_RELEASE: {_yn(result.published_release)}")
    print(f"CATALOG_DISCOVERABLE: {_yn(result.catalog_discoverable)}")


def _yn(value: bool) -> str:
    return "YES" if value else "NO"
