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

            VStack(spacing: 24) {
                topBar

                Spacer()

                centerVisual
                    .frame(height: 280)

                statusText

                Spacer()

                if !conversation.lastTranscript.isEmpty {
                    transcriptCard
                        .padding(.horizontal, 20)
                }

                controlBar
                    .padding(.bottom, 20)
            }
            .padding(.top, 8)
        }
        .overlay(alignment: .top) {
            if conversation.modelLoading {
                HStack(spacing: 10) {
                    ProgressView().tint(.white)
                    Text("Ses modeli hazırlanıyor, lütfen bekleyin…\nİlk açılışta bir kez indiriliyor.")
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
                .transition(.opacity.combined(with: .scale))
        case .speaking:
            OrbView(amplitude: conversation.outputAmplitude, hue: 0.78, pulsing: true)
                .transition(.opacity.combined(with: .scale))
        case .transcribing, .synthesizing:
            OrbView(amplitude: 0.15, hue: 0.55, pulsing: true)
                .transition(.opacity.combined(with: .scale))
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
        VStack(spacing: 4) {
            Text(conversation.state.label)
                .font(.system(size: 16, weight: .medium, design: .rounded))
                .foregroundStyle(.white.opacity(0.75))
            if conversation.state == .waitingForWake, !settings.wakeWord.isEmpty {
                Text("\"\(settings.wakeWord)\" de")
                    .font(.system(size: 13, weight: .regular, design: .rounded))
                    .foregroundStyle(.white.opacity(0.45))
            }
            if !conversation.diagnosticStatus.isEmpty {
                Text(conversation.diagnosticStatus)
                    .font(.system(size: 12, weight: .regular, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.48))
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .padding(.horizontal, 20)
            }
        }
        .animation(.easeInOut, value: conversation.state)
    }

    private var transcriptCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Sen dedin ki")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.5))
            Text(conversation.lastTranscript)
                .font(.system(size: 15, weight: .regular))
                .foregroundStyle(.white.opacity(0.9))
                .lineLimit(3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
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
