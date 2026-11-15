import SwiftUI

@main
struct EchoSenseApp: App {
    @StateObject private var scanner = LiDARScanner()

    var body: some Scene {
        WindowGroup {
            ContentView(scanner: scanner, bridge: scanner.bridge)
                .preferredColorScheme(.dark)
                .onAppear {
                    UIApplication.shared.isIdleTimerDisabled = true
                    scanner.start()
                }
        }
    }
}
