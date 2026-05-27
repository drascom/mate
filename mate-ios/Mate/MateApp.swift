import SwiftUI

@main
struct MateApp: App {
    @StateObject private var settings = SettingsStore()
    @StateObject private var conversation = ConversationManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(conversation)
                .preferredColorScheme(.dark)
                .onAppear {
                    conversation.attach(settings: settings)
                    conversation.start()
                    // WhisperKit modelini açılışta arka planda indir/yükle (prewarm).
                    // Bu sürede UI'da "model hazırlanıyor" göstergesi çıkar.
                    conversation.prewarmModel()
                }
        }
    }
}
