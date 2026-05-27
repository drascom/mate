import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss

    @State private var draftVoice = ""
    @State private var draftLanguage = ""
    @State private var draftBridgeKey = ""
    @State private var draftWakeEnabled = true
    @State private var draftWakeWord = "candan"
    @State private var draftCuesEnabled = true
    @State private var draftNoiseFilter = true
    @State private var draftBargeIn = true
    @State private var draftUseOnDeviceTTS = false
    @State private var draftUseWhisperSTT = true
    @State private var draftOnDeviceVoice = ""
    @State private var draftBridgeWSURL = ""

    @State private var onDeviceVoices: [OnDeviceTTS.VoiceOption] = []
    @State private var bridgeVoices: [Voice] = []
    @State private var bridgeVoicesLoading = false
    @State private var bridgeVoicesError: String?

    private let api = APIClient()

    var body: some View {
        NavigationStack {
            Form {
                Section("Ses Motoru") {
                    Picker("STT Motoru", selection: $draftUseWhisperSTT) {
                        Text("Whisper (turbo)").tag(true)
                        Text("Apple").tag(false)
                    }
                    .pickerStyle(.segmented)
                    Text("Whisper Türkçe'de daha iyi (model iner), Apple ise anında ve internetsiz çalışır.")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Toggle("Cihaz TTS (AVSpeechSynthesizer)", isOn: $draftUseOnDeviceTTS)
                    if draftUseOnDeviceTTS {
                        Picker("Cihaz sesi", selection: $draftOnDeviceVoice) {
                            Text("Varsayılan (\(draftLanguage))").tag("")
                            ForEach(onDeviceVoices) { v in
                                Text(v.displayName).tag(v.id)
                            }
                        }
                        .pickerStyle(.menu)
                    }
                    Text("Açıkken ses sentezi cihazda yapılır; kapalıyken bridge kullanılır, erişilemezse cihaza düşülür.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Realtime Bridge (WebSocket TTS)") {
                    TextField("ws://192.168.0.183:8643/ws", text: $draftBridgeWSURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .onChange(of: draftBridgeWSURL) { _ in
                            Task { await loadBridgeVoices() }
                        }

                    bridgeVoicePickerRow

                    if let err = bridgeVoicesError {
                        Text(err)
                            .font(.caption)
                            .foregroundStyle(.red.opacity(0.85))
                    }

                    SecureField("Bridge token", text: $draftBridgeKey)

                    Text("Tanınan metin bridge'e gönderilir, dönen ses gerçek zamanlı çalınır (token boş bırakılabilir).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Wake Word") {
                    Toggle("Wake word kullan", isOn: $draftWakeEnabled)
                    TextField("Tetikleyici kelime (örn: candan)", text: $draftWakeWord)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .disabled(!draftWakeEnabled)
                    Text("Açıkken \"\(draftWakeWord.isEmpty ? "—" : draftWakeWord)\" duyulana kadar bekler; kapalıyken sürekli dinler.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Geçiş Sesleri") {
                    Toggle("Bip sesleri", isOn: $draftCuesEnabled)
                    Text("Wake, konuşma sonu ve uyku geçişlerinde kısa yumuşak tonlar çalar.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Gürültü Filtresi") {
                    Toggle("Adaptif gürültü filtresi", isOn: $draftNoiseFilter)
                    Text("Açıkken ortam sesine göre eşiği uyarlar; kapalıyken sabit eşik kullanır.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Sözünü Kes (Barge-in)") {
                    Toggle("Konuşurken müdahaleye izin ver", isOn: $draftBargeIn)
                    Text("Açıkken konuşmaya başladığında ajan susup sana döner; kapalıyken sözünü bitirir.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section {
                    Button {
                        save()
                    } label: {
                        Text("Kaydet")
                            .frame(maxWidth: .infinity)
                            .fontWeight(.semibold)
                    }
                }
            }
            .navigationTitle("Ayarlar")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Vazgeç") { dismiss() }
                }
            }
            .onAppear {
                draftVoice = settings.voice
                draftLanguage = settings.language
                draftBridgeKey = settings.bridgeApiKey
                draftWakeEnabled = settings.wakeWordEnabled
                draftWakeWord = settings.wakeWord
                draftCuesEnabled = settings.cuesEnabled
                draftNoiseFilter = settings.noiseFilterEnabled
                draftBargeIn = settings.bargeInEnabled
                draftUseOnDeviceTTS = settings.useOnDeviceTTS
                draftUseWhisperSTT = settings.useWhisperSTT
                draftOnDeviceVoice = settings.onDeviceVoiceId
                draftBridgeWSURL = settings.bridgeWSURL
                onDeviceVoices = OnDeviceTTS.availableVoices(language: settings.language)
                Task { await loadBridgeVoices() }
            }
            .onChange(of: draftLanguage) { newLang in
                onDeviceVoices = OnDeviceTTS.availableVoices(language: newLang)
            }
        }
    }

    @ViewBuilder
    private var bridgeVoicePickerRow: some View {
        HStack {
            if bridgeVoicesLoading {
                ProgressView()
                    .controlSize(.small)
                Text("Sesler yükleniyor…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
            } else {
                Picker("Ses", selection: $draftVoice) {
                    if !draftVoice.isEmpty &&
                        !bridgeVoices.contains(where: { $0.filename == draftVoice }) {
                        Text("\(draftVoice) (kayıtlı)").tag(draftVoice)
                    }
                    ForEach(bridgeVoices) { v in
                        Text(v.displayName).tag(v.filename)
                    }
                    if bridgeVoices.isEmpty && draftVoice.isEmpty {
                        Text("—").tag("")
                    }
                }
                .pickerStyle(.menu)
            }
            Button {
                Task { await loadBridgeVoices() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.borderless)
            .disabled(bridgeVoicesLoading)
        }
    }

    /// `ws://host:port/ws` gibi bir WebSocket URL'inden HTTP base türetir:
    /// şema ws→http / wss→https'e çevrilir, path ve query atılır.
    /// Örn: `ws://192.168.0.150:8080/ws` → `http://192.168.0.150:8080`
    private func httpBase(fromWS wsURL: String) -> String? {
        let trimmed = wsURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              var components = URLComponents(string: trimmed),
              let host = components.host, !host.isEmpty
        else { return nil }

        switch components.scheme?.lowercased() {
        case "ws", "http": components.scheme = "http"
        case "wss", "https": components.scheme = "https"
        case .none: components.scheme = "http"
        default: components.scheme = "http"
        }
        components.path = ""
        components.query = nil
        components.fragment = nil
        return components.string
    }

    private func loadBridgeVoices() async {
        guard let base = httpBase(fromWS: draftBridgeWSURL) else {
            bridgeVoices = []
            bridgeVoicesError = "Geçersiz bridge WS URL'i"
            bridgeVoicesLoading = false
            return
        }
        bridgeVoicesLoading = true
        bridgeVoicesError = nil
        do {
            let fetched = try await api.fetchVoices(
                baseURL: base,
                apiKey: draftBridgeKey
            )
            bridgeVoices = fetched
        } catch {
            bridgeVoices = []
            bridgeVoicesError = "Sesler alınamadı: \(error.localizedDescription)"
        }
        bridgeVoicesLoading = false
    }

    private func save() {
        settings.voice = draftVoice.trimmingCharacters(in: .whitespacesAndNewlines)
        settings.language = draftLanguage.trimmingCharacters(in: .whitespacesAndNewlines)
        settings.bridgeApiKey = draftBridgeKey.trimmingCharacters(in: .whitespacesAndNewlines)
        settings.wakeWordEnabled = draftWakeEnabled
        settings.wakeWord = draftWakeWord.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        settings.cuesEnabled = draftCuesEnabled
        settings.noiseFilterEnabled = draftNoiseFilter
        settings.bargeInEnabled = draftBargeIn
        settings.useOnDeviceTTS = draftUseOnDeviceTTS
        settings.useWhisperSTT = draftUseWhisperSTT
        settings.onDeviceVoiceId = draftOnDeviceVoice.trimmingCharacters(in: .whitespacesAndNewlines)
        settings.bridgeWSURL = draftBridgeWSURL.trimmingCharacters(in: .whitespacesAndNewlines)
        dismiss()
    }
}

#Preview {
    SettingsView()
        .environmentObject(SettingsStore())
}
