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
                    // Modeli arka planda indir/yükle. İnerken SFSpeech kullanılır (bloklamaz),
                    // hazır olunca otomatik WhisperKit'e geçilir. Banner durumu gösterir.
                    conversation.prewarmModel()
                }
        }
    }
}
