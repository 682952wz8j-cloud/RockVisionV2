import CryptoKit
import Foundation

enum FieldTestExport {
    static let requiredNames = [
        "samples.jsonl",
        "summary.json",
        "session.json",
        "report.json",
        "manifest.json"
    ]

    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func pasteSummary(
        session: FieldTestSessionRecord,
        summary: FieldTestSummary?,
        samples: [FieldTestSample],
        identity: FieldTestAppIdentity
    ) -> String {
        let valid = samples.filter(\.valid).count
        var lines: [String] = [
            "RockVision Gate 4B Field Test",
            "session: \(session.sessionID)",
            "status: \(session.status)",
            "samples: \(samples.count)  (valid \(valid) / invalid \(samples.count - valid))",
            "OpenCV: \(session.openCVVersion)",
            "App: \(identity.display)",
            "schema: \(FieldTestExportSchema.version)",
            "offlineBaseline: \(FieldTestExportSchema.provenanceOfflineBaseline)",
            "runtimeBaseline: \(FieldTestExportSchema.provenanceRuntimeBaseline)",
            "SIFT: \(session.siftParameters)",
            "testMode: \(session.testMode)",
            "requestedScene: \(session.requestedScene ?? "—")"
        ]
        if let stats = samples.compactMap(\.confirmationStats).last {
            let lastTick = samples.compactMap(\.confirmation).last
            lines.append("localization: \(lastTick?.localizationState ?? ConfirmationConfig.localizationIdle)")
            lines.append("confirmWindow: \(ConfirmationConfig.confirmWindow)  (uncalibrated)")
            lines.append("pnpEval: \(stats.pnpEvaluations)  qualified: \(stats.qualifiedCount)  unqualified: \(stats.unqualifiedCount)")
            lines.append("confirmAttempts: \(stats.confirmationAttemptCount)  localizedEntries: \(stats.localizedEntryCount)  longestStreak: \(stats.longestValidStreak)")
            lines.append("resets: \(stats.resetCount)  unqual=\(stats.resetUnqualified) rot=\(stats.resetAdjacentRotation) cWall=\(stats.resetAdjacentCWall) depth=\(stats.resetPositiveDepth) nonFinite=\(stats.resetNonFinite) flip=\(stats.resetAntiFlip)")
            lines.append("afterLocalizedAccepted: \(stats.acceptedAfterFirstLocalized)  localizedLosses: \(stats.localizedLossCount)")
            if let seq = stats.firstLocalizedSequence {
                lines.append("firstLocalizedSequence: \(seq.map(String.init).joined(separator: ","))")
            }
            lines.append("confirmedEqualsLatestRefined: \(stats.confirmedAlwaysEqualsLatestRefined)")
            let lastAlignment = samples.compactMap(\.alignment).last
            if let aligned = lastAlignment, aligned.hasT_ARWorld_Wall, let id = aligned.provenance?.confirmedFrameID {
                lines.append("T_ARWorld_Wall: yes frame=\(id)")
            } else {
                lines.append("T_ARWorld_Wall: none")
            }
            if let alignStats = samples.compactMap(\.alignmentStats).last {
                lines.append("productionAlignmentCalled: \(alignStats.generatedCount > 0)")
                if let first = alignStats.firstGeneratedFrameID {
                    lines.append("firstT_ARWorld_WallFrameID: \(first)")
                }
                lines.append("alignmentGenerated: \(alignStats.generatedCount)  cleared: \(alignStats.clearedCount)")
                lines.append("renderedRoute: \(alignStats.renderedRoute)")
            }
            let lastGeom = samples.compactMap(\.wallDebugGeometry).last
            if let geom = lastGeom, geom.visible,
               let x = geom.axisLengthX, let y = geom.axisLengthY, let z = geom.axisLengthZ {
                lines.append("wallDebugGeometry: \(geom.kind) visible frame=\(geom.sourceFrameID.map(String.init) ?? "—")")
                lines.append(String(format: "axisLengths_m: X=%.6f Y=%.6f Z=%.6f", x, y, z))
                lines.append("validatedLandmarks: \(geom.validatedLandmarkCount)")
                lines.append("measurementMarkers: \(geom.markerCount ?? geom.markers?.count ?? 0)/4")
                if let markers = geom.markers, !markers.isEmpty {
                    for marker in markers {
                        let predicted = marker.predictedARWorldXYZMeters
                        lines.append(
                            "marker \(marker.landmarkID) wall=\(formatXYZ(marker.wallXYZMeters)) arWorld=\(formatXYZ(predicted)) visibleByAlignment=\(marker.visibleByAlignmentState)"
                        )
                    }
                }
            } else {
                lines.append("wallDebugGeometry: hidden")
            }
        }
        if let summary {
            lines.append("phase: \(summary.phase)")
            for cell in summary.cells where cell.status != .pending {
                if cell.status == .notRequested {
                    lines.append("\(cell.scene) \(cell.presetLabel) notRequested")
                    continue
                }
                var extra = ""
                if let sift = cell.siftMs?.median {
                    extra += "  siftMed=\(String(format: "%.1f", sift))ms"
                }
                if let kp = cell.keypoints?.median {
                    extra += "  kpMed=\(String(format: "%.0f", kp))"
                }
                if let match = cell.matchingMs?.median {
                    extra += "  matchMed=\(String(format: "%.1f", match))ms"
                }
                if let unique = cell.acceptedUniquePoint3D?.median {
                    extra += "  unique3DMed=\(String(format: "%.0f", unique))"
                }
                let corr = samples.filter { $0.valid && $0.scene == cell.scene && $0.presetLabel == cell.presetLabel }
                if let inputMed = FieldTestMetricStats.from(corr.compactMap(\.inputCorrespondenceCount).map(Double.init))?.median {
                    extra += "  pnpInMed=\(String(format: "%.0f", inputMed))"
                }
                let pnp = corr.compactMap(\.pnpDiagnostic)
                if !pnp.isEmpty {
                    let candidates = pnp.filter(\.candidateQualified).count
                    extra += "  pnpCand=\(candidates)/\(pnp.count)"
                    if let inlierMed = FieldTestMetricStats.from(pnp.map { Double($0.inlierCount) })?.median {
                        extra += "  inlierMed=\(String(format: "%.0f", inlierMed))"
                    }
                    if let depthMed = FieldTestMetricStats.from(pnp.compactMap(\.medianInlierDepthMeters))?.median {
                        extra += "  obsDepthMed=\(String(format: "%.2f", depthMed))m"
                    }
                }
                lines.append("\(cell.scene) \(cell.presetLabel) \(cell.status.rawValue) \(cell.progressLabel)\(extra)")
            }
        }
        lines.append("Paste this summary into chat. Attach the Share ZIP for full JSON.")
        return lines.joined(separator: "\n")
    }

    private static func formatXYZ(_ xyz: [Double]) -> String {
        guard xyz.count == 3 else { return "—" }
        return String(format: "[%.6f, %.6f, %.6f]", xyz[0], xyz[1], xyz[2])
    }

    /// Writes official JSON/JSONL into `sessionDir`, then stages a ZIP under `stagingRoot` (tmp only).
    static func writeOfficialSnapshotAndZip(
        sessionDir: URL,
        session: FieldTestSessionRecord,
        summary: FieldTestSummary,
        samples: [FieldTestSample],
        identity: FieldTestAppIdentity,
        encoder: JSONEncoder,
        fileManager: FileManager,
        stagingRoot: URL
    ) throws -> URL {
        let handle = FieldTestSessionHandle(
            directory: sessionDir,
            encoder: encoder,
            decoder: JSONDecoder(),
            fileManager: fileManager
        )
        try handle.writeSamples(samples)
        try handle.writeSummary(summary)
        try handle.writeSession(session)
        try handle.writeReport(session: session, summary: summary, samples: samples)

        let payload = try snapshotPayloads(sessionDir: sessionDir, fileManager: fileManager)
        let exportTime = Date()
        let files = payload.map { name, data in
            FieldTestExportFileEntry(name: name, byteSize: data.count, sha256: sha256Hex(data))
        }
        let manifest = FieldTestExportManifest(
            schemaVersion: FieldTestExportSchema.version,
            sessionID: session.sessionID,
            exportTime: exportTime,
            sessionStatus: session.status,
            sampleCount: samples.count,
            appVersion: identity.version,
            appBuild: identity.build,
            openCVVersion: session.openCVVersion,
            testMode: session.testMode,
            requestedScene: session.requestedScene,
            files: files
        )
        var zipFiles = payload
        zipFiles.append(("manifest.json", try encoder.encode(manifest)))

        let staging = stagingRoot.appendingPathComponent("export-\(UUID().uuidString)", isDirectory: true)
        try fileManager.createDirectory(at: staging, withIntermediateDirectories: true)
        let zipURL = staging.appendingPathComponent("RockVision_FieldTest_\(session.sessionID).zip")
        try FieldTestZip.pack(files: zipFiles, to: zipURL)
        return zipURL
    }

    private static func snapshotPayloads(sessionDir: URL, fileManager: FileManager) throws -> [(String, Data)] {
        let names = ["samples.jsonl", "summary.json", "session.json", "report.json"]
        return try names.map { name in
            let url = sessionDir.appendingPathComponent(name)
            guard fileManager.fileExists(atPath: url.path) else {
                throw FieldTestStorageError.exportFailed("missing official file \(name)")
            }
            return (name, try Data(contentsOf: url))
        }
    }
}

enum FieldTestZip {
    static func pack(files: [(String, Data)], to url: URL) throws {
        var local: Data = Data()
        var central: Data = Data()
        var offset: UInt32 = 0
        for (name, payload) in files {
            let nameData = Data(name.utf8)
            let crc = CRC32.hash(payload)
            let size = UInt32(payload.count)
            var header = Data()
            header.appendUInt32(0x04034b50)
            header.appendUInt16(20)
            header.appendUInt16(0)
            header.appendUInt16(0)
            header.appendUInt16(0)
            header.appendUInt16(0)
            header.appendUInt32(crc)
            header.appendUInt32(size)
            header.appendUInt32(size)
            header.appendUInt16(UInt16(nameData.count))
            header.appendUInt16(0)
            local.append(header)
            local.append(nameData)
            local.append(payload)

            var dir = Data()
            dir.appendUInt32(0x02014b50)
            dir.appendUInt16(20)
            dir.appendUInt16(20)
            dir.appendUInt16(0)
            dir.appendUInt16(0)
            dir.appendUInt16(0)
            dir.appendUInt16(0)
            dir.appendUInt32(crc)
            dir.appendUInt32(size)
            dir.appendUInt32(size)
            dir.appendUInt16(UInt16(nameData.count))
            dir.appendUInt16(0)
            dir.appendUInt16(0)
            dir.appendUInt16(0)
            dir.appendUInt16(0)
            dir.appendUInt32(0)
            dir.appendUInt32(offset)
            central.append(dir)
            central.append(nameData)
            offset += UInt32(header.count + nameData.count + payload.count)
        }
        var eocd = Data()
        eocd.appendUInt32(0x06054b50)
        eocd.appendUInt16(0)
        eocd.appendUInt16(0)
        eocd.appendUInt16(UInt16(files.count))
        eocd.appendUInt16(UInt16(files.count))
        eocd.appendUInt32(UInt32(central.count))
        eocd.appendUInt32(UInt32(local.count))
        eocd.appendUInt16(0)
        var zip = Data()
        zip.append(local)
        zip.append(central)
        zip.append(eocd)
        try zip.write(to: url, options: .atomic)
    }

    static func unpack(_ url: URL) throws -> [String: Data] {
        let data = try Data(contentsOf: url)
        var offset = 0
        var files: [String: Data] = [:]
        while offset + 30 <= data.count {
            let sig: UInt32 = data.readUInt32(at: offset)
            if sig == 0x02014b50 || sig == 0x06054b50 { break }
            guard sig == 0x04034b50 else {
                throw FieldTestStorageError.exportFailed("invalid zip signature")
            }
            let method: UInt16 = data.readUInt16(at: offset + 8)
            let size = Int(data.readUInt32(at: offset + 18))
            let nameLen = Int(data.readUInt16(at: offset + 26))
            let extraLen = Int(data.readUInt16(at: offset + 28))
            let nameStart = offset + 30
            let name = String(data: data.subdata(in: nameStart..<(nameStart + nameLen)), encoding: .utf8) ?? ""
            let dataStart = nameStart + nameLen + extraLen
            guard method == 0 else {
                throw FieldTestStorageError.exportFailed("unsupported zip method")
            }
            files[name] = data.subdata(in: dataStart..<(dataStart + size))
            offset = dataStart + size
        }
        return files
    }
}

private enum CRC32 {
    static let table: [UInt32] = {
        (0..<256).map { i -> UInt32 in
            var c = UInt32(i)
            for _ in 0..<8 {
                c = (c & 1) != 0 ? (0xedb88320 ^ (c >> 1)) : (c >> 1)
            }
            return c
        }
    }()

    static func hash(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xffffffff
        for byte in data {
            crc = table[Int((crc ^ UInt32(byte)) & 0xff)] ^ (crc >> 8)
        }
        return crc ^ 0xffffffff
    }
}

private extension Data {
    mutating func appendUInt16(_ value: UInt16) {
        var le = value.littleEndian
        Swift.withUnsafeBytes(of: &le) { append(contentsOf: $0) }
    }

    mutating func appendUInt32(_ value: UInt32) {
        var le = value.littleEndian
        Swift.withUnsafeBytes(of: &le) { append(contentsOf: $0) }
    }

    func readUInt16(at offset: Int) -> UInt16 {
        UInt16(self[offset]) | UInt16(self[offset + 1]) << 8
    }

    func readUInt32(at offset: Int) -> UInt32 {
        UInt32(self[offset])
            | UInt32(self[offset + 1]) << 8
            | UInt32(self[offset + 2]) << 16
            | UInt32(self[offset + 3]) << 24
    }
}
