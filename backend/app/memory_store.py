"""In-memory published catalog for tests. Synthetic fixtures only."""

from __future__ import annotations

import copy
import hashlib

from .contract import (
    CATALOG_SCHEMA,
    MANIFEST_SCHEMA,
    assert_manifest_identity,
    require_asset_id,
    require_release_id,
    require_wall_id,
    validate_catalog,
)
from .store import NotFound

EXAMPLE_WALL_ID = "wall_example_01"
EXAMPLE_RELEASE_ID = "r000001"
EXAMPLE_RELEASE_ID_2 = "r000002"
EXAMPLE_ASSET_ID = "reference-map"
EXAMPLE_ASSET_TYPE = "reference_map"
EXAMPLE_ASSET_BYTES = b"cragpal-example-reference-map-v1\n"
EXAMPLE_ASSET_BYTES_V2 = b"cragpal-example-reference-map-v2\n"
EXAMPLE_ASSET_SHA256 = hashlib.sha256(EXAMPLE_ASSET_BYTES).hexdigest()
EXAMPLE_ASSET_SHA256_V2 = hashlib.sha256(EXAMPLE_ASSET_BYTES_V2).hexdigest()
EXAMPLE_CREATED_AT = "2026-09-02T15:30:00Z"


def example_catalog(*, latest_release_id: str = EXAMPLE_RELEASE_ID) -> dict:
    return {
        "schema": CATALOG_SCHEMA,
        "walls": [
            {
                "wallId": EXAMPLE_WALL_ID,
                "name": "Example Wall",
                "latestReleaseId": latest_release_id,
            }
        ],
    }


def example_manifest(
    *,
    release_id: str = EXAMPLE_RELEASE_ID,
    payload: bytes = EXAMPLE_ASSET_BYTES,
    created_at: str = EXAMPLE_CREATED_AT,
) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "wallId": EXAMPLE_WALL_ID,
        "releaseId": release_id,
        "createdAt": created_at,
        "assets": [
            {
                "assetId": EXAMPLE_ASSET_ID,
                "type": EXAMPLE_ASSET_TYPE,
                "required": True,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        ],
    }


class MemoryStore:
    """Explicitly published synthetic releases. Does not scan the RockVision tree."""

    def __init__(
        self,
        *,
        catalog: dict,
        manifests: dict[tuple[str, str], dict],
        assets: dict[tuple[str, str, str], bytes],
    ):
        self._catalog = validate_catalog(copy.deepcopy(catalog))
        self._manifests: dict[tuple[str, str], dict] = {}
        for (wall_id, release_id), payload in manifests.items():
            require_wall_id(wall_id)
            require_release_id(release_id)
            self._manifests[(wall_id, release_id)] = assert_manifest_identity(
                copy.deepcopy(payload), wall_id, release_id
            )
        self._assets = {
            (
                require_wall_id(wall_id),
                require_release_id(release_id),
                require_asset_id(asset_id),
            ): payload
            for (wall_id, release_id, asset_id), payload in assets.items()
        }

    @classmethod
    def example(cls) -> "MemoryStore":
        return cls(
            catalog=example_catalog(),
            manifests={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): example_manifest()},
            assets={(EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID): EXAMPLE_ASSET_BYTES},
        )

    @classmethod
    def two_releases(cls, *, latest_release_id: str = EXAMPLE_RELEASE_ID) -> "MemoryStore":
        return cls(
            catalog=example_catalog(latest_release_id=latest_release_id),
            manifests={
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID): example_manifest(),
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID_2): example_manifest(
                    release_id=EXAMPLE_RELEASE_ID_2,
                    payload=EXAMPLE_ASSET_BYTES_V2,
                ),
            },
            assets={
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID, EXAMPLE_ASSET_ID): EXAMPLE_ASSET_BYTES,
                (EXAMPLE_WALL_ID, EXAMPLE_RELEASE_ID_2, EXAMPLE_ASSET_ID): EXAMPLE_ASSET_BYTES_V2,
            },
        )

    def catalog(self) -> dict:
        return copy.deepcopy(self._catalog)

    def latest_release_id(self, wall_id: str) -> str:
        require_wall_id(wall_id)
        for item in self._catalog["walls"]:
            if item["wallId"] == wall_id:
                return item["latestReleaseId"]
        raise NotFound(f"unknown wallId {wall_id}")

    def manifest(self, wall_id: str) -> dict:
        return self.manifest_for_release(wall_id, self.latest_release_id(wall_id))

    def manifest_for_release(self, wall_id: str, release_id: str) -> dict:
        require_wall_id(wall_id)
        require_release_id(release_id)
        payload = self._manifests.get((wall_id, release_id))
        if payload is None:
            raise NotFound(f"unknown release {wall_id}/{release_id}")
        return copy.deepcopy(assert_manifest_identity(payload, wall_id, release_id))

    def asset_bytes(self, wall_id: str, release_id: str, asset_id: str) -> bytes:
        require_wall_id(wall_id)
        require_release_id(release_id)
        require_asset_id(asset_id)
        manifest = self.manifest_for_release(wall_id, release_id)
        known = {item["assetId"] for item in manifest["assets"]}
        if asset_id not in known:
            raise NotFound(f"unknown assetId {asset_id}")
        payload = self._assets.get((wall_id, release_id, asset_id))
        if payload is None:
            raise NotFound(f"unknown assetId {asset_id}")
        return payload
