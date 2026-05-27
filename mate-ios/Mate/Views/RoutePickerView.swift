import SwiftUI
import AVKit

/// iOS'un native audio route picker'ı (AirPlay/BT/wired/speaker).
/// Tek tap ile Control Center'daki gibi cihaz seçim listesi açılır.
struct RoutePickerView: UIViewRepresentable {
    var tintColor: UIColor = UIColor(white: 1.0, alpha: 0.75)
    var activeTintColor: UIColor = UIColor(red: 0.55, green: 0.75, blue: 1.0, alpha: 1.0)

    func makeUIView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.tintColor = tintColor
        view.activeTintColor = activeTintColor
        view.prioritizesVideoDevices = false
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {
        uiView.tintColor = tintColor
        uiView.activeTintColor = activeTintColor
    }
}
