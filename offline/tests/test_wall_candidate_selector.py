from __future__ import annotations

import unittest

from offline.catalog_promotion.catalog import catalog_entry
from offline.catalog_promotion.location import (
    JINSHIDONG_CATALOG_LOCATION,
    JINSHIDONG_WALL_ID,
    MAX_CANDIDATE_DISTANCE_METERS,
    haversine_meters,
    select_wall_id,
)
from offline.catalog_promotion.record import promotion_record
from offline.catalog_promotion.projector import project_catalog
from offline.localization_package.schema import ENVIRONMENT_PRODUCTION


class WallCandidateSelectorTests(unittest.TestCase):
    def test_jinshidong_location_selects_jinshidong(self) -> None:
        catalog = {
            "walls": [
                catalog_entry(
                    wall_id=JINSHIDONG_WALL_ID,
                    name="金狮洞",
                    latest_release_id="r000001",
                    environment=ENVIRONMENT_PRODUCTION,
                    catalog_location=JINSHIDONG_CATALOG_LOCATION,
                )
            ]
        }
        loc = JINSHIDONG_CATALOG_LOCATION
        chosen = select_wall_id(
            latitude_deg=loc["latitudeDeg"],
            longitude_deg=loc["longitudeDeg"],
            walls=catalog["walls"],
        )
        self.assertEqual(chosen, JINSHIDONG_WALL_ID)
        self.assertLess(
            haversine_meters(loc["latitudeDeg"], loc["longitudeDeg"], loc["latitudeDeg"], loc["longitudeDeg"]),
            1.0,
        )

    def test_far_away_gps_selects_nothing(self) -> None:
        walls = [
            catalog_entry(
                wall_id=JINSHIDONG_WALL_ID,
                name="金狮洞",
                latest_release_id="r000001",
                environment=ENVIRONMENT_PRODUCTION,
                catalog_location=JINSHIDONG_CATALOG_LOCATION,
            )
        ]
        chosen = select_wall_id(latitude_deg=31.23, longitude_deg=121.47, walls=walls)
        self.assertIsNone(chosen)

    def test_entry_without_location_is_ignored(self) -> None:
        walls = [
            catalog_entry(
                wall_id="wall_example_01",
                name="Example Wall",
                latest_release_id="r000001",
                environment=None,
            )
        ]
        loc = JINSHIDONG_CATALOG_LOCATION
        chosen = select_wall_id(
            latitude_deg=loc["latitudeDeg"],
            longitude_deg=loc["longitudeDeg"],
            walls=walls,
        )
        self.assertIsNone(chosen)

    def test_promotion_projects_catalog_location(self) -> None:
        record = promotion_record(
            wall_id=JINSHIDONG_WALL_ID,
            release_id="r000001",
            name="金狮洞",
            promoted_at="2026-09-09T00:00:00Z",
            release_manifest_sha256="a" * 64,
            environment=ENVIRONMENT_PRODUCTION,
            catalog_location=JINSHIDONG_CATALOG_LOCATION,
        )
        catalog = project_catalog([record])
        entry = catalog["walls"][0]
        self.assertEqual(entry["wallId"], JINSHIDONG_WALL_ID)
        self.assertEqual(entry["latestReleaseId"], "r000001")
        self.assertEqual(entry["catalogLocation"]["purpose"], "wall_candidate_selection_only")
        self.assertEqual(entry["catalogLocation"]["latitudeDeg"], JINSHIDONG_CATALOG_LOCATION["latitudeDeg"])
        self.assertEqual(MAX_CANDIDATE_DISTANCE_METERS, 2500.0)
