import Foundation
import Combine

@MainActor
final class SettingsStore: ObservableObject {
    private let defaults = UserDefaults.standard

    @Published var bridgeApiKey: String { didSet { defaults.set(bridgeApiKey, forKey: "bridgeApiKey") } }
    @Published var voice: String { didSet { defaults.set(voice, forKey: "voice") } }
    @Published var language: String { didSet { defaults.set(language, forKey: "language") } }
    @Published var wakeWordEnabled: Bool { didSet { defaults.set(wakeWordEnabled, forKey: "wakeWordEnabled") } }
    @Published var wakeWord: String { didSet { defaults.set(wakeWord, forKey: "wakeWord") } }
    @Published var cuesEnabled: Bool { didSet { defaults.set(cuesEnabled, forKey: "cuesEnabled") } }
    @Published var noiseFilterEnabled: Bool { didSet { defaults.set(noiseFilterEnabled, forKey: "noiseFilterEnabled") } }
    @Published var bargeInEnabled: Bool { didSet { defaults.set(bargeInEnabled, forKey: "bargeInEnabled") } }
    // Cihaz TTS yedek/override: açıkken bridge atlanır, doğrudan AVSpeechSynthesizer kullanılır.
    @Published var useOnDeviceTTS: Bool { didSet { defaults.set(useOnDeviceTTS, forKey: "useOnDeviceTTS") } }
    @Published var onDeviceVoiceId: String { didSet { defaults.set(onDeviceVoiceId, forKey: "onDeviceVoiceId") } }
    // STT motoru: true → WhisperKit (cihaz-içi, Türkçe iyi, model iner),
    // false → Apple SFSpeech (anında, internetsiz, Türkçe zayıf). Apple seçiliyse
    // Whisper modeli HİÇ indirilmez.
    @Published var useWhisperSTT: Bool { didSet { defaults.set(useWhisperSTT, forKey: "useWhisperSTT") } }
    // Realtime bridge (WebSocket TTS): STT cihazda yapılır, tanınan metin WS ile
    // bridge'e gönderilir, gelen pcm_f32le parçaları gerçek zamanlı çalınır.
    @Published var bridgeWSURL: String { didSet { defaults.set(bridgeWSURL, forKey: "bridgeWSURL") } }

    init() {
        self.bridgeApiKey = defaults.string(forKey: "bridgeApiKey") ?? ""
        self.voice = defaults.string(forKey: "voice") ?? "ayhan.mp3"
        self.language = defaults.string(forKey: "language") ?? "tr"
        self.wakeWordEnabled = defaults.object(forKey: "wakeWordEnabled") as? Bool ?? true
        self.wakeWord = defaults.string(forKey: "wakeWord") ?? "candan"
        self.cuesEnabled = defaults.object(forKey: "cuesEnabled") as? Bool ?? true
        self.noiseFilterEnabled = defaults.object(forKey: "noiseFilterEnabled") as? Bool ?? true
        self.bargeInEnabled = defaults.object(forKey: "bargeInEnabled") as? Bool ?? true
        self.useOnDeviceTTS = defaults.object(forKey: "useOnDeviceTTS") as? Bool ?? false
        self.onDeviceVoiceId = defaults.string(forKey: "onDeviceVoiceId") ?? ""
        self.useWhisperSTT = defaults.object(forKey: "useWhisperSTT") as? Bool ?? true
        self.bridgeWSURL = defaults.string(forKey: "bridgeWSURL") ?? "ws://192.168.0.183:8643/ws"
    }
}
