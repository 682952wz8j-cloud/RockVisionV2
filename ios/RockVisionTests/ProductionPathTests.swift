import XCTest
@testable import RockVision

final class ProductionPathTests: XCTestCase {
    func testPrivacyConsentOnlyAcceptsCurrentPolicyVersion() {
        XCTAssertFalse(PrivacyConsent.isGranted(version: 0))
        XCTAssertTrue(PrivacyConsent.isGranted(version: PrivacyConsent.currentVersion))
        XCTAssertFalse(PrivacyConsent.isGranted(version: PrivacyConsent.currentVersion + 1))
    }

    @MainActor
    func testCragDirectoryDoesNotFetchBeforePrivacyConsent() async {
        let transport = MockCloudTransport()
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .production, transport: transport),
            store: CloudReleaseStore(rootURL: uniqueRoot())
        )
        let model = CragDirectoryModel()
        model.serviceOverride = service

        await model.refresh(privacyConsentGranted: false)

        XCTAssertTrue(transport.requestedPaths.isEmpty)
        XCTAssertEqual(model.loadState, .ready)
        XCTAssertEqual(model.groups, CragDirectoryBuilder.groups())
    }

    func testStartupPermissionAndNetworkWorkAreBehindPrivacyConsent() throws {
        let app = try readHostSource("RockVision/App/RockVisionApp.swift")
        XCTAssertTrue(app.contains("if PrivacyConsent.isGranted(version: privacyConsentVersion)"))
        XCTAssertTrue(app.contains("PrivacyConsentGate(consentVersion: $privacyConsentVersion)"))

        let content = try readHostSource("RockVision/App/ContentView.swift")
        let resumeScan = content.slice(after: "private func resumeScan", before: "private func currentOrientation")
        let consentGuard = try XCTUnwrap(resumeScan.range(of: "guard privacyConsentGranted else"))
        let cameraCheck = try XCTUnwrap(resumeScan.range(of: "AVCaptureDevice.authorizationStatus"))
        XCTAssertLessThan(consentGuard.lowerBound, cameraCheck.lowerBound)

        let directory = try readHostSource("RockVision/Features/ScanLoading/CragDirectory.swift")
        XCTAssertTrue(directory.contains("func refresh(privacyConsentGranted: Bool) async"))
        XCTAssertTrue(directory.contains("guard privacyConsentGranted else { return }"))
        XCTAssertTrue(directory.contains("model.refresh(privacyConsentGranted: privacyConsentGranted)"))
    }

    @MainActor
    func testPermissionFailureCanRetryWithoutRecreatingController() async throws {
        let runtime = ProductionRuntimeController()
        runtime.coordinateProviderOverride = { throw WallLocationError.permissionDenied }
        await runtime.start()
        XCTAssertEqual(runtime.lastError, "location permission denied")
        XCTAssertFalse(runtime.isLoading)
        runtime.coordinateProviderOverride = { throw WallLocationError.unavailable }
        await runtime.start()
        XCTAssertEqual(runtime.lastError, "location unavailable")
        XCTAssertFalse(runtime.isLoading)
        XCTAssertFalse(runtime.cloudAssetsLoaded)
    }

    @MainActor
    func testRepeatedStartDoesNotCreateOverlappingLocationRequests() async throws {
        let runtime = ProductionRuntimeController()
        var requests = 0
        var pending: CheckedContinuation<Void, Never>?
        runtime.coordinateProviderOverride = {
            requests += 1
            await withCheckedContinuation { pending = $0 }
            throw WallLocationError.unavailable
        }
        let first = Task { await runtime.start() }
        while pending == nil { await Task.yield() }
        XCTAssertTrue(runtime.isLoading)
        await runtime.start()
        XCTAssertEqual(requests, 1)
        pending?.resume()
        await first.value
        XCTAssertFalse(runtime.isLoading)
        XCTAssertEqual(runtime.lastError, "location unavailable")
    }

    func testDefaultReferenceSourceIsProductionCloudNotLocalTest() throws {
        let processor = OpenCVFrameProcessor()
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "productionCloud")
        XCTAssertNotEqual(processor.debugDesiredReferenceSourceMode, "jinshidongLocalTest")
        XCTAssertNotEqual(processor.debugDesiredReferenceSourceMode, "cloudCurrentJiulongfengDevR000001")
        XCTAssertNotEqual(processor.debugDesiredReferenceSourceMode, "bundleDevelopmentFixture")
        #else
        throw XCTSkip("Only meaningful in DEBUG test builds.")
        #endif
    }

    func testProductionSim3AndRoutesLoadFromCandidateArtifacts() throws {
        let sim3URL = try candidateURL("assets/s-wall-colmap")
        let routesURL = try candidateURL("assets/wall-routes")
        let sim3 = try ProductionSim3Loader.load(from: sim3URL)
        XCTAssertEqual(sim3.status, "VALIDATED")
        XCTAssertEqual(sim3.scale, 3.7780058545133315, accuracy: 1e-9)
        XCTAssertNotEqual(sim3.scale, PnPConfig.expectedSim3Scale)
        let routes = try XCTUnwrap(
            VerifiedFrozenRoute.loadProductionAsset(
                from: routesURL,
                expectedWallId: JinshidongCatalogLocation.wallId,
                expectedReleaseId: JinshidongCatalogLocation.releaseId
            )
        )
        XCTAssertEqual(routes.count, 4)
        XCTAssertEqual(routes.map(\.routeId), [
            "jinshidong_lucky_baby",
            "jinshidong_shui_tai_shen",
            "jinshidong_mei_xiang_hao",
            "jinshidong_long_zhua_shou"
        ])
        XCTAssertEqual(routes[0].polylineSha256, "9473023e60e9fd5a2003ead60d5e7134d0b1386e81b861457e1de569ae62b407")
        XCTAssertTrue(routes.allSatisfy { $0.hashVerified })
        XCTAssertTrue(routes.allSatisfy { !$0.developmentValidationOnly })
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(routes[0]),
            ["Lucky Baby", "5.7", "🔗 3+2"]
        )
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(routes[1]),
            ["水太深", "5.12d", "🔗 6+2"]
        )
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(routes[2]),
            ["没想好", "5.11b", "🔗 7+2"]
        )
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(routes[3]),
            ["龙抓手", "5.11b", "🔗 5+2"]
        )
        XCTAssertTrue(routes.allSatisfy { $0.lengthMeters == nil })
        XCTAssertTrue(routes.allSatisfy { !ProductionRouteFieldCopy.displayLines($0).contains { $0.hasSuffix(" m") } })
    }

    func testProductionSim3AndRoutesLoadFromJiulongfengCandidateArtifacts() throws {
        let sim3URL = try candidateURL("assets/s-wall-colmap", wallId: JiulongfengCatalogLocation.wallId)
        let routesURL = try candidateURL("assets/wall-routes", wallId: JiulongfengCatalogLocation.wallId)
        let sim3 = try ProductionSim3Loader.load(from: sim3URL)
        XCTAssertEqual(sim3.status, "VALIDATED")
        XCTAssertEqual(sim3.scale, 3.19764417024824, accuracy: 1e-9)
        XCTAssertEqual(sim3.scale, PnPConfig.expectedSim3Scale, accuracy: 1e-9)
        let routes = try XCTUnwrap(
            VerifiedFrozenRoute.loadProductionAsset(
                from: routesURL,
                expectedWallId: JiulongfengCatalogLocation.wallId,
                expectedReleaseId: JiulongfengCatalogLocation.releaseId
            )
        )
        XCTAssertEqual(routes.count, 1)
        XCTAssertEqual(routes.map(\.routeId), [JiulongfengCatalogLocation.routeId])
        XCTAssertEqual(routes[0].routeName, "白墙测试线")
        XCTAssertEqual(routes[0].grade, "unspecified")
        XCTAssertEqual(routes[0].displayDraws, "unspecified")
        XCTAssertNil(routes[0].lengthMeters)
        XCTAssertEqual(routes[0].polylineSha256, "ff6ff3ee58303634d369b919284ee8c827a80eb57a9403004614cda6194d2f99")
        XCTAssertNotEqual(routes[0].routeId, VerifiedFrozenRoute.expectedRouteId)
        XCTAssertTrue(routes.allSatisfy { $0.hashVerified })
        XCTAssertTrue(routes.allSatisfy { !$0.developmentValidationOnly })
        XCTAssertEqual(ProductionRouteFieldCopy.displayLines(routes[0]), ["白墙测试线"])
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains("unspecified"))
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains { $0.hasPrefix("🔗") })
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(routes[0]).contains { $0.hasSuffix(" m") })
    }

    @MainActor
    func testInjectedJinshidongGPSSelectsWallAndLoadsProductionRelease() async throws {
        let (service, _) = try makeProductionStore(
            wallId: JinshidongCatalogLocation.wallId,
            releaseId: JinshidongCatalogLocation.releaseId
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: JinshidongCatalogLocation.wallId,
                    name: JinshidongCatalogLocation.displayName,
                    latestReleaseId: JinshidongCatalogLocation.releaseId,
                    environment: .production,
                    catalogLocation: JinshidongCatalogLocation.location
                )
            ]
        )
        runtime.injectedCoordinate = (
            JinshidongCatalogLocation.location.latitudeDeg,
            JinshidongCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertEqual(runtime.wallId, JinshidongCatalogLocation.wallId)
        XCTAssertTrue(runtime.cloudAssetsLoaded)
        XCTAssertEqual(processor.referenceAssetProvenance.source, "cloud")
        XCTAssertEqual(processor.referenceAssetProvenance.wallId, JinshidongCatalogLocation.wallId)
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, JinshidongCatalogLocation.releaseId)
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.productionFieldRoutes.map(\.routeId), ["jinshidong_lucky_baby"])
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]),
            ["Lucky Baby", "5.7", "🔗 3+2"]
        )
        XCTAssertEqual(
            Stage5DebugHUDModel.diagnosticLine(
                localization: processor.confirmationSnapshot.localization,
                pnp: processor.pnpSnapshot,
                wallId: runtime.wallId,
                cloudAssetsLoaded: runtime.cloudAssetsLoaded
            ),
            "定位失败 | PnP — | — px | \(JinshidongCatalogLocation.wallId) | 云端已加载"
        )
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "productionCloud")
        #endif
    }

    @MainActor
    func testOfficeGPSDoesNotSelectJinshidong() async throws {
        let (service, _) = try makeProductionStore(
            wallId: JinshidongCatalogLocation.wallId,
            releaseId: JinshidongCatalogLocation.releaseId
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: JinshidongCatalogLocation.wallId,
                    name: JinshidongCatalogLocation.displayName,
                    latestReleaseId: JinshidongCatalogLocation.releaseId,
                    environment: .production,
                    catalogLocation: JinshidongCatalogLocation.location
                )
            ]
        )
        runtime.injectedCoordinate = (31.23, 121.47)
        await runtime.start()
        XCTAssertEqual(runtime.wallId, "—")
        XCTAssertFalse(runtime.cloudAssetsLoaded)
        XCTAssertEqual(runtime.lastError, "no wall in GPS range")
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "productionCloud")
        #endif
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "unavailable")
        XCTAssertTrue(processor.productionFieldRoutes.isEmpty)
        XCTAssertEqual(
            Stage5DebugHUDModel.diagnosticLine(
                localization: processor.confirmationSnapshot.localization,
                pnp: processor.pnpSnapshot,
                wallId: runtime.wallId,
                cloudAssetsLoaded: runtime.cloudAssetsLoaded
            ),
            "定位失败 | PnP — | — px | — | 加载失败"
        )
    }

    @MainActor
    func testInjectedJiulongfengGPSSelectsWallAndLoadsProductionRelease() async throws {
        let (service, _) = try makeProductionStore(
            wallId: JiulongfengCatalogLocation.wallId,
            releaseId: JiulongfengCatalogLocation.releaseId,
            routeId: JiulongfengCatalogLocation.routeId,
            routeName: "白墙测试线",
            grade: "unspecified",
            quickdraws: "unspecified"
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: JinshidongCatalogLocation.wallId,
                    name: JinshidongCatalogLocation.displayName,
                    latestReleaseId: JinshidongCatalogLocation.releaseId,
                    environment: .production,
                    catalogLocation: JinshidongCatalogLocation.location
                ),
                WallCatalogEntry(
                    wallId: JiulongfengCatalogLocation.wallId,
                    name: JiulongfengCatalogLocation.displayName,
                    latestReleaseId: JiulongfengCatalogLocation.releaseId,
                    environment: .production,
                    catalogLocation: JiulongfengCatalogLocation.location
                )
            ]
        )
        runtime.injectedCoordinate = (
            JiulongfengCatalogLocation.location.latitudeDeg,
            JiulongfengCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertEqual(runtime.wallId, JiulongfengCatalogLocation.wallId)
        XCTAssertTrue(runtime.cloudAssetsLoaded)
        XCTAssertEqual(processor.referenceAssetProvenance.source, "cloud")
        XCTAssertEqual(processor.referenceAssetProvenance.wallId, JiulongfengCatalogLocation.wallId)
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, JiulongfengCatalogLocation.releaseId)
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.productionFieldRoutes.map(\.routeId), [JiulongfengCatalogLocation.routeId])
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]),
            ["白墙测试线"]
        )
        XCTAssertEqual(
            Stage5DebugHUDModel.diagnosticLine(
                localization: processor.confirmationSnapshot.localization,
                pnp: processor.pnpSnapshot,
                wallId: runtime.wallId,
                cloudAssetsLoaded: runtime.cloudAssetsLoaded
            ),
            "定位失败 | PnP — | — px | \(JiulongfengCatalogLocation.wallId) | 云端已加载"
        )
        #if DEBUG
        XCTAssertEqual(processor.debugDesiredReferenceSourceMode, "productionCloud")
        #endif
    }

    @MainActor
    func testProductionWallSwitchClearsPreviousPackageRoutesAndHUD() async throws {
        let (jinshidongService, _) = try makeProductionStore(
            wallId: JinshidongCatalogLocation.wallId,
            releaseId: JinshidongCatalogLocation.releaseId
        )
        let (jiulongfengService, _) = try makeProductionStore(
            wallId: JiulongfengCatalogLocation.wallId,
            releaseId: JiulongfengCatalogLocation.releaseId,
            routeId: JiulongfengCatalogLocation.routeId,
            routeName: "白墙测试线",
            grade: "unspecified",
            quickdraws: "unspecified"
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.injectedCatalog = bothWallsCatalog()

        runtime.serviceOverride = jinshidongService
        runtime.injectedCoordinate = (
            JinshidongCatalogLocation.location.latitudeDeg,
            JinshidongCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertEqual(runtime.wallId, JinshidongCatalogLocation.wallId)
        XCTAssertEqual(processor.productionFieldRoutes.map(\.routeId), ["jinshidong_lucky_baby"])
        XCTAssertEqual(processor.localTestRouteLegend.map(\.routeId), ["jinshidong_lucky_baby"])

        runtime.serviceOverride = jiulongfengService
        runtime.injectedCoordinate = (
            JiulongfengCatalogLocation.location.latitudeDeg,
            JiulongfengCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertEqual(runtime.wallId, JiulongfengCatalogLocation.wallId)
        XCTAssertTrue(runtime.cloudAssetsLoaded)
        XCTAssertEqual(processor.productionFieldRoutes.map(\.routeId), [JiulongfengCatalogLocation.routeId])
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]),
            ["白墙测试线"]
        )
        XCTAssertFalse(processor.productionFieldRoutes.contains { $0.routeId.hasPrefix("jinshidong_") })
        XCTAssertEqual(processor.localTestRouteLegend.map(\.routeId), [JiulongfengCatalogLocation.routeId])
        XCTAssertEqual(processor.routeRenderPlan, .empty)
        XCTAssertEqual(processor.pnpSnapshot.inliers, "—")
        XCTAssertEqual(processor.pnpSnapshot.reproj, "—")
        XCTAssertEqual(processor.confirmationSnapshot.localization, ConfirmationConfig.localizationIdle)
        XCTAssertEqual(
            Stage5DebugHUDModel.diagnosticLine(
                localization: processor.confirmationSnapshot.localization,
                pnp: processor.pnpSnapshot,
                wallId: runtime.wallId,
                cloudAssetsLoaded: runtime.cloudAssetsLoaded
            ),
            "定位失败 | PnP — | — px | \(JiulongfengCatalogLocation.wallId) | 云端已加载"
        )
    }

    @MainActor
    func testLeavingProductionWallClearsPackageRoutesAndHUD() async throws {
        let (service, _) = try makeProductionStore(
            wallId: JinshidongCatalogLocation.wallId,
            releaseId: JinshidongCatalogLocation.releaseId
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = bothWallsCatalog()
        runtime.injectedCoordinate = (
            JinshidongCatalogLocation.location.latitudeDeg,
            JinshidongCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertFalse(processor.productionFieldRoutes.isEmpty)

        runtime.injectedCoordinate = (31.23, 121.47)
        await runtime.start()
        XCTAssertEqual(runtime.wallId, "—")
        XCTAssertFalse(runtime.cloudAssetsLoaded)
        XCTAssertTrue(processor.productionFieldRoutes.isEmpty)
        XCTAssertTrue(processor.localTestRouteLegend.isEmpty)
        XCTAssertEqual(processor.routeRenderPlan, .empty)
        XCTAssertEqual(processor.pnpSnapshot.inliers, "—")
        XCTAssertEqual(
            Stage5DebugHUDModel.diagnosticLine(
                localization: processor.confirmationSnapshot.localization,
                pnp: processor.pnpSnapshot,
                wallId: runtime.wallId,
                cloudAssetsLoaded: runtime.cloudAssetsLoaded
            ),
            "定位失败 | PnP — | — px | — | 加载失败"
        )
    }

    @MainActor
    func testMissingOfficialRouteMetadataIsOmittedFromFieldCopy() async throws {
        let (service, _) = try makeProductionStore(
            wallId: "wall_example_01",
            releaseId: "r000001",
            routeId: "example_unnamed_meta",
            routeName: "Example Route",
            grade: "unspecified",
            quickdraws: "n/a"
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: "wall_example_01",
                    name: "Example Wall",
                    latestReleaseId: "r000001",
                    environment: .production,
                    catalogLocation: JinshidongCatalogLocation.location
                )
            ]
        )
        runtime.injectedCoordinate = (
            JinshidongCatalogLocation.location.latitudeDeg,
            JinshidongCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertEqual(runtime.wallId, "wall_example_01")
        XCTAssertEqual(processor.productionFieldRoutes.map(\.routeName), ["Example Route"])
        XCTAssertEqual(ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]), ["Example Route"])
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]).contains("unspecified"))
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]).contains { $0.hasPrefix("🔗") })
        XCTAssertFalse(ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]).contains { $0.hasSuffix(" m") })
    }

    @MainActor
    func testOfficialLengthAppearsOnlyWhenPresentInPackage() async throws {
        let (service, _) = try makeProductionStore(
            wallId: "wall_example_01",
            releaseId: "r000001",
            routeId: "example_with_length",
            routeName: "Measured Route",
            grade: "5.10a",
            quickdraws: "8",
            lengthMeters: 18
        )
        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: "wall_example_01",
                    name: "Example Wall",
                    latestReleaseId: "r000001",
                    environment: .production,
                    catalogLocation: JinshidongCatalogLocation.location
                )
            ]
        )
        runtime.injectedCoordinate = (
            JinshidongCatalogLocation.location.latitudeDeg,
            JinshidongCatalogLocation.location.longitudeDeg
        )
        await runtime.start()
        XCTAssertEqual(
            ProductionRouteFieldCopy.displayLines(processor.productionFieldRoutes[0]),
            ["Measured Route", "5.10a", "18 m", "🔗 8+2"]
        )
    }

    func testProductionPathDoesNotReadBundleSim3OrLocalTestDefaults() throws {
        let processor = try readHostSource("RockVision/Features/OpenCV/OpenCVFrameProcessor.swift")
        XCTAssertTrue(processor.contains("desiredReferenceSourceMode: ReferenceSourceMode = .productionCloudUnselected"))
        XCTAssertFalse(processor.contains("desiredReferenceSourceMode: ReferenceSourceMode = .jinshidongLocalTest"))
        XCTAssertTrue(processor.contains("ProductionSim3Loader.load"))
        XCTAssertTrue(processor.contains("VerifiedFrozenRoute.loadProductionAsset"))
        XCTAssertTrue(processor.contains("selectProductionCloudRelease"))
        XCTAssertTrue(processor.contains("selectReferenceSourceJinshidongLocalTest"))
        let productionCase = processor.slice(after: "case .productionCloud(let wallId):", before: "case .jinshidongLocalTest:")
        XCTAssertTrue(productionCase.contains("ProductionSim3Loader.load"))
        XCTAssertFalse(productionCase.contains("ValidatedSim3Loader.loadFromBundle"))
        XCTAssertFalse(productionCase.contains("PnPConfig.expectedSim3Scale"))
        XCTAssertFalse(productionCase.contains("JinshidongLocalTestAssets.load"))
        let content = try readHostSource("RockVision/App/ContentView.swift")
        let resumeScan = content.slice(after: "private func resumeScan", before: "private func currentOrientation")
        XCTAssertTrue(content.contains("productionRuntime.start()"))
        XCTAssertTrue(content.contains("onSelectReferenceSourceJinshidongLocalTest"))
        let appear = content.slice(after: ".onAppear {", before: ".onChange(of: geo.size)")
        XCTAssertTrue(appear.contains("resumeScan()"))
        XCTAssertTrue(resumeScan.contains("productionRuntime.start()"))
        XCTAssertFalse(appear.contains("selectReferenceSourceJinshidongLocalTest()"))
        XCTAssertFalse(appear.contains("selectReferenceSourceCloudCurrentJiulongfengDevR000001()"))
        let api = try readHostSource("RockVision/Features/Cloud/CloudAPIConfiguration.swift")
        XCTAssertTrue(api.contains("https://api.cragpal.com"))
        XCTAssertTrue(api.contains("static let `default` = CloudAPIConfiguration.production"))
        let releaseDefault = String(api.components(separatedBy: "#else").last!.components(separatedBy: "#endif")[0])
        XCTAssertTrue(releaseDefault.contains("CloudAPIConfiguration.production"))
        XCTAssertFalse(releaseDefault.contains("124.223.178.91"))
        XCTAssertFalse(releaseDefault.contains("developmentTemporaryHTTP"))
    }

    @MainActor
    func testLiveHTTPSReleaseProductionDiscovery() async throws {
        #if !LIVE_PRODUCTION_HTTPS
        throw XCTSkip("opt-in live HTTPS production discovery")
        #else
        executionTimeAllowance = 600
        XCTAssertEqual(CloudAPIConfiguration.production.baseURL.absoluteString, "https://api.cragpal.com")
        let catalogURL = CloudAPIConfiguration.productionHTTPSURL.appending(path: "v1/walls")
        let (catalogData, catalogResponse) = try await URLSession.shared.data(from: catalogURL)
        XCTAssertEqual((catalogResponse as? HTTPURLResponse)?.statusCode, 200)
        let catalog = CloudCatalogAudience.production.filter(try CloudAssetContract.decodeCatalog(catalogData))
        let location = JinshidongCatalogLocation.location
        let selected = try XCTUnwrap(
            WallCandidateSelector.selectWallId(
                latitude: location.latitudeDeg,
                longitude: location.longitudeDeg,
                catalog: catalog
            )
        )
        XCTAssertEqual(selected, JinshidongCatalogLocation.wallId)
        let entry = try XCTUnwrap(catalog.walls.first { $0.wallId == selected })
        XCTAssertEqual(entry.name, JinshidongCatalogLocation.displayName)
        XCTAssertEqual(entry.latestReleaseId, JinshidongCatalogLocation.releaseId)
        XCTAssertEqual(entry.environment, .production)
        XCTAssertEqual(entry.catalogLocation, location)

        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .production),
            store: store
        )
        let installed = try await service.installRelease(wallId: selected, releaseId: entry.latestReleaseId)
        XCTAssertEqual(installed.release.wallId, selected)
        XCTAssertEqual(installed.release.releaseId, JinshidongCatalogLocation.releaseId)
        XCTAssertTrue(installed.optionalFailures.isEmpty)

        let sim3Asset = try CloudStage3AssetSemantics.requiredSim3Asset(in: installed.release.manifest)
        let routesAsset = try XCTUnwrap(
            try CloudStage3AssetSemantics.productionRoutesAsset(in: installed.release.manifest)
        )
        let sim3 = try ProductionSim3Loader.load(from: try service.localAssetURL(wallId: selected, assetId: sim3Asset.assetId))
        XCTAssertEqual(sim3.status, "VALIDATED")
        XCTAssertEqual(sim3.scale, 3.7780058545133315, accuracy: 1e-9)
        let routes = try XCTUnwrap(
            VerifiedFrozenRoute.loadProductionAsset(
                from: try service.localAssetURL(wallId: selected, assetId: routesAsset.assetId),
                expectedWallId: selected,
                expectedReleaseId: installed.release.releaseId
            )
        )
        XCTAssertEqual(routes.map(\.routeId), [
            "jinshidong_lucky_baby",
            "jinshidong_shui_tai_shen",
            "jinshidong_mei_xiang_hao",
            "jinshidong_long_zhua_shou"
        ])
        XCTAssertTrue(routes.allSatisfy(\.hashVerified))

        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = catalog
        runtime.injectedCoordinate = (location.latitudeDeg, location.longitudeDeg)
        await runtime.start()
        XCTAssertNil(runtime.lastError)
        XCTAssertEqual(runtime.wallId, selected)
        XCTAssertTrue(runtime.cloudAssetsLoaded)
        XCTAssertEqual(processor.referenceAssetProvenance.source, "cloud")
        XCTAssertEqual(processor.referenceAssetProvenance.wallId, selected)
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, JinshidongCatalogLocation.releaseId)
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.localTestRouteLegend.count, 4)
        #endif
    }

    @MainActor
    func testLiveHTTPSJiulongfengReleaseProductionDiscovery() async throws {
        #if !LIVE_PRODUCTION_HTTPS
        throw XCTSkip("opt-in live HTTPS production discovery")
        #else
        executionTimeAllowance = 600
        XCTAssertEqual(CloudAPIConfiguration.production.baseURL.absoluteString, "https://api.cragpal.com")
        let catalogURL = CloudAPIConfiguration.productionHTTPSURL.appending(path: "v1/walls")
        let (catalogData, catalogResponse) = try await URLSession.shared.data(from: catalogURL)
        XCTAssertEqual((catalogResponse as? HTTPURLResponse)?.statusCode, 200)
        let catalog = CloudCatalogAudience.production.filter(try CloudAssetContract.decodeCatalog(catalogData))
        let location = JiulongfengCatalogLocation.location
        let selected = try XCTUnwrap(
            WallCandidateSelector.selectWallId(
                latitude: location.latitudeDeg,
                longitude: location.longitudeDeg,
                catalog: catalog
            )
        )
        XCTAssertEqual(selected, JiulongfengCatalogLocation.wallId)
        let entry = try XCTUnwrap(catalog.walls.first { $0.wallId == selected })
        XCTAssertEqual(entry.name, JiulongfengCatalogLocation.displayName)
        XCTAssertEqual(entry.latestReleaseId, JiulongfengCatalogLocation.releaseId)
        XCTAssertEqual(entry.environment, .production)
        XCTAssertEqual(entry.catalogLocation, location)

        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let service = CloudAssetService(
            client: CloudAPIClient(configuration: .production),
            store: store
        )
        let installed = try await service.installRelease(wallId: selected, releaseId: entry.latestReleaseId)
        XCTAssertEqual(installed.release.wallId, selected)
        XCTAssertEqual(installed.release.releaseId, JiulongfengCatalogLocation.releaseId)
        XCTAssertTrue(installed.optionalFailures.isEmpty)

        let sim3Asset = try CloudStage3AssetSemantics.requiredSim3Asset(in: installed.release.manifest)
        let routesAsset = try XCTUnwrap(
            try CloudStage3AssetSemantics.productionRoutesAsset(in: installed.release.manifest)
        )
        let sim3 = try ProductionSim3Loader.load(from: try service.localAssetURL(wallId: selected, assetId: sim3Asset.assetId))
        XCTAssertEqual(sim3.status, "VALIDATED")
        XCTAssertEqual(sim3.scale, 3.19764417024824, accuracy: 1e-9)
        let routes = try XCTUnwrap(
            VerifiedFrozenRoute.loadProductionAsset(
                from: try service.localAssetURL(wallId: selected, assetId: routesAsset.assetId),
                expectedWallId: selected,
                expectedReleaseId: installed.release.releaseId
            )
        )
        XCTAssertEqual(routes.map(\.routeId), [JiulongfengCatalogLocation.routeId])
        XCTAssertEqual(routes[0].polylineSha256, "ff6ff3ee58303634d369b919284ee8c827a80eb57a9403004614cda6194d2f99")
        XCTAssertEqual(routes[0].routeName, "白墙测试线")
        XCTAssertEqual(ProductionRouteFieldCopy.displayLines(routes[0]), ["白墙测试线"])
        XCTAssertTrue(routes.allSatisfy(\.hashVerified))

        let processor = OpenCVFrameProcessor()
        let runtime = ProductionRuntimeController()
        runtime.processor = processor
        runtime.serviceOverride = service
        runtime.injectedCatalog = catalog
        runtime.injectedCoordinate = (location.latitudeDeg, location.longitudeDeg)
        await runtime.start()
        XCTAssertNil(runtime.lastError)
        XCTAssertEqual(runtime.wallId, selected)
        XCTAssertTrue(runtime.cloudAssetsLoaded)
        XCTAssertEqual(processor.referenceAssetProvenance.source, "cloud")
        XCTAssertEqual(processor.referenceAssetProvenance.wallId, selected)
        XCTAssertEqual(processor.referenceAssetProvenance.releaseId, JiulongfengCatalogLocation.releaseId)
        XCTAssertEqual(processor.referenceAssetProvenance.assetState, "available")
        XCTAssertEqual(processor.localTestRouteLegend.count, 1)
        #endif
    }

    private func bothWallsCatalog() -> WallCatalog {
        WallCatalog(
            schema: CloudAssetSchema.catalog,
            walls: [
                WallCatalogEntry(
                    wallId: JinshidongCatalogLocation.wallId,
                    name: JinshidongCatalogLocation.displayName,
                    latestReleaseId: JinshidongCatalogLocation.releaseId,
                    environment: .production,
                    catalogLocation: JinshidongCatalogLocation.location
                ),
                WallCatalogEntry(
                    wallId: JiulongfengCatalogLocation.wallId,
                    name: JiulongfengCatalogLocation.displayName,
                    latestReleaseId: JiulongfengCatalogLocation.releaseId,
                    environment: .production,
                    catalogLocation: JiulongfengCatalogLocation.location
                )
            ]
        )
    }

    private func makeProductionStore(
        wallId: String,
        releaseId: String,
        routeId: String = "jinshidong_lucky_baby",
        routeName: String = "Lucky Baby",
        grade: String = "5.7",
        quickdraws: String = "3+2",
        lengthMeters: Double? = nil
    ) throws -> (service: CloudAssetService, store: CloudReleaseStore) {
        let descriptors = try makeDescriptorsPayload()
        let landmarks = try makeLandmarksJSONPayload(wallId: wallId)
        let sim3 = try makeSim3Payload()
        let polyline: [[Double]] = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        let hash = try XCTUnwrap(FrozenRoutePolylineHash.sha256Hex(polyline, pointCount: 2))
        let routesPayload = VerifiedFrozenRoute.ProductionRoutesFile(
            schema: "cragpal.wall-routes.v1",
            wallId: wallId,
            releaseId: releaseId,
            coordinateFrame: "WallMetricMeters",
            routes: [
                VerifiedFrozenRoute.ProductionRoute(
                    routeId: routeId,
                    routeName: routeName,
                    grade: grade,
                    quickdraws: quickdraws,
                    lengthMeters: lengthMeters,
                    source: VerifiedFrozenRoute.ProductionRouteSource(
                        path: "routes/Lucky Baby 5.7.dxf",
                        sha256: String(repeating: "a", count: 64),
                        sizeBytes: 12
                    ),
                    coordinateFrame: "WallMetricMeters",
                    provenance: "IDENTITY_SUPPORTED",
                    dummyOriginExcluded: true,
                    pointCount: 2,
                    polyline: polyline,
                    polylineSha256: hash
                )
            ]
        )
        let routes = try JSONEncoder().encode(routesPayload)
        let assets: [(WallAssetDescriptor, Data)] = [
            (
                WallAssetDescriptor(
                    assetId: "stage3-descriptors",
                    type: CloudAssetType.referenceDescriptorsRVS1,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(descriptors),
                    bytes: descriptors.count
                ),
                descriptors
            ),
            (
                WallAssetDescriptor(
                    assetId: "stage3-landmarks",
                    type: CloudAssetType.referenceLandmarksJSON,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(landmarks),
                    bytes: landmarks.count
                ),
                landmarks
            ),
            (
                WallAssetDescriptor(
                    assetId: "s-wall-colmap",
                    type: CloudAssetType.sWallColmapJSON,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(sim3),
                    bytes: sim3.count
                ),
                sim3
            ),
            (
                WallAssetDescriptor(
                    assetId: "wall-routes",
                    type: CloudAssetType.wallRoutesJSON,
                    required: true,
                    sha256: CloudIntegrity.sha256Hex(routes),
                    bytes: routes.count
                ),
                routes
            )
        ]
        let store = try activateCloudRelease(wallId: wallId, releaseId: releaseId, assets: assets)
        let service = CloudAssetService(
            client: CloudAPIClient(
                configuration: .custom(URL(string: "https://cloud.test")!),
                transport: MockCloudTransport()
            ),
            store: store
        )
        return (service, store)
    }

    private func activateCloudRelease(
        wallId: String,
        releaseId: String,
        assets: [(WallAssetDescriptor, Data)]
    ) throws -> CloudReleaseStore {
        let store = CloudReleaseStore(rootURL: uniqueRoot())
        let manifest = WallManifest(
            schema: CloudAssetSchema.manifest,
            wallId: wallId,
            releaseId: releaseId,
            createdAt: "2026-09-09T06:00:00Z",
            assets: assets.map(\.0)
        )
        let staging = try store.prepareStaging(wallId: wallId, releaseId: releaseId)
        try store.writeManifest(manifest, toReleaseRoot: staging)
        for (descriptor, data) in assets {
            try store.commitVerifiedAsset(data, descriptor: descriptor, toReleaseRoot: staging)
        }
        _ = try store.activateVerifiedStaging(wallId: wallId, releaseId: releaseId, manifest: manifest)
        return store
    }

    private func makeDescriptorsPayload() throws -> Data {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("rvs1-\(UUID().uuidString).bin")
        var row = [Float](repeating: 0, count: MatchingConfig.descriptorDim)
        row[0] = 1
        let payload = row.withUnsafeBufferPointer { Data(buffer: $0) }
        try RVS1Artifact.write(descriptors: payload, to: tmp)
        return try Data(contentsOf: tmp)
    }

    private func makeLandmarksJSONPayload(wallId: String) throws -> Data {
        let landmarks: [String: Any] = [
            "schema": 1,
            "wallId": wallId,
            "developmentFixtureOnly": true,
            "notAWallPackage": true,
            "matcherHotPath": ["descriptor", "point3DID"],
            "landmarks": [[
                "index": 0,
                "referenceImageID": 1,
                "referenceImageName": "bridge.JPG",
                "referenceKeypointX": 1.0,
                "referenceKeypointY": 2.0,
                "point3DID": 7,
                "colmapXYZ": [0.0, 0.0, 0.0],
            ]],
        ]
        return try JSONSerialization.data(withJSONObject: landmarks)
    }

    private func makeSim3Payload() throws -> Data {
        let payload: [String: Any] = [
            "name": "S_wall_colmap",
            "status": "VALIDATED",
            "convention": "X_wall = s * R * X_colmap + t  (column vectors)",
            "scale": 3.7780058545133315,
            "rotationMatrix": [
                "values": [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0]
                ]
            ],
            "translationMeters": [0.0, 0.0, 0.0]
        ]
        return try JSONSerialization.data(withJSONObject: payload)
    }

    private func candidateURL(_ relative: String, wallId: String = JinshidongCatalogLocation.wallId) throws -> URL {
        let releaseId = wallId == JiulongfengCatalogLocation.wallId
            ? JiulongfengCatalogLocation.releaseId
            : JinshidongCatalogLocation.releaseId
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("offline/packages/\(wallId)/\(releaseId)")
            .appendingPathComponent(relative)
        guard FileManager.default.isReadableFile(atPath: url.path) else {
            throw XCTSkip("production candidate artifact missing: \(relative)")
        }
        return url
    }

    private func uniqueRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("prod-path-\(UUID().uuidString)", isDirectory: true)
    }

    private func readHostSource(_ relative: String) throws -> String {
        let path = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(relative)
            .path
        guard FileManager.default.isReadableFile(atPath: path) else {
            throw XCTSkip("host source tree not readable")
        }
        return try String(contentsOfFile: path, encoding: .utf8)
    }
}

private extension String {
    func slice(after start: String, before end: String) -> String {
        guard let startRange = range(of: start),
              let endRange = range(of: end, range: startRange.upperBound..<endIndex)
        else { return "" }
        return String(self[startRange.upperBound..<endRange.lowerBound])
    }
}
