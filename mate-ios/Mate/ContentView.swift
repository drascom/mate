import SwiftUI

struct ContentView: View {
    @EnvironmentObject var settings: SettingsStore
    @EnvironmentObject var conversation: ConversationManager
    @State private var showSettings = false
    @State private var serverAlertMessage: String?

    var body: some View {
        ZStack {
            backgroundGradient
                .ignoresSafeArea()

            VStack(spacing: 0) {
                topBar

                Spacer(minLength: 12)

                centerVisual
                    .frame(height: 280)

                statusText
                    .frame(height: 56)          // sabit → state değişince kaymaz

                Spacer(minLength: 12)

                transcriptSlot
                    .frame(height: 82)          // sabit slot (biraz kısaltıldı — üstten)
                    .padding(.bottom, 18)       // play/pause butonundan boşluk (alttan yukarı)

                controlBar
                    .padding(.bottom, 20)
            }
            .padding(.top, 8)
        }
        .overlay(alignment: .top) {
            if conversation.modelLoading {
                HStack(spacing: 10) {
                    ProgressView().tint(.white)
                    Text(modelBannerText)
                        .font(.footnote)
                        .foregroundStyle(.white)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.ultraThinMaterial, in: Capsule())
                .padding(.top, 12)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut, value: conversation.modelLoading)
        .sheet(isPresented: $showSettings) {
            SettingsView()
                .environmentObject(settings)
        }
        .onChange(of: conversation.state) { newState in
            if case .error(let message) = newState, message.hasPrefix("Bağlantı yok:") {
                serverAlertMessage = message
            }
        }
        .alert("Sunucu bağlantısı yok", isPresented: Binding(
            get: { serverAlertMessage != nil },
            set: { if !$0 { serverAlertMessage = nil } }
        )) {
            Button("Ayarlar") {
                serverAlertMessage = nil
                showSettings = true
            }
            Button("Tamam", role: .cancel) {
                serverAlertMessage = nil
            }
        } message: {
            Text(serverAlertMessage ?? "")
        }
    }

    /// İndirme banner metni: indirme sürerken yüzde, %100'de "hazırlanıyor".
    private var modelBannerText: String {
        let pct = Int((conversation.modelProgress * 100).rounded())
        if pct >= 100 {
            return "Gelişmiş ses modeli hazırlanıyor…\nBu sürede temel tanıma kullanılıyor."
        }
        return "Gelişmiş ses modeli iniyor… %\(pct)\nBu sürede temel tanıma kullanılıyor."
    }

    private var backgroundGradient: some View {
        LinearGradient(
            colors: [
                Color(red: 0.04, green: 0.05, blue: 0.10),
                Color(red: 0.10, green: 0.06, blue: 0.18),
                Color(red: 0.02, green: 0.04, blue: 0.08)
            ],
            startPoint: .top,
            endPoint: .bottom
        )
    }

    private var topBar: some View {
        HStack(spacing: 10) {
            Text("Mate.")
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundStyle(.white.opacity(0.9))
            Spacer()
            RoutePickerView()
                .frame(width: 28, height: 28)
                .padding(8)
                .background(.ultraThinMaterial, in: Circle())
            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.title2)
                    .foregroundStyle(.white.opacity(0.7))
                    .padding(10)
                    .background(.ultraThinMaterial, in: Circle())
            }
        }
        .padding(.horizontal, 20)
    }

    @ViewBuilder
    private var centerVisual: some View {
        switch conversation.state {
        case .listening:
            BarsView(level: conversation.inputLevel)
                .transition(.opacity)
        case .speaking:
            OrbView(amplitude: conversation.outputAmplitude, hue: 0.78, pulsing: true)
                .transition(.opacity)
        case .transcribing, .synthesizing:
            OrbView(amplitude: 0.15, hue: 0.55, pulsing: true)
                .transition(.opacity)
        case .waitingForWake:
            OrbView(amplitude: 0, hue: 0.42, pulsing: true)
                .opacity(0.55)
                .transition(.opacity)
        case .idle, .waitingPermission, .error:
            OrbView(amplitude: 0, hue: 0.62, pulsing: conversation.state != .idle)
                .opacity(conversation.state == .idle ? 0.4 : 0.85)
                .transition(.opacity)
        }
    }

    private var statusText: some View {
        // Ana satır (state.label) + ince, SABİT yükseklikli per-state alt başlık.
        // Ham diagnosticStatus burada GÖSTERİLMEZ (yalnız log/print için set ediliyor).
        VStack(spacing: 4) {
            Text(conversation.state.label)
                .font(.system(size: 16, weight: .medium, design: .rounded))
                .foregroundStyle(.white.opacity(0.75))
            Text(stateSubtitle)
                .font(.system(size: 13, weight: .regular, design: .rounded))
                .foregroundStyle(.white.opacity(0.45))
                .multilineTextAlignment(.center)
                .lineLimit(1)
                .frame(height: 18)   // sabit → alt başlık boşken bile yükseklik değişmez
        }
        .animation(.easeInOut, value: conversation.state)
    }

    /// State'e uygun temiz alt başlık. waitingForWake'te wake kelime ipucu üretir.
    private var stateSubtitle: String {
        if conversation.state == .waitingForWake {
            return settings.wakeWord.isEmpty ? "Wake kelimesini söyle" : "\"\(settings.wakeWord)\" de"
        }
        return conversation.state.subtitle
    }

    /// Sohbet akışı: user/assistant satırları alternatif, en yeni ALTTA, eskiler
    /// yukarı kayar. Sabit yükseklikli alan; yeni satırda slide+opacity animasyonu.
    private var transcriptSlot: some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: 6) {
                    ForEach(conversation.messages) { message in
                        chatRow(message)
                            .id(message.id)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
                .padding(.horizontal, 20)
                .frame(maxWidth: .infinity, alignment: .bottom)
                .frame(maxHeight: .infinity, alignment: .bottom)
            }
            .frame(maxWidth: .infinity)
            .animation(.easeOut(duration: 0.25), value: conversation.messages.count)
            .onChange(of: conversation.messages.count) { _ in
                if let last = conversation.messages.last {
                    withAnimation(.easeOut(duration: 0.25)) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func chatRow(_ message: ChatMessage) -> some View {
        let isUser = message.role == .user
        HStack {
            if isUser { Spacer(minLength: 40) }
            Text(message.text)
                .font(.system(size: 14, weight: .regular, design: .rounded))
                .foregroundStyle(isUser ? Color.white.opacity(0.92) : Color(hue: 0.62, saturation: 0.35, brightness: 1.0))
                .multilineTextAlignment(isUser ? .trailing : .leading)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: 14)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.white.opacity(isUser ? 0.10 : 0.04), lineWidth: 1)
                )
            if !isUser { Spacer(minLength: 40) }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }

    private var controlBar: some View {
        HStack(spacing: 20) {
            Button {
                conversation.toggle()
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: conversation.isRunning ? "pause.fill" : "play.fill")
                    Text(conversation.isRunning ? "Duraklat" : "Başlat")
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 22)
                .padding(.vertical, 14)
                .background(.ultraThinMaterial, in: Capsule())
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(SettingsStore())
        .environmentObject(ConversationManager())
}
