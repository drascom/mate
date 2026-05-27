import Foundation
import AVFoundation
import Speech
import WhisperKit

/// PRIMARY cihaz-içi STT motoru: WhisperKit (Argmax) — `openai_whisper-small` modeli.
/// Apple SFSpeech Türkçe'de dolu sesi bile boş döndürdüğü için Whisper birincil,
/// SFSpeech yedek. Model ilk kullanımda HuggingFace'ten indirilir (~500MB) ve
/// instance canlı tutulur (her çağrıda yeniden yükleme yok). Model indikten sonra
/// tamamen cihazda çalışır — Apple buluta ses GİTMEZ.
actor WhisperSTT {
    static let shared = WhisperSTT()
    /// Model yüklendi mi — transcribe'ın inme sırasında BLOKLAMAMASI için hızlı (senkron) kontrol.
    /// İnerken false → SFSpeech kullanılır; hazır olunca true → WhisperKit'e geçilir.
    static var modelReady = false

    private let modelName = "openai_whisper-large-v3-v20240930_turbo_632MB"
    private var whisperKit: WhisperKit?
    private var loadTask: Task<WhisperKit, Error>?
    /// İndirme ilerlemesini (0.0–1.0) UI'a bildiren callback. prewarm(progress:)
    /// ile set edilir; download progressCallback'ten (fractionCompleted) beslenir.
    /// MainActor'a marshal edilerek çağrılır.
    private var progressHandler: (@Sendable (Double) -> Void)?

    /// Modeli LAZY ve BİR KEZ yükle. Eşzamanlı çağrılar aynı load Task'i bekler.
    /// İlk transcribe model inene kadar bloklar — kabul (loglanır).
    /// İki aşama: (1) WhisperKit.download(progressCallback:) ile indir (yüzde),
    /// (2) inen klasörden WhisperKit(modelFolder:) ile yükle.
    private func instance() async throws -> WhisperKit {
        if let whisperKit { return whisperKit }
        if let loadTask { return try await loadTask.value }
        let model = modelName
        let handler = progressHandler
        let task = Task { () throws -> WhisperKit in
            let base = Self.modelsDirectory()
            print("[Whisper] model indiriliyor (\(model)) → kalıcı konum: \(base.path)")
            // (1) İndir — fractionCompleted'i UI callback'ine taşı (MainActor'a marshal).
            let folder = try await WhisperKit.download(
                variant: model,
                downloadBase: base,   // Application Support — iOS temizlemez; bir kez iner, bir daha inmez
                progressCallback: { progress in
                    if let handler {
                        let p = progress.fractionCompleted
                        Task { @MainActor in handler(p) }
                    }
                }
            )
            print("[Whisper] model indi, yükleniyor → \(folder.path)")
            // İndirme bitti → UI'da %100 göster (yüklenirken "hazırlanıyor").
            if let handler { Task { @MainActor in handler(1.0) } }
            // (2) İnen klasörden yükle (yeniden indirme yok).
            let config = WhisperKitConfig(
                model: model,
                modelFolder: folder.path,
                prewarm: true,
                load: true,
                download: false
            )
            let kit = try await WhisperKit(config)
            print("[Whisper] model hazır (\(model))")
            return kit
        }
        loadTask = task
        do {
            let kit = try await task.value
            whisperKit = kit
            Self.modelReady = true
            loadTask = nil
            return kit
        } catch {
            // Başarısızsa cache'i temizle ki sonraki çağrı yeniden denesin.
            loadTask = nil
            throw error
        }
    }

    /// Ses dosyasını WhisperKit ile Türkçe (zorlanmış) transkript eder.
    /// .m4a (AAC 48kHz) → WhisperKit içeride AVFoundation ile okur ve 16kHz'e indirir.
    func transcribe(audioURL: URL) async throws -> String {
        let kit = try await instance()
        let options = DecodingOptions(
            task: .transcribe,
            language: "tr",          // dil = "tr" ZORLA (auto-detect değil)
            detectLanguage: false
        )
        let results = try await kit.transcribe(
            audioPath: audioURL.path,
            decodeOptions: options
        )
        let text = results
            .map { $0.text }
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return text
    }

    /// Açılışta arka planda modeli indir/yükle (prewarm) — ilk konuşma beklemesin.
    /// `progress` callback'i indirme ilerlemesini (0.0–1.0) bildirir; MainActor'a
    /// marshal edilerek çağrılır.
    func prewarm(progress: (@Sendable (Double) -> Void)? = nil) async {
        progressHandler = progress
        _ = try? await instance()
        progressHandler = nil
    }

    /// Modellerin kalıcı indirileceği konum: Application Support (iOS bunu temizlemez).
    /// Caches yerine burası kullanılınca model bir kez iner, depolama baskısında silinmez.
    private static func modelsDirectory() -> URL {
        let fm = FileManager.default
        let base = (try? fm.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                appropriateFor: nil, create: true))
            ?? fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = base.appendingPathComponent("WhisperKitModels", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
}

enum OnDeviceSpeechError: LocalizedError {
    case recognizerUnavailable(String)
    case synthesizerFailed
    case bufferAllocFailed
    case emptyTranscript

    var errorDescription: String? {
        switch self {
        case .recognizerUnavailable(let loc): return "Cihazda STT mevcut değil: \(loc)"
        case .synthesizerFailed: return "Cihaz TTS başarısız"
        case .bufferAllocFailed: return "PCM buffer ayrılamadı"
        case .emptyTranscript: return "Boş transkript"
        }
    }
}

enum OnDeviceSTT {
    // Recognizer'ı locale başına SAKLA: her çağrıda yeniden yaratmak on-device modeli
    // tekrar tekrar yükleyip throttle'a sokuyor (ardışık boş sonuçların sebebi). Reuse et.
    private static var cachedRecognizers: [String: SFSpeechRecognizer] = [:]
    private static var activeTask: SFSpeechRecognitionTask?

    /// PRIMARY: WhisperKit; YEDEK: SFSpeech. İmza ConversationManager için AYNI.
    /// Whisper hata atar VEYA boş/whitespace dönerse SFSpeech yedek devreye girer.
    /// `useWhisper == false` → Apple SFSpeech motoru SADECE kullanılır (Whisper'a hiç
    /// gidilmez, model inmez). `useWhisper == true` → mevcut mantık: model hazırsa
    /// Whisper, değilse (iniyorsa) geçici SFSpeech.
    static func transcribe(audioURL: URL, language: String, useWhisper: Bool = true) async throws -> String {
        // TANI: yakalanan dosyanın süresi — boş STT'nin sebebi capture (kısa/sessiz
        // dosya) mı yoksa recognition mı, ayırt etmek için. (Motordan bağımsız logla.)
        if let f = try? AVAudioFile(forReading: audioURL) {
            let sr = f.fileFormat.sampleRate
            let dur = sr > 0 ? Double(f.length) / sr : 0
            print(String(format: "[STT] file dur=%.2fs frames=%lld", dur, f.length))
        } else {
            print("[STT] file AÇILAMADI: \(audioURL.lastPathComponent)")
        }

        // 0) Apple motoru seçiliyse Whisper'a HİÇ gitme — sadece SFSpeech.
        if !useWhisper {
            print("[STT] motor=apple (kullanıcı seçimi) → sfspeech")
            return try await transcribeSFSpeech(audioURL: audioURL, language: language)
        }

        // 1) PRIMARY: WhisperKit — yalnız model HAZIR ise. Model iniyorsa BLOKLAMA;
        // SFSpeech ile geçici devam (option 2). Model inince otomatik Whisper'a geçilir.
        if WhisperSTT.modelReady {
            do {
                let text = try await WhisperSTT.shared.transcribe(audioURL: audioURL)
                if !text.isEmpty {
                    print("[STT] engine=whisper final empty=false")
                    return text
                }
                print("[STT] engine=whisper boş döndü → sfspeech yedek")
            } catch {
                print("[STT] engine=whisper hata: \(error.localizedDescription) → sfspeech yedek")
            }
        } else {
            print("[STT] whisper modeli henüz hazır değil (iniyor) → sfspeech (geçici)")
        }

        // 2) SFSpeech (model inene kadar geçici, veya whisper boş/hata yedeği)
        return try await transcribeSFSpeech(audioURL: audioURL, language: language)
    }

    /// YEDEK SFSpeech yolu (eski davranış). Whisper boş/başarısız olursa kullanılır.
    private static func transcribeSFSpeech(audioURL: URL, language: String) async throws -> String {
        let localeId = language.contains("-")
            ? language
            : (language.lowercased() == "tr" ? "tr-TR" : language)
        let recognizer: SFSpeechRecognizer
        if let cached = cachedRecognizers[localeId] {
            recognizer = cached
        } else {
            guard let r = SFSpeechRecognizer(locale: Locale(identifier: localeId)) else {
                throw OnDeviceSpeechError.recognizerUnavailable(localeId)
            }
            cachedRecognizers[localeId] = r
            recognizer = r
        }
        guard recognizer.isAvailable else {
            throw OnDeviceSpeechError.recognizerUnavailable(localeId)
        }
        // Önceki tanıma görevini iptal et — on-device kaynağı meşgul kalmasın.
        activeTask?.cancel()
        activeTask = nil
        print("[STT] engine=sfspeech onDevice=\(recognizer.supportsOnDeviceRecognition ? "yes" : "no")")

        let request = SFSpeechURLRecognitionRequest(url: audioURL)
        request.shouldReportPartialResults = false
        request.taskHint = .dictation
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }

        return try await withCheckedThrowingContinuation { cont in
            var resumed = false
            let task = recognizer.recognitionTask(with: request) { result, error in
                if resumed { return }
                if let error {
                    print("[STT] recognition ERROR: \(error.localizedDescription)")
                    resumed = true
                    Self.activeTask = nil
                    cont.resume(throwing: error)
                    return
                }
                guard let result, result.isFinal else { return }
                resumed = true
                Self.activeTask = nil
                let text = result.bestTranscription.formattedString
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                print("[STT] engine=sfspeech final empty=\(text.isEmpty)")
                cont.resume(returning: text)
            }
            Self.activeTask = task
        }
    }
}

/// CANLI (streaming) cihaz-içi STT. Mic buffer'ları konuşma sürerken
/// `SFSpeechAudioBufferRecognitionRequest`'e beslenir; partial sonuçlar
/// sürekli güncellenir. VAD turu kapanınca `finishText()` o ana kadarki en
/// güncel transcript'i (veya kısa bir timeout ile final'i) döndürür → uzun
/// konuşmalarda batch transcribe gecikmesi ~sıfıra iner.
/// OnDeviceSTT.transcribe yedek olarak korunur.
final class LiveSTT: @unchecked Sendable {
    private let lock = NSLock()
    // lock altında: tap (audio thread) append'i ve start/finish/cancel'in
    // request reset'i yarışmasın.
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var latestText: String = ""
    private var receivedFinal = false
    private var isActive = false

    /// Tanımayı başlat. tr-TR locale mantığı OnDeviceSTT ile aynı.
    func start(language: String) {
        // Önceki oturum sızmasın.
        cancel()

        let localeId = language.contains("-")
            ? language
            : (language.lowercased() == "tr" ? "tr-TR" : language)
        let locale = Locale(identifier: localeId)
        guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
            print("[LiveSTT] recognizer unavailable for \(localeId)")
            return
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }

        lock.lock()
        self.recognizer = recognizer
        self.request = request
        self.latestText = ""
        self.receivedFinal = false
        self.isActive = true
        lock.unlock()

        let task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            // Sonuç handler arbitrary bir queue'da çağrılabilir → @Published/UI
            // güncellemesi yok; sadece lock altında saklanan state güncelleniyor.
            guard let self else { return }
            self.lock.lock()
            if self.isActive {
                if let result {
                    self.latestText = result.bestTranscription.formattedString
                    if result.isFinal { self.receivedFinal = true }
                }
                // Hata: o ana kadarki partial korunsun, final beklenmesin.
                if error != nil { self.receivedFinal = true }
            }
            self.lock.unlock()
        }
        lock.lock()
        self.task = task
        lock.unlock()
        print("[LiveSTT] started locale=\(localeId) onDevice=\(recognizer.supportsOnDeviceRecognition)")
    }

    /// Mic buffer'ı tanımaya besle. Tap callback'inden (audio thread) çağrılabilir;
    /// SFSpeechAudioBufferRecognitionRequest.append thread-safe; lock yalnızca
    /// request referansını start/cancel ile yarıştırmamak için.
    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let request = isActive ? self.request : nil
        lock.unlock()
        request?.append(buffer)
    }

    /// Audio'yu bitir, final sonucu ~1.5s'ye kadar bekle; gelmezse o ana kadarki
    /// en güncel partial'ı döndür. Sonra oturumu temizle.
    func finishText() async -> String {
        lock.lock()
        let active = isActive
        let request = self.request
        lock.unlock()
        guard active else { return "" }
        request?.endAudio()

        let deadline = Date().addingTimeInterval(1.5)
        while Date() < deadline {
            lock.lock()
            let done = receivedFinal
            lock.unlock()
            if done { break }
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        lock.lock()
        let text = latestText.trimmingCharacters(in: .whitespacesAndNewlines)
        cleanupLocked()
        lock.unlock()
        return text
    }

    /// Tanımayı iptal et, saklanan metni sıfırla (barge-in / discard / no-speech).
    func cancel() {
        lock.lock()
        let task = self.task
        cleanupLocked()
        lock.unlock()
        task?.cancel()
    }

    private func cleanupLocked() {
        isActive = false
        task = nil
        request = nil
        recognizer = nil
        latestText = ""
        receivedFinal = false
    }
}

/// AVSpeechSynthesizer'ı PCM buffer'a render eder. Synthesizer kalıcı tutulur —
/// `write(...)` async callback'leri çağırırken referans kaybolursa iOS crash atar.
@MainActor
final class OnDeviceTTS {
    static let shared = OnDeviceTTS()
    private let synthesizer = AVSpeechSynthesizer()
    private var inFlight = false

    struct VoiceOption: Identifiable, Hashable {
        let id: String          // AVSpeechSynthesisVoice.identifier
        let displayName: String
        let language: String
    }

    static func availableVoices(language: String) -> [VoiceOption] {
        let localeId = language.contains("-")
            ? language
            : (language.lowercased() == "tr" ? "tr-TR" : language)
        let prefix = String(localeId.prefix(2)).lowercased()
        return AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.lowercased().hasPrefix(prefix) }
            .map { v in
                let q: String
                switch v.quality {
                case .premium: q = "Premium"
                case .enhanced: q = "Enhanced"
                default: q = "Default"
                }
                return VoiceOption(
                    id: v.identifier,
                    displayName: "\(v.name) (\(q)) — \(v.language)",
                    language: v.language
                )
            }
            .sorted { $0.displayName < $1.displayName }
    }

    func synthesize(text: String, language: String, voiceId: String) async throws -> AVAudioPCMBuffer {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw OnDeviceSpeechError.emptyTranscript }

        // Aynı anda iki write çalıştırma — AVSpeechSynthesizer tek queue'ya sahip.
        while inFlight {
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        inFlight = true
        defer { inFlight = false }

        let utterance = AVSpeechUtterance(string: trimmed)
        if !voiceId.isEmpty, let v = AVSpeechSynthesisVoice(identifier: voiceId) {
            utterance.voice = v
        } else {
            let localeId = language.contains("-")
                ? language
                : (language.lowercased() == "tr" ? "tr-TR" : language)
            utterance.voice = AVSpeechSynthesisVoice(language: localeId)
        }

        return try await withCheckedThrowingContinuation { cont in
            var resumed = false
            var collected: [AVAudioPCMBuffer] = []
            var detectedFormat: AVAudioFormat?

            synthesizer.write(utterance) { buffer in
                if resumed { return }
                guard let pcm = buffer as? AVAudioPCMBuffer else {
                    resumed = true
                    cont.resume(throwing: OnDeviceSpeechError.synthesizerFailed)
                    return
                }
                if pcm.frameLength == 0 {
                    // Bitti — chunk'ları birleştir.
                    guard let fmt = detectedFormat else {
                        resumed = true
                        cont.resume(throwing: OnDeviceSpeechError.synthesizerFailed)
                        return
                    }
                    let total = collected.reduce(AVAudioFrameCount(0)) { $0 + $1.frameLength }
                    guard total > 0,
                          let combined = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: total) else {
                        resumed = true
                        cont.resume(throwing: OnDeviceSpeechError.bufferAllocFailed)
                        return
                    }
                    var offset: AVAudioFrameCount = 0
                    let channels = Int(fmt.channelCount)
                    for chunk in collected {
                        let n = Int(chunk.frameLength)
                        if let src = chunk.floatChannelData, let dst = combined.floatChannelData {
                            for ch in 0..<channels {
                                dst[ch].advanced(by: Int(offset)).update(from: src[ch], count: n)
                            }
                        } else if let src = chunk.int16ChannelData, let dst = combined.int16ChannelData {
                            for ch in 0..<channels {
                                dst[ch].advanced(by: Int(offset)).update(from: src[ch], count: n)
                            }
                        }
                        offset += chunk.frameLength
                    }
                    combined.frameLength = total
                    resumed = true
                    cont.resume(returning: combined)
                    return
                }
                if detectedFormat == nil { detectedFormat = pcm.format }
                // Buffer hayatta kalsın diye kopyala — write() reuse edebiliyor.
                if let copy = Self.copyBuffer(pcm) {
                    collected.append(copy)
                }
            }
        }
    }

    private static func copyBuffer(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard let copy = AVAudioPCMBuffer(
            pcmFormat: buffer.format,
            frameCapacity: buffer.frameLength
        ) else { return nil }
        copy.frameLength = buffer.frameLength
        let channels = Int(buffer.format.channelCount)
        let frames = Int(buffer.frameLength)
        if let src = buffer.floatChannelData, let dst = copy.floatChannelData {
            for ch in 0..<channels { dst[ch].update(from: src[ch], count: frames) }
        } else if let src = buffer.int16ChannelData, let dst = copy.int16ChannelData {
            for ch in 0..<channels { dst[ch].update(from: src[ch], count: frames) }
        } else if let src = buffer.int32ChannelData, let dst = copy.int32ChannelData {
            for ch in 0..<channels { dst[ch].update(from: src[ch], count: frames) }
        } else {
            return nil
        }
        return copy
    }
}
