import UIKit
import CoreHaptics

final class Haptics {
    static let shared = Haptics()

    private let impact = UIImpactFeedbackGenerator(style: .rigid)
    private var engine: CHHapticEngine?
    private var player: CHHapticAdvancedPatternPlayer?

    private init() {
        impact.prepare()
        guard CHHapticEngine.capabilitiesForHardware().supportsHaptics else { return }
        engine = try? CHHapticEngine()
        engine?.isAutoShutdownEnabled = false
        engine?.resetHandler = { [weak self] in
            self?.player = nil
            try? self?.engine?.start()
        }
        engine?.stoppedHandler = { [weak self] _ in self?.player = nil }
        try? engine?.start()
    }

    func tap() {
        impact.impactOccurred(intensity: 0.7)
    }

    /// Map controller rumble (0...255 per motor) to a continuous haptic.
    func rumble(large: UInt8, small: UInt8) {
        guard let engine else { return }
        let intensity = Float(max(large, small)) / 255
        if intensity < 0.02 {
            try? player?.stop(atTime: CHHapticTimeImmediate)
            player = nil
            return
        }
        if player == nil {
            let event = CHHapticEvent(
                eventType: .hapticContinuous,
                parameters: [
                    CHHapticEventParameter(parameterID: .hapticIntensity, value: 1),
                    CHHapticEventParameter(parameterID: .hapticSharpness, value: small > large ? 0.7 : 0.25)
                ],
                relativeTime: 0, duration: 30)
            if let pattern = try? CHHapticPattern(events: [event], parameters: []) {
                try? engine.start()
                player = try? engine.makeAdvancedPlayer(with: pattern)
                player?.loopEnabled = true
                try? player?.start(atTime: CHHapticTimeImmediate)
            }
        }
        let p = CHHapticDynamicParameter(parameterID: .hapticIntensityControl, value: intensity, relativeTime: 0)
        try? player?.sendParameters([p], atTime: CHHapticTimeImmediate)
    }
}
