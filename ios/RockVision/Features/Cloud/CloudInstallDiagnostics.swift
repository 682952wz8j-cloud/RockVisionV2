import Foundation

/// On-disk installer failure report. Never a Gate input. Never contains asset bytes.
enum CloudInstallDiagnosticsSchema {
    static let name = "cragpal.cloud-install-diagnostics.v1"
    static let directoryComponents = ["diagnostics", "cloud-install"]
}

struct CloudInstallAssetDiagnostic: Codable, Equatable, Sendable {
    var assetId: String
    var url: String
    var expectedBytes: Int
    var expectedSha256: String
    var downloadStartedAt: String?
    var httpStatus: Int?
    var actualBytes: Int?
    var actualSha256: String?
    var result: String
}

struct CloudInstallErrorDiagnostic: Codable, Equatable, Sendable {
    var errorCase: String
    var associatedValue: String?

    enum CodingKeys: String, CodingKey {
        case errorCase = "case"
        case associatedValue
    }
}

struct CloudInstallURLSessionError: Codable, Equatable, Sendable {
    var domain: String
    var code: Int
    var description: String
}

struct CloudInstallStagingFile: Codable, Equatable, Sendable {
    var path: String
    var bytes: Int
}

struct CloudInstallDiagnosticReport: Codable, Equatable, Sendable {
    var schema: String
    var sessionId: String
    var sessionTimestamp: String
    var wallId: String?
    var releaseId: String?
    var manifestURL: String?
    var assets: [CloudInstallAssetDiagnostic]
    var failureStage: String?
    var cloudAssetError: CloudInstallErrorDiagnostic?
    var urlSessionError: CloudInstallURLSessionError?
    var stagingBeforeDiscard: [CloudInstallStagingFile]?
    var currentActivationStarted: Bool
    var productionRuntimeError: String?
}

/// One refreshAndInstall / installExplicitRelease attempt.
final class CloudInstallDiagnosticSession: @unchecked Sendable {
    let sessionId: String
    let sessionTimestamp: String
    private let lock = NSLock()
    private var wallId: String?
    private var releaseId: String?
    private var manifestURL: String?
    private var assets: [CloudInstallAssetDiagnostic] = []
    private var failureStage: String?
    private var cloudAssetError: CloudInstallErrorDiagnostic?
    private var urlSessionError: CloudInstallURLSessionError?
    private var stagingBeforeDiscard: [CloudInstallStagingFile]?
    private var currentActivationStarted = false
    private var productionRuntimeError: String?
    private var inFlightAssetId: String?

    init(now: Date = Date(), uuid: UUID = UUID()) {
        sessionId = uuid.uuidString
        sessionTimestamp = CloudInstallDiagnosticsStore.timestampString(now)
    }

    func setWallId(_ value: String) {
        lock.lock()
        wallId = value
        lock.unlock()
    }

    func setReleaseId(_ value: String) {
        lock.lock()
        releaseId = value
        lock.unlock()
    }

    func setManifestURL(_ value: String) {
        lock.lock()
        manifestURL = value
        lock.unlock()
    }

    func registerRequiredAssets(_ descriptors: [WallAssetDescriptor], urlFor: (String) -> String) {
        lock.lock()
        defer { lock.unlock() }
        assets = descriptors.map { item in
            CloudInstallAssetDiagnostic(
                assetId: item.assetId,
                url: urlFor(item.assetId),
                expectedBytes: item.bytes,
                expectedSha256: item.sha256,
                downloadStartedAt: nil,
                httpStatus: nil,
                actualBytes: nil,
                actualSha256: nil,
                result: "not_attempted"
            )
        }
    }

    func markDownloadStarted(assetId: String, at date: Date = Date()) {
        lock.lock()
        defer { lock.unlock() }
        inFlightAssetId = assetId
        updateAsset(assetId) { asset in
            asset.downloadStartedAt = CloudInstallDiagnosticsStore.timestampString(date)
        }
    }

    func recordHTTPResponse(url: URL?, status: Int, data: Data) {
        lock.lock()
        defer { lock.unlock() }
        let assetId = inFlightAssetId ?? assetIdMatching(url)
        guard let assetId else { return }
        let sha = CloudIntegrity.sha256Hex(data)
        updateAsset(assetId) { asset in
            asset.httpStatus = status
            asset.actualBytes = data.count
            asset.actualSha256 = sha
            if !(200..<300).contains(status) {
                asset.result = "http_error"
            }
        }
    }

    func recordURLSessionError(_ error: NSError, url: URL?) {
        lock.lock()
        defer { lock.unlock() }
        urlSessionError = CloudInstallURLSessionError(
            domain: error.domain,
            code: error.code,
            description: error.localizedDescription
        )
        let assetId = inFlightAssetId ?? assetIdMatching(url)
        if let assetId {
            updateAsset(assetId) { asset in
                asset.result = "network"
            }
        }
    }

    func recordAssetOutcome(assetId: String, data: Data?, error: CloudAssetError?) {
        lock.lock()
        defer { lock.unlock() }
        updateAsset(assetId) { asset in
            if let data {
                asset.actualBytes = data.count
                asset.actualSha256 = CloudIntegrity.sha256Hex(data)
            }
            if let error {
                asset.result = CloudInstallDiagnosticSession.resultName(for: error, expectedBytes: asset.expectedBytes, actualBytes: data?.count)
            } else {
                asset.result = "ok"
            }
        }
        inFlightAssetId = nil
    }

    func recordFailure(stage: String, error: CloudAssetError) {
        lock.lock()
        defer { lock.unlock() }
        failureStage = stage
        cloudAssetError = CloudInstallErrorDiagnostic(
            errorCase: error.diagnosticCaseName,
            associatedValue: error.diagnosticAssociatedValue
        )
    }

    func recordStagingInventory(_ files: [CloudInstallStagingFile]) {
        lock.lock()
        stagingBeforeDiscard = files
        lock.unlock()
    }

    func markCurrentActivationStarted() {
        lock.lock()
        currentActivationStarted = true
        lock.unlock()
    }

    func recordProductionRuntimeCatch(_ error: Error) {
        lock.lock()
        productionRuntimeError = String(describing: error)
        if failureStage == nil {
            failureStage = "production_runtime"
        }
        if cloudAssetError == nil, let cloud = error as? CloudAssetError {
            cloudAssetError = CloudInstallErrorDiagnostic(
                errorCase: cloud.diagnosticCaseName,
                associatedValue: cloud.diagnosticAssociatedValue
            )
        }
        lock.unlock()
    }

    func snapshot() -> CloudInstallDiagnosticReport {
        lock.lock()
        defer { lock.unlock() }
        return CloudInstallDiagnosticReport(
            schema: CloudInstallDiagnosticsSchema.name,
            sessionId: sessionId,
            sessionTimestamp: sessionTimestamp,
            wallId: wallId,
            releaseId: releaseId,
            manifestURL: manifestURL,
            assets: assets,
            failureStage: failureStage,
            cloudAssetError: cloudAssetError,
            urlSessionError: urlSessionError,
            stagingBeforeDiscard: stagingBeforeDiscard,
            currentActivationStarted: currentActivationStarted,
            productionRuntimeError: productionRuntimeError
        )
    }

    private func assetIdMatching(_ url: URL?) -> String? {
        guard let url else { return nil }
        return assets.first(where: { $0.url == url.absoluteString })?.assetId
    }

    private func updateAsset(_ assetId: String, mutate: (inout CloudInstallAssetDiagnostic) -> Void) {
        guard let index = assets.firstIndex(where: { $0.assetId == assetId }) else { return }
        mutate(&assets[index])
    }

    private static func resultName(for error: CloudAssetError, expectedBytes: Int, actualBytes: Int?) -> String {
        switch error {
        case .httpStatus:
            return "http_error"
        case .network:
            return "network"
        case .integrityFailure(let message):
            if message.contains("bytes mismatch") {
                return "bytes_mismatch"
            }
            if message.contains("sha256 mismatch") {
                return "sha256_mismatch"
            }
            if let actualBytes, actualBytes != expectedBytes {
                return "bytes_mismatch"
            }
            return "sha256_mismatch"
        default:
            return "failed"
        }
    }
}

final class CloudInstallDiagnosticsStore: @unchecked Sendable {
    let directory: URL
    private let fileManager: FileManager
    private let lock = NSLock()
    private var lastSession: CloudInstallDiagnosticSession?
    private(set) var lastReportURL: URL?

    init(directory: URL, fileManager: FileManager = .default) {
        self.directory = directory
        self.fileManager = fileManager
    }

    static func applicationSupportStore() throws -> CloudInstallDiagnosticsStore {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        var dir = base
        for component in CloudInstallDiagnosticsSchema.directoryComponents {
            dir.appendPathComponent(component, isDirectory: true)
        }
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return CloudInstallDiagnosticsStore(directory: dir)
    }

    func beginSession(now: Date = Date()) -> CloudInstallDiagnosticSession {
        let session = CloudInstallDiagnosticSession(now: now)
        lock.lock()
        lastSession = session
        lock.unlock()
        return session
    }

    /// Failure-only write. Never throws to the installer. Never writes asset bytes.
    func persistFailure(_ session: CloudInstallDiagnosticSession) {
        let report = session.snapshot()
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let url = directory.appendingPathComponent(filename(for: report), isDirectory: false)
            let data = try Self.encoder.encode(report)
            try data.write(to: url, options: .atomic)
            lock.lock()
            lastSession = session
            lastReportURL = url
            lock.unlock()
        } catch {
            return
        }
    }

    func recordProductionRuntimeCatch(_ error: Error) {
        lock.lock()
        let session = lastSession
        lock.unlock()
        if let session {
            session.recordProductionRuntimeCatch(error)
            persistFailure(session)
            return
        }
        let created = beginSession()
        created.recordProductionRuntimeCatch(error)
        persistFailure(created)
    }

    static func timestampString(_ date: Date) -> String {
        formatter.string(from: date)
    }

    private func filename(for report: CloudInstallDiagnosticReport) -> String {
        let stamp = report.sessionTimestamp
            .replacingOccurrences(of: ":", with: "")
            .replacingOccurrences(of: "-", with: "")
        return "install-\(stamp)-\(report.sessionId).json"
    }

    private static let formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return encoder
    }()
}

extension CloudAssetError {
    var diagnosticCaseName: String {
        switch self {
        case .network: return "network"
        case .httpStatus: return "httpStatus"
        case .decoding: return "decoding"
        case .unsupportedSchema: return "unsupportedSchema"
        case .integrityFailure: return "integrityFailure"
        case .storageFailure: return "storageFailure"
        case .notInstalled: return "notInstalled"
        case .offlineNoCache: return "offlineNoCache"
        case .invalidIdentifier: return "invalidIdentifier"
        case .immutableReleaseConflict: return "immutableReleaseConflict"
        case .missingRequiredSemanticType: return "missingRequiredSemanticType"
        case .semanticTypeNotRequired: return "semanticTypeNotRequired"
        case .duplicateSemanticType: return "duplicateSemanticType"
        }
    }

    var diagnosticAssociatedValue: String? {
        switch self {
        case .network, .decoding, .notInstalled, .offlineNoCache, .immutableReleaseConflict:
            return nil
        case .httpStatus(let status):
            return String(status)
        case .unsupportedSchema(let value),
             .integrityFailure(let value),
             .storageFailure(let value),
             .invalidIdentifier(let value),
             .missingRequiredSemanticType(let value),
             .semanticTypeNotRequired(let value),
             .duplicateSemanticType(let value):
            return value
        }
    }
}
