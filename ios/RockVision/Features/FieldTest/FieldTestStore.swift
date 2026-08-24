import Foundation

/// Documents/FieldTests persistence. Writes happen after SIFT timing is finished.
final class FieldTestStore {
    let rootURL: URL
    private let fileManager: FileManager
    private let lock = NSLock()
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(rootURL: URL, fileManager: FileManager = .default) {
        self.rootURL = rootURL
        self.fileManager = fileManager
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    static func documentsDirectory() throws -> URL {
        do {
            return try FileManager.default.url(for: .documentDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        } catch {
            throw FieldTestStorageError.documentsUnavailable
        }
    }

    static func documentsStore() throws -> FieldTestStore {
        let docs = try documentsDirectory()
        return FieldTestStore(rootURL: docs.appendingPathComponent("FieldTests", isDirectory: true))
    }

    /// Actual write/read/delete probe. Does not leave a sentinel file.
    func probeStorage() throws {
        try fileManager.createDirectory(at: rootURL, withIntermediateDirectories: true)
        let url = rootURL.appendingPathComponent("storage_probe_\(UUID().uuidString).tmp")
        let payload = Data("rockvision-storage-probe-\(UUID().uuidString)".utf8)
        try payload.write(to: url, options: .atomic)
        let readBack: Data
        do {
            readBack = try Data(contentsOf: url)
            try fileManager.removeItem(at: url)
        } catch {
            try? fileManager.removeItem(at: url)
            throw FieldTestStorageError.persistFailed(error.localizedDescription)
        }
        guard readBack == payload else {
            throw FieldTestStorageError.probeMismatch
        }
    }

    func exportZIP(
        handle: FieldTestSessionHandle,
        session: FieldTestSessionRecord,
        summary: FieldTestSummary,
        samples: [FieldTestSample],
        identity: FieldTestAppIdentity,
        stagingRoot: URL
    ) throws -> URL {
        try FieldTestExport.writeOfficialSnapshotAndZip(
            sessionDir: handle.directory,
            session: session,
            summary: summary,
            samples: samples,
            identity: identity,
            encoder: encoder,
            fileManager: fileManager,
            stagingRoot: stagingRoot
        )
    }

    func createSession(openCVVersion: String, plan: FieldTestRunPlan = .full) throws -> FieldTestSessionHandle {
        try fileManager.createDirectory(at: rootURL, withIntermediateDirectories: true)
        let stamp = Self.timestampFormatter.string(from: Date())
        var id = "gate3b_\(stamp)"
        var url = rootURL.appendingPathComponent(id, isDirectory: true)
        if fileManager.fileExists(atPath: url.path) {
            id = "gate3b_\(stamp)_\(UUID().uuidString.prefix(6))"
            url = rootURL.appendingPathComponent(id, isDirectory: true)
        }
        try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
        let record = FieldTestSessionRecord(
            sessionID: id,
            createdAt: Date(),
            updatedAt: Date(),
            status: "running",
            currentScene: nil,
            currentPreset: nil,
            cellStartedAt: nil,
            openCVVersion: openCVVersion,
            siftParameters: SIFTParameterRecord.summary,
            nativeWidth: 1920,
            nativeHeight: 1440,
            testMode: plan.testMode,
            requestedScene: plan.requestedScene
        )
        let handle = FieldTestSessionHandle(directory: url, encoder: encoder, decoder: decoder, fileManager: fileManager)
        try handle.writeSession(record)
        try handle.writeSummary(FieldTestSummary(
            sessionID: id,
            updatedAt: Date(),
            phase: "idle",
            cells: [],
            testMode: plan.testMode,
            requestedScene: plan.requestedScene
        ))
        return handle
    }

    func latestSession() throws -> FieldTestSessionHandle? {
        var isDir: ObjCBool = false
        guard fileManager.fileExists(atPath: rootURL.path, isDirectory: &isDir), isDir.boolValue else {
            return nil
        }
        let dirs = try fileManager.contentsOfDirectory(at: rootURL, includingPropertiesForKeys: [.creationDateKey], options: [.skipsHiddenFiles])
        let sessions = dirs.filter { $0.hasDirectoryPath }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        guard let url = sessions.last else { return nil }
        return FieldTestSessionHandle(directory: url, encoder: encoder, decoder: decoder, fileManager: fileManager)
    }

    private static let timestampFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        return formatter
    }()
}

final class FieldTestSessionHandle {
    let directory: URL
    var sessionID: String { directory.lastPathComponent }
    var samplesURL: URL { directory.appendingPathComponent("samples.jsonl") }
    var summaryURL: URL { directory.appendingPathComponent("summary.json") }
    var sessionURL: URL { directory.appendingPathComponent("session.json") }
    var reportURL: URL { directory.appendingPathComponent("report.json") }

    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let fileManager: FileManager
    private let lock = NSLock()

    init(directory: URL, encoder: JSONEncoder, decoder: JSONDecoder, fileManager: FileManager) {
        self.directory = directory
        self.encoder = encoder
        self.decoder = decoder
        self.fileManager = fileManager
    }

    func append(_ sample: FieldTestSample) throws {
        lock.lock()
        defer { lock.unlock() }
        var data = try encoder.encode(sample)
        data.append(0x0A)
        if fileManager.fileExists(atPath: samplesURL.path) {
            let handle = try FileHandle(forWritingTo: samplesURL)
            do {
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
                try handle.close()
            } catch {
                try? handle.close()
                throw error
            }
        } else {
            try data.write(to: samplesURL, options: .atomic)
        }
    }

    func writeSamples(_ samples: [FieldTestSample]) throws {
        lock.lock()
        defer { lock.unlock() }
        var data = Data()
        for sample in samples {
            var line = try encoder.encode(sample)
            line.append(0x0A)
            data.append(line)
        }
        try atomicWriteData(data, to: samplesURL)
    }

    func loadSamples() throws -> [FieldTestSample] {
        lock.lock()
        defer { lock.unlock() }
        guard fileManager.fileExists(atPath: samplesURL.path) else { return [] }
        let text = try String(contentsOf: samplesURL, encoding: .utf8)
        return try text.split(whereSeparator: \.isNewline).compactMap { line in
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            return try decoder.decode(FieldTestSample.self, from: Data(trimmed.utf8))
        }
    }

    func writeSummary(_ summary: FieldTestSummary) throws {
        try atomicWrite(summary, to: summaryURL)
    }

    func writeSession(_ session: FieldTestSessionRecord) throws {
        try atomicWrite(session, to: sessionURL)
    }

    func writeReport(session: FieldTestSessionRecord, summary: FieldTestSummary, samples: [FieldTestSample]) throws {
        struct Report: Codable {
            var session: FieldTestSessionRecord
            var summary: FieldTestSummary
            var samples: [FieldTestSample]
        }
        try atomicWrite(Report(session: session, summary: summary, samples: samples), to: reportURL)
    }

    func loadSession() throws -> FieldTestSessionRecord {
        let data = try Data(contentsOf: sessionURL)
        return try decoder.decode(FieldTestSessionRecord.self, from: data)
    }

    func loadSummary() throws -> FieldTestSummary {
        let data = try Data(contentsOf: summaryURL)
        return try decoder.decode(FieldTestSummary.self, from: data)
    }

    private func atomicWrite<T: Encodable>(_ value: T, to url: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        let data = try encoder.encode(value)
        try atomicWriteData(data, to: url)
    }

    private func atomicWriteData(_ data: Data, to url: URL) throws {
        let temp = url.appendingPathExtension("tmp")
        try data.write(to: temp, options: .atomic)
        if fileManager.fileExists(atPath: url.path) {
            _ = try fileManager.replaceItemAt(url, withItemAt: temp)
        } else {
            try fileManager.moveItem(at: temp, to: url)
        }
    }
}
