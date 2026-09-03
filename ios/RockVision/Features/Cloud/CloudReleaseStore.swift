import Foundation

enum ImmutableReleaseInspection {
    case absent
    case valid(LocalValidatedRelease)
    case corrupt
}

struct CloudCurrentPointer: Codable, Equatable, Sendable {
    var wallId: String
    var releaseId: String
    var state: String
}

struct LocalValidatedRelease: Equatable, Sendable {
    var wallId: String
    var releaseId: String
    var manifest: WallManifest
    var rootURL: URL

    func fileURL(forAssetId assetId: String) -> URL {
        rootURL.appendingPathComponent("assets", isDirectory: true).appendingPathComponent(assetId)
    }
}

/// On-disk published releases. CURRENT is a pointer, never a half-written directory.
final class CloudReleaseStore: @unchecked Sendable {
    let rootURL: URL
    private let fileManager: FileManager
    private let lock = NSLock()

    init(rootURL: URL, fileManager: FileManager = .default) {
        self.rootURL = rootURL
        self.fileManager = fileManager
    }

    static func applicationSupportStore() throws -> CloudReleaseStore {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return CloudReleaseStore(rootURL: base.appendingPathComponent("CloudAssets", isDirectory: true))
    }

    func wallRoot(_ wallId: String) throws -> URL {
        try CloudIdentifier.requireWallId(wallId)
        return rootURL.appendingPathComponent("walls", isDirectory: true).appendingPathComponent(wallId, isDirectory: true)
    }

    func releaseURL(wallId: String, releaseId: String) throws -> URL {
        try CloudIdentifier.requireReleaseId(releaseId)
        return try wallRoot(wallId)
            .appendingPathComponent("releases", isDirectory: true)
            .appendingPathComponent(releaseId, isDirectory: true)
    }

    func stagingURL(wallId: String, releaseId: String) throws -> URL {
        try CloudIdentifier.requireReleaseId(releaseId)
        return try wallRoot(wallId)
            .appendingPathComponent("staging", isDirectory: true)
            .appendingPathComponent(releaseId, isDirectory: true)
    }

    func currentPointerURL(wallId: String) throws -> URL {
        try wallRoot(wallId).appendingPathComponent("current.json")
    }

    func currentRelease(wallId: String) throws -> LocalValidatedRelease {
        lock.lock()
        defer { lock.unlock() }
        return try loadCurrentLocked(wallId: wallId)
    }

    func currentReleaseIfPresent(wallId: String) -> LocalValidatedRelease? {
        try? currentRelease(wallId: wallId)
    }

    func inspectImmutableRelease(wallId: String, releaseId: String) -> ImmutableReleaseInspection {
        lock.lock()
        defer { lock.unlock() }
        return inspectImmutableReleaseLocked(wallId: wallId, releaseId: releaseId)
    }

    /// Points CURRENT at an already-valid immutable tree. Never replaces that tree.
    func adoptExistingReleaseAsCurrent(wallId: String, releaseId: String) throws -> LocalValidatedRelease {
        lock.lock()
        defer { lock.unlock() }
        switch inspectImmutableReleaseLocked(wallId: wallId, releaseId: releaseId) {
        case .absent:
            throw CloudAssetError.notInstalled
        case .corrupt:
            throw CloudAssetError.storageFailure("local immutable release is corrupt")
        case .valid:
            try writeCurrentPointerLocked(wallId: wallId, releaseId: releaseId)
            return try loadCurrentLocked(wallId: wallId)
        }
    }

    func deleteAssetIfPresent(assetId: String, inReleaseRoot root: URL) {
        let url = root.appendingPathComponent("assets", isDirectory: true).appendingPathComponent(assetId)
        if fileManager.fileExists(atPath: url.path) {
            try? fileManager.removeItem(at: url)
        }
    }

    /// Writes only after in-memory verify. Re-reads and verifies; deletes the file if post-write verify fails.
    func commitVerifiedAsset(_ data: Data, descriptor: WallAssetDescriptor, toReleaseRoot root: URL) throws {
        try CloudIntegrity.verify(data: data, descriptor: descriptor)
        try writeAsset(data, assetId: descriptor.assetId, toReleaseRoot: root)
        let url = root.appendingPathComponent("assets", isDirectory: true).appendingPathComponent(descriptor.assetId)
        do {
            let written = try Data(contentsOf: url)
            try CloudIntegrity.verify(data: written, descriptor: descriptor)
        } catch {
            deleteAssetIfPresent(assetId: descriptor.assetId, inReleaseRoot: root)
            throw error
        }
    }

    /// If a file is present but fails integrity, delete it. Returns whether a valid file remains.
    @discardableResult
    func verifyOrDeleteAsset(descriptor: WallAssetDescriptor, inReleaseRoot root: URL) throws -> Bool {
        let url = root.appendingPathComponent("assets", isDirectory: true).appendingPathComponent(descriptor.assetId)
        guard fileManager.fileExists(atPath: url.path) else {
            return false
        }
        do {
            let data = try Data(contentsOf: url)
            try CloudIntegrity.verify(data: data, descriptor: descriptor)
            return true
        } catch {
            deleteAssetIfPresent(assetId: descriptor.assetId, inReleaseRoot: root)
            return false
        }
    }

    func validatedAssetURL(wallId: String, assetId: String) throws -> URL {
        lock.lock()
        defer { lock.unlock() }
        try CloudIdentifier.requireAssetId(assetId)
        let release = try loadCurrentLocked(wallId: wallId)
        guard let descriptor = release.manifest.assets.first(where: { $0.assetId == assetId }) else {
            throw CloudAssetError.notInstalled
        }
        let url = release.fileURL(forAssetId: assetId)
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw CloudAssetError.notInstalled
        }
        do {
            try CloudIntegrity.verify(data: data, descriptor: descriptor)
        } catch {
            if !descriptor.required {
                try? fileManager.removeItem(at: url)
            }
            throw CloudAssetError.notInstalled
        }
        return url
    }

    func prepareStaging(wallId: String, releaseId: String) throws -> URL {
        lock.lock()
        defer { lock.unlock() }
        let staging = try stagingURL(wallId: wallId, releaseId: releaseId)
        if fileManager.fileExists(atPath: staging.path) {
            try fileManager.removeItem(at: staging)
        }
        try fileManager.createDirectory(
            at: staging.appendingPathComponent("assets", isDirectory: true),
            withIntermediateDirectories: true
        )
        return staging
    }

    func writeManifest(_ manifest: WallManifest, toReleaseRoot root: URL) throws {
        let url = root.appendingPathComponent("manifest.json")
        let data = try JSONEncoder().encode(manifest)
        try data.write(to: url, options: .atomic)
    }

    func writeAsset(_ data: Data, assetId: String, toReleaseRoot root: URL) throws {
        try CloudIdentifier.requireAssetId(assetId)
        let url = root.appendingPathComponent("assets", isDirectory: true).appendingPathComponent(assetId)
        try data.write(to: url, options: .atomic)
    }

    func discardStaging(wallId: String, releaseId: String) {
        lock.lock()
        defer { lock.unlock() }
        if let staging = try? stagingURL(wallId: wallId, releaseId: releaseId),
           fileManager.fileExists(atPath: staging.path) {
            try? fileManager.removeItem(at: staging)
        }
    }

    /// Promotes a verified staging tree into a **new** immutable releaseId. Never replaces an existing same id.
    func activateVerifiedStaging(wallId: String, releaseId: String, manifest: WallManifest) throws -> LocalValidatedRelease {
        lock.lock()
        defer { lock.unlock() }
        let destination = try releaseURL(wallId: wallId, releaseId: releaseId)
        let staging = try stagingURL(wallId: wallId, releaseId: releaseId)
        try verifyReleaseTreeLocked(root: staging, wallId: wallId, releaseId: releaseId, manifest: manifest)
        try fileManager.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fileManager.fileExists(atPath: destination.path) {
            throw CloudAssetError.immutableReleaseConflict
        }
        try fileManager.moveItem(at: staging, to: destination)
        do {
            try verifyReleaseTreeLocked(root: destination, wallId: wallId, releaseId: releaseId, manifest: manifest)
        } catch {
            throw error
        }
        try writeCurrentPointerLocked(wallId: wallId, releaseId: releaseId)
        return try loadCurrentLocked(wallId: wallId)
    }

    private func inspectImmutableReleaseLocked(wallId: String, releaseId: String) -> ImmutableReleaseInspection {
        let root: URL
        do {
            root = try releaseURL(wallId: wallId, releaseId: releaseId)
        } catch {
            return .corrupt
        }
        guard fileManager.fileExists(atPath: root.path) else {
            return .absent
        }
        do {
            let manifestData = try Data(contentsOf: root.appendingPathComponent("manifest.json"))
            let manifest = try CloudAssetContract.decodeManifest(manifestData)
            try verifyReleaseTreeLocked(root: root, wallId: wallId, releaseId: releaseId, manifest: manifest)
            return .valid(LocalValidatedRelease(wallId: wallId, releaseId: releaseId, manifest: manifest, rootURL: root))
        } catch {
            return .corrupt
        }
    }

    private func writeCurrentPointerLocked(wallId: String, releaseId: String) throws {
        let pointer = CloudCurrentPointer(wallId: wallId, releaseId: releaseId, state: "READY")
        let pointerData = try JSONEncoder().encode(pointer)
        let pointerURL = try currentPointerURL(wallId: wallId)
        try fileManager.createDirectory(at: pointerURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let tmp = pointerURL.appendingPathExtension("tmp")
        try pointerData.write(to: tmp, options: .atomic)
        if fileManager.fileExists(atPath: pointerURL.path) {
            try fileManager.removeItem(at: pointerURL)
        }
        try fileManager.moveItem(at: tmp, to: pointerURL)
    }

    private func loadCurrentLocked(wallId: String) throws -> LocalValidatedRelease {
        let pointerURL = try currentPointerURL(wallId: wallId)
        guard fileManager.fileExists(atPath: pointerURL.path) else {
            throw CloudAssetError.notInstalled
        }
        let pointer: CloudCurrentPointer
        do {
            pointer = try JSONDecoder().decode(CloudCurrentPointer.self, from: try Data(contentsOf: pointerURL))
        } catch {
            throw CloudAssetError.storageFailure("current pointer unreadable")
        }
        guard pointer.wallId == wallId, pointer.state == "READY" else {
            throw CloudAssetError.notInstalled
        }
        let root = try releaseURL(wallId: wallId, releaseId: pointer.releaseId)
        let manifestData: Data
        do {
            manifestData = try Data(contentsOf: root.appendingPathComponent("manifest.json"))
        } catch {
            throw CloudAssetError.storageFailure("current manifest missing")
        }
        let manifest = try CloudAssetContract.decodeManifest(manifestData)
        try verifyReleaseTreeLocked(root: root, wallId: wallId, releaseId: pointer.releaseId, manifest: manifest)
        return LocalValidatedRelease(wallId: wallId, releaseId: pointer.releaseId, manifest: manifest, rootURL: root)
    }

    private func verifyReleaseTreeLocked(
        root: URL,
        wallId: String,
        releaseId: String,
        manifest: WallManifest
    ) throws {
        guard manifest.wallId == wallId, manifest.releaseId == releaseId else {
            throw CloudAssetError.integrityFailure("manifest identity mismatch")
        }
        for asset in manifest.assets where asset.required {
            let url = root.appendingPathComponent("assets", isDirectory: true).appendingPathComponent(asset.assetId)
            let data: Data
            do {
                data = try Data(contentsOf: url)
            } catch {
                throw CloudAssetError.integrityFailure("missing required asset \(asset.assetId)")
            }
            try CloudIntegrity.verify(data: data, descriptor: asset)
        }
    }
}
