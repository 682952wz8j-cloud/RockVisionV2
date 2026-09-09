from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IOS = ROOT / "ios"
ASSETS = IOS / "RockVision" / "Resources" / "JinshidongLocalTest"
PROCESSOR = IOS / "RockVision" / "Features" / "OpenCV" / "OpenCVFrameProcessor.swift"
SIM3_LOADER = IOS / "RockVision" / "Features" / "PnP" / "PnPSim3.swift"
HUD = IOS / "RockVision" / "Features" / "DebugOverlay" / "DebugHUDMode.swift"


class JinshidongIOSLocalTestTests(unittest.TestCase):
    def test_committed_assets_are_jinshidong_local_test_not_production(self) -> None:
        manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["wallId"], "wall_jinshidong_01")
        self.assertEqual(manifest["wallBuildRunId"], "wb_20260906T024519Z_6e08b5ff")
        self.assertEqual(manifest["releaseId"], "r000000")
        self.assertTrue(manifest["developmentLocalTestOnly"])
        self.assertTrue(manifest["notAProductionRelease"])
        self.assertTrue(manifest["notACatalogRelease"])
        self.assertTrue(manifest["notAProductionRoutePackage"])

        package = json.loads((ASSETS / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["wallId"], "wall_jinshidong_01")
        self.assertEqual(package["releaseId"], "r000000")
        self.assertTrue(package["notACatalogRelease"])
        self.assertEqual(package["packageState"], "CONSTRUCTED")
        self.assertNotEqual(package.get("packageState"), "PUBLISHED")

        bundle = json.loads((ASSETS / "route_bundle.json").read_text(encoding="utf-8"))
        self.assertTrue(bundle["notAProductionRoutePackage"])
        self.assertTrue(bundle["notAStage5Release"])
        self.assertEqual(bundle["wallId"], "wall_jinshidong_01")
        self.assertEqual(
            [row["routeId"] for row in bundle["routes"]],
            [
                "jinshidong_lucky_baby",
                "jinshidong_shui_tai_shen",
                "jinshidong_mei_xiang_hao",
                "jinshidong_long_zhua_shou",
            ],
        )
        expected = {
            "jinshidong_lucky_baby": ("Lucky Baby", "5.7", "3+2", 6),
            "jinshidong_shui_tai_shen": ("水太深", "5.12d", "6+2", 3),
            "jinshidong_mei_xiang_hao": ("没想好", "5.11b", "7+2", 6),
            "jinshidong_long_zhua_shou": ("龙抓手", "5.11b", "5+2", 4),
        }
        for row in bundle["routes"]:
            name, grade, draws, count = expected[row["routeId"]]
            self.assertEqual(row["routeName"], name)
            self.assertEqual(row["grade"], grade)
            self.assertEqual(row["quickdraws"], draws)
            self.assertEqual(row["pointCount"], count)
            fixture = json.loads((ASSETS / Path(row["fixturePath"]).name).read_text(encoding="utf-8"))
            self.assertEqual(fixture["routeId"], row["routeId"])
            self.assertEqual(fixture["routeName"], name)
            self.assertEqual(fixture["grade"], grade)
            self.assertEqual(fixture["quickdraws"], draws)
            self.assertEqual(fixture["polylineSha256"], row["polylineSha256"])
            self.assertEqual(len(fixture["polyline"]), count)
            self.assertTrue(fixture["notAProductionRoutePackage"])
            self.assertEqual(fixture["provenance"], "IDENTITY_SUPPORTED")
            self.assertNotEqual(fixture["routeId"], "route_test_01")

    def test_ios_runtime_defaults_to_production_cloud(self) -> None:
        processor = PROCESSOR.read_text(encoding="utf-8")
        self.assertIn("case productionCloudUnselected", processor)
        self.assertIn("desiredReferenceSourceMode: ReferenceSourceMode = .productionCloudUnselected", processor)
        self.assertIn("selectProductionCloudRelease", processor)
        self.assertIn("JinshidongLocalTestAssets.load", processor)
        self.assertIn("selectReferenceSourceJinshidongLocalTest", processor)
        hud = HUD.read_text(encoding="utf-8")
        self.assertIn(".stage5", hud)
        self.assertIn("showsStage5HUD", hud)
        sim3 = SIM3_LOADER.read_text(encoding="utf-8")
        self.assertIn("PnPConfig.expectedSim3Scale", sim3)
        self.assertIn("enum ProductionSim3Loader", sim3)
        selector = (IOS / "RockVision" / "Features" / "Cloud" / "WallCandidateSelector.swift").read_text(encoding="utf-8")
        self.assertNotIn("import CoreLocation", selector)
        self.assertIn("wall_jinshidong_01", selector)
        self.assertIn("30.623418333479282", selector)
        self.assertIn("118.72756872205237", selector)
        runtime = (IOS / "RockVision" / "Features" / "Cloud" / "ProductionRuntime.swift").read_text(encoding="utf-8")
        self.assertIn("injectedCoordinate", runtime)
        self.assertIn("selectProductionCloudRelease", runtime)
        self.assertIn("fetchCatalog", runtime)
        plist = (IOS / "RockVision" / "Info.plist").read_text(encoding="utf-8")
        self.assertIn("NSLocationWhenInUseUsageDescription", plist)
        content = (IOS / "RockVision" / "App" / "ContentView.swift").read_text(encoding="utf-8")
        self.assertIn("productionRuntime.start()", content)
        appear = content.split(".onAppear {", 1)[1].split(".onChange(of: geo.size)", 1)[0]
        self.assertNotIn("selectReferenceSourceJinshidongLocalTest()", appear)
        self.assertNotIn("selectReferenceSourceCloudCurrentJiulongfengDevR000001()", appear)

    def test_stage5_debug_hud_is_localization_pnp_wall_and_cloud(self) -> None:
        hud = (IOS / "RockVision" / "Features" / "DebugOverlay" / "Stage5DebugHUD.swift").read_text(encoding="utf-8")
        self.assertIn("定位成功", hud)
        self.assertIn("定位失败", hud)
        self.assertIn("localizationLocalized", hud)
        self.assertIn('PnP \\(inliers) | \\(medianToken(reproj)) px', hud)
        self.assertIn("云端资产：已加载", hud)
        self.assertIn("云端资产：加载失败", hud)
        self.assertNotIn("Start Measurement", hud)
        self.assertNotIn("Gate 4B", hud)
        self.assertNotIn("Jinshidong local test", hud)
        self.assertNotIn("FieldTestPanel", hud)
        content = (IOS / "RockVision" / "App" / "ContentView.swift").read_text(encoding="utf-8")
        self.assertIn("Stage5DebugHUD(", content)
        self.assertIn("if DebugHUDMode.active.showsStage5HUD {", content)
        self.assertIn("if DebugHUDMode.active.showsGate4BHUD {", content)
        self.assertNotIn("showsGate4BHUD || DebugHUDMode.active.showsStage5HUD", content)
        stage = content.split("if DebugHUDMode.active.showsStage5HUD {", 1)[1]
        self.assertIn("Stage5DebugHUD(", stage)
        self.assertNotIn("FieldTestPanel(", stage)
        gate = content.split("if DebugHUDMode.active.showsGate4BHUD {", 1)[1].split(
            "if DebugHUDMode.active.showsStage5HUD {", 1
        )[0]
        self.assertIn("FieldTestPanel(", gate)
        self.assertNotIn("Stage5DebugHUD(", gate)
        panel = (IOS / "RockVision" / "Features" / "FieldTest" / "FieldTestPanel.swift").read_text(encoding="utf-8")
        self.assertIn("Gate4BPhysicalValidationHUD", panel)
        self.assertNotIn("定位成功", panel)

    def test_binaries_are_not_required_in_git(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("ios/RockVision/Resources/JinshidongLocalTest/descriptors.bin", gitignore)
        self.assertIn("ios/RockVision/Resources/JinshidongLocalTest/landmarks.json", gitignore)
        self.assertTrue((ASSETS / "manifest.json").exists())
        self.assertTrue((ASSETS / "package.json").exists())
        self.assertTrue((ASSETS / "jinshidong_s_wall_colmap.json").exists())
        self.assertTrue((ASSETS / "route_bundle.json").exists())
        catalog = ROOT / "published" / "catalog.json"
        if catalog.exists():
            text = catalog.read_text(encoding="utf-8")
            self.assertNotIn("wall_jinshidong_01", text)
