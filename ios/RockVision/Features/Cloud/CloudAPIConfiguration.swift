import Foundation

/// Central Cloud Asset API v1 base URL. The IP is not the long-term contract.
struct CloudAPIConfiguration: Equatable, Sendable {
    enum Kind: Equatable, Sendable {
        /// Temporary HTTP development endpoint only. Not production.
        case developmentTemporaryHTTP
        /// Intended production hostname. ICP / DNS / HTTPS are not complete.
        case productionHTTPS
        case custom(URL)
    }

    var kind: Kind

    /// Development-only temporary endpoint. Do not treat as the production contract.
    static let developmentTemporaryHTTPURL = URL(string: "http://124.223.178.91")!

    /// Target production URL. Not claimed live. Do not fall back to a bare HTTP IP.
    static let productionHTTPSURL = URL(string: "https://api.cragpal.com")!

    var baseURL: URL {
        switch kind {
        case .developmentTemporaryHTTP:
            return Self.developmentTemporaryHTTPURL
        case .productionHTTPS:
            return Self.productionHTTPSURL
        case .custom(let url):
            return url
        }
    }

    static let development = CloudAPIConfiguration(kind: .developmentTemporaryHTTP)
    static let production = CloudAPIConfiguration(kind: .productionHTTPS)

    static func custom(_ url: URL) -> CloudAPIConfiguration {
        CloudAPIConfiguration(kind: .custom(url))
    }

    #if DEBUG
    static let `default` = CloudAPIConfiguration.development
    #else
    static let `default` = CloudAPIConfiguration.production
    #endif
}
