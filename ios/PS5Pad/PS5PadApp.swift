import SwiftUI

@main
struct PS5PadApp: App {
    @StateObject private var manager = ConnectionManager()

    var body: some Scene {
        WindowGroup {
            ControllerView()
                .environmentObject(manager)
                .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        }
    }
}
