import Foundation
import AVFoundation

/// AudioPipeline (voice-processing'li shared engine) üzerinden kayıt yapan facade.
/// AVAudioRecorder yerine AVAudioEngine input tap kullanır → AEC + noise
/// suppression buffer'lara uygulanır, hem dosyaya hem level callback'e temiz ses gider.
@MainActor
final class AudioRecorder: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var isCapturingSegment = false
    @Published var level: Float = 0

    private let pipeline = AudioPipeline.shared
    private var file: AVAudioFile?
    private var fileURL: URL?
    private var tapInstalled = false
    private var ringBuffers: [AVAudioPCMBuffer] = []
    private var ringFrameCount: AVAudioFramePosition = 0
    private var maxRingFrames: AVAudioFramePosition = 48_000

    var onLevel: ((Float) -> Void)?
    /// Her kopyalanmış mic buffer'ı için çağrılır (canlı STT beslemesi).
    /// Tap (gerçek-zamanlı audio thread) üzerinden çağrılır — alıcı
    /// @Published/UI dokunuşunu kendisi MainActor'a marshal etmeli.
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?

    func requestPermission() async -> Bool {
        if #available(iOS 17.0, *) {
            return await withCheckedContinuation { cont in
                AVAudioApplication.requestRecordPermission { granted in
                    cont.resume(returning: granted)
                }
            }
        } else {
            return await withCheckedContinuation { cont in
                AVAudioSession.sharedInstance().requestRecordPermission { granted in
                    cont.resume(returning: granted)
                }
            }
        }
    }

    func startMonitoring() throws {
        try pipeline.prepareIfNeeded()

        guard !tapInstalled else {
            try pipeline.prepareIfNeeded()
            isRecording = true
            return
        }

        let inputNode = pipeline.engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)
        maxRingFrames = AVAudioFramePosition(inputFormat.sampleRate * 2.5)

        var firstBufferLogged = false
        var bufferCount = 0
        print("[Recorder] tap install, format=\(inputFormat.sampleRate)Hz \(inputFormat.channelCount)ch")
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, _ in
            guard let self else { return }
            if let copy = Self.copyBuffer(buffer) {
                self.ringBuffers.append(copy)
                self.ringFrameCount += AVAudioFramePosition(copy.frameLength)
                while self.ringFrameCount > self.maxRingFrames, !self.ringBuffers.isEmpty {
                    let removed = self.ringBuffers.removeFirst()
                    self.ringFrameCount -= AVAudioFramePosition(removed.frameLength)
                }
            }
            try? self.file?.write(from: buffer)
            // Canlı STT beslemesi — konuşurken tanıma yürüsün.
            self.onBuffer?(buffer)
            let lvl = AudioPipeline.computeLevel(buffer: buffer)
            bufferCount += 1
            if !firstBufferLogged {
                firstBufferLogged = true
                print("[Recorder] first buffer: frames=\(buffer.frameLength) level=\(String(format: "%.3f", lvl))")
            }
            DispatchQueue.main.async {
                self.level = lvl
                self.onLevel?(lvl)
            }
        }
        tapInstalled = true
        isRecording = true
    }

    func start() throws -> URL {
        try startMonitoring()
        return try beginSegment(includePreRoll: false)
    }

    @discardableResult
    func beginSegment(includePreRoll: Bool = true, preRollSeconds: Double = 0.75) throws -> URL {
        try startMonitoring()
        file = nil
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("rec-\(UUID().uuidString).m4a")
        let inputFormat = pipeline.engine.inputNode.outputFormat(forBus: 0)
        let fileSettings = Self.fileSettings(for: inputFormat)
        let outFile = try AVAudioFile(forWriting: url, settings: fileSettings)
        file = outFile
        fileURL = url
        isCapturingSegment = true

        if includePreRoll {
            let framesNeeded = AVAudioFramePosition(inputFormat.sampleRate * preRollSeconds)
            var collected: AVAudioFramePosition = 0
            var selected: [AVAudioPCMBuffer] = []
            for buffer in ringBuffers.reversed() {
                selected.append(buffer)
                collected += AVAudioFramePosition(buffer.frameLength)
                if collected >= framesNeeded { break }
            }
            for buffer in selected.reversed() {
                try? outFile.write(from: buffer)
                // Pre-roll'ü canlı STT'ye de gönder (ilk hece tanımaya girsin).
                onBuffer?(buffer)
            }
            print("[Recorder] segment begin, preRollFrames=\(collected)")
        } else {
            print("[Recorder] segment begin")
        }
        return url
    }

    /// Mevcut kayıt dosyasını kapat, **aynı tap'ı koruyarak** yeni bir dosyaya
    /// yazmaya başla. Eski URL döner (caller silebilir). Barge-in trigger anında
    /// TTS-echo dolu dosyayı atıp temiz dosyaya geçmek için kullanılır.
    /// Tap durdurulmadığı için frame kaybı yok.
    func rotateFile() throws -> URL? {
        guard isRecording else { return nil }
        let oldURL = fileURL
        let newURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("rec-\(UUID().uuidString).m4a")
        let inputFormat = pipeline.engine.inputNode.outputFormat(forBus: 0)
        let fileSettings = Self.fileSettings(for: inputFormat)
        let newFile = try AVAudioFile(forWriting: newURL, settings: fileSettings)
        file = newFile
        fileURL = newURL
        isCapturingSegment = true
        print("[Recorder] file rotated")
        return oldURL
    }

    @discardableResult
    func finishSegment() -> URL? {
        file = nil
        let url = fileURL
        fileURL = nil
        isCapturingSegment = false
        return url
    }

    func discardSegment() {
        if let url = finishSegment() {
            try? FileManager.default.removeItem(at: url)
        }
    }

    @discardableResult
    func stop() -> URL? {
        if tapInstalled {
            pipeline.engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        file = nil  // dosya flush
        let url = fileURL
        fileURL = nil
        isRecording = false
        isCapturingSegment = false
        level = 0
        ringBuffers.removeAll()
        ringFrameCount = 0
        return url
    }

    static func normalize(dB: Float) -> Float {
        AudioPipeline.normalize(dB: dB)
    }

    private static func fileSettings(for format: AVAudioFormat) -> [String: Any] {
        [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue
        ]
    }

    private static func copyBuffer(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard let copy = AVAudioPCMBuffer(
            pcmFormat: buffer.format,
            frameCapacity: buffer.frameCapacity
        ) else { return nil }
        copy.frameLength = buffer.frameLength
        let channels = Int(buffer.format.channelCount)
        let frames = Int(buffer.frameLength)
        if let source = buffer.floatChannelData, let dest = copy.floatChannelData {
            for channel in 0..<channels {
                dest[channel].update(from: source[channel], count: frames)
            }
        } else if let source = buffer.int16ChannelData, let dest = copy.int16ChannelData {
            for channel in 0..<channels {
                dest[channel].update(from: source[channel], count: frames)
            }
        } else if let source = buffer.int32ChannelData, let dest = copy.int32ChannelData {
            for channel in 0..<channels {
                dest[channel].update(from: source[channel], count: frames)
            }
        } else {
            return nil
        }
        return copy
    }
}
