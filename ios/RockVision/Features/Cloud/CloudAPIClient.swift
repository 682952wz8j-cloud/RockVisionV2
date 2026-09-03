import Foundation

protocol CloudHTTPTransport: Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

struct URLSessionCloudTransport: CloudHTTPTransport {
    let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw CloudAssetError.network
        }
    }
}

struct CloudAPIClient: Sendable {
    var configuration: CloudAPIConfiguration
    var transport: any CloudHTTPTransport

    init(configuration: CloudAPIConfiguration, transport: any CloudHTTPTransport = URLSessionCloudTransport()) {
        self.configuration = configuration
        self.transport = transport
    }

    func fetchCatalog() async throws -> WallCatalog {
        let request = URLRequest(url: try catalogURL())
        let data = try await fetchData(request)
        return try CloudAssetContract.decodeCatalog(data)
    }

    func fetchManifest(wallId: String) async throws -> WallManifest {
        try CloudIdentifier.requireWallId(wallId)
        let request = URLRequest(url: try manifestURL(wallId: wallId))
        let data = try await fetchData(request)
        let manifest = try CloudAssetContract.decodeManifest(data)
        guard manifest.wallId == wallId else {
            throw CloudAssetError.decoding
        }
        return manifest
    }

    /// Immutable explicit release. Does not consult catalog or `latestReleaseId`.
    func fetchManifest(wallId: String, releaseId: String) async throws -> WallManifest {
        try CloudIdentifier.requireWallId(wallId)
        try CloudIdentifier.requireReleaseId(releaseId)
        let request = URLRequest(url: try releaseManifestURL(wallId: wallId, releaseId: releaseId))
        let data = try await fetchData(request)
        let manifest = try CloudAssetContract.decodeManifest(data)
        guard manifest.wallId == wallId, manifest.releaseId == releaseId else {
            throw CloudAssetError.decoding
        }
        return manifest
    }

    /// Downloads one asset for a frozen `releaseId`. Never substitutes `latestReleaseId`.
    func downloadAsset(wallId: String, releaseId: String, assetId: String) async throws -> Data {
        try CloudIdentifier.requireWallId(wallId)
        try CloudIdentifier.requireReleaseId(releaseId)
        try CloudIdentifier.requireAssetId(assetId)
        let request = URLRequest(url: try assetURL(wallId: wallId, releaseId: releaseId, assetId: assetId))
        return try await fetchData(request)
    }

    func catalogURL() throws -> URL {
        try url(path: ["v1", "walls"])
    }

    func manifestURL(wallId: String) throws -> URL {
        try CloudIdentifier.requireWallId(wallId)
        return try url(path: ["v1", "walls", wallId, "manifest"])
    }

    func releaseManifestURL(wallId: String, releaseId: String) throws -> URL {
        try CloudIdentifier.requireWallId(wallId)
        try CloudIdentifier.requireReleaseId(releaseId)
        return try url(path: ["v1", "walls", wallId, "releases", releaseId, "manifest"])
    }

    func assetURL(wallId: String, releaseId: String, assetId: String) throws -> URL {
        try CloudIdentifier.requireWallId(wallId)
        try CloudIdentifier.requireReleaseId(releaseId)
        try CloudIdentifier.requireAssetId(assetId)
        return try url(path: ["v1", "walls", wallId, "releases", releaseId, "assets", assetId])
    }

    private func url(path: [String]) throws -> URL {
        var url = configuration.baseURL
        for component in path {
            url.append(path: component)
        }
        return url
    }

    private func fetchData(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await transport.data(for: request)
        } catch let error as CloudAssetError {
            throw error
        } catch {
            throw CloudAssetError.network
        }
        guard let http = response as? HTTPURLResponse else {
            throw CloudAssetError.network
        }
        guard (200..<300).contains(http.statusCode) else {
            throw CloudAssetError.httpStatus(http.statusCode)
        }
        return data
    }
}
