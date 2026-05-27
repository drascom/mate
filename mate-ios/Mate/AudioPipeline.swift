import Foundation
import AVFoundation

/// Tek bir AVAudioEngine üzerinden hem mic input hem TTS playback geçiriyoruz.
/// Voice processing (`setVoiceProcessingEnabled(true)`) → donanım seviyesinde
/// AEC (acoustic echo cancellation) + noise suppression. TTS sesi mic'e geri
/// dönerken iOS engine içinde otomatik cancel eder, böylece speaker'da bile
/// kendi sesini "kullanıcı konuşması" sanmaz.
@MainActor
final class AudioPipeline {
    static let shared = AudioPipeline()

    let engine = AVAudioEngine()
    let playerNode = AVAudioPlayerNode()

    private var configured = false
    private(set) var connectedFormat: AVAudioFormat?

    private init() {}

    /// İlk çağrıda voice processing'i açıp playerNode'u attach eder.
    /// Sonraki çağrılarda sadece engine'i (varsa duraklatılmış) yeniden başlatır.
    func prepareIfNeeded() throws {
        if !configured {
            try engine.inputNode.setVoiceProcessingEnabled(true)
            engine.attach(playerNode)
            // VPIO input ile aynı format kullan: AEC, output path'ı (echo reference)
            // ile input path'ını aynı sample rate'te ve channel count'ta görmek
            // zorunda; mismatch reference signal'ı kıllar → echo subtraction
            // çalışmaz. iOS device output'a giden resampling'i mainMixer ile
            // outputNode arasında kendi halleder.
            let inputFormat = engine.inputNode.outputFormat(forBus: 0)
            let connectFormat = AVAudioFormat(
                standardFormatWithSampleRate: inputFormat.sampleRate,
                channels: inputFormat.channelCount
            ) ?? engine.mainMixerNode.outputFormat(forBus: 0)
            engine.connect(playerNode, to: engine.mainMixerNode, format: connectFormat)
            connectedFormat = connectFormat
            engine.prepare()
            configured = true
            print("[Pipeline] configured (voice processing ON, connect sr=\(Int(connectFormat.sampleRate))Hz ch=\(connectFormat.channelCount))")
        }
        if !engine.isRunning {
            try engine.start()
            let inputFormat = engine.inputNode.outputFormat(forBus: 0)
            print("[Pipeline] engine started — VP=\(engine.inputNode.isVoiceProcessingEnabled) inputSR=\(Int(inputFormat.sampleRate))Hz ch=\(inputFormat.channelCount)")
        }
    }

    /// Wake mode'a geçerken engine'i durdur — wake kendi AVAudioEngine'ini kullanır,
    /// iki engine aynı anda mic'i tutmasın.
    func pause() {
        if engine.isRunning {
            engine.stop()
            print("[Pipeline] engine paused (wake mode)")
        }
    }

    /// PlayerNode'u verilen format'a bağlar — SADECE format gerçekten değiştiyse.
    /// Engine çalışırken graph topology değişikliği VP IO unit'i render err -1
    /// ile düşürür; bu yüzden format değiştiğinde stop → reconnect → start.
    /// Aynı format için no-op, AEC reference path'ını korur.
    func reconnectPlayer(format: AVAudioFormat) {
        if let current = connectedFormat,
           current.sampleRate == format.sampleRate,
           current.channelCount == format.channelCount {
            return
        }
        let wasRunning = engine.isRunning
        if wasRunning { engine.stop() }
        if connectedFormat != nil {
            engine.disconnectNodeOutput(playerNode)
        }
        engine.connect(playerNode, to: engine.mainMixerNode, format: format)
        connectedFormat = format
        if wasRunning {
            do { try engine.start() }
            catch { print("[Pipeline] engine restart failed: \(error)") }
        }
        print("[Pipeline] player reconnected sr=\(Int(format.sampleRate))Hz ch=\(format.channelCount)")
    }

    static func computeLevel(buffer: AVAudioPCMBuffer) -> Float {
        guard let data = buffer.floatChannelData?[0] else { return 0 }
        let count = Int(buffer.frameLength)
        guard count > 0 else { return 0 }
        var sumSquares: Float = 0
        for i in 0..<count {
            let s = data[i]
            sumSquares += s * s
        }
        let rms = sqrtf(sumSquares / Float(count))
        let db = 20 * log10f(max(rms, 1e-7))
        return normalize(dB: db)
    }

    static func normalize(dB: Float) -> Float {
        let minDb: Float = -55
        if dB < minDb { return 0 }
        if dB >= 0 { return 1 }
        return (dB - minDb) / -minDb
    }
}
