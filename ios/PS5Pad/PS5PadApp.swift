import SwiftUI

@main
struct PS5PadApp: App {
    @StateObject private var manager = ConnectionManager()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ControllerView()
                .environmentObject(manager)
                .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
                .onChange(of: scenePhase) { phase in
                    if phase == .active {
                        manager.refreshIfNeeded()
                    }
                }
        }
    }
}
