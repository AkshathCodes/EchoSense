import AudioToolbox
import UIKit

/// Pulses faster as the nearest obstacle gets closer, like a parking sensor.
/// Call `update` from the main thread.
final class ProximityFeedback {
    var hapticsEnabled = true
    var soundEnabled = false

    /// Farther than this, stay silent.
    private let alertRange: Float = 1.5
    private let generator = UIImpactFeedbackGenerator(style: .heavy)
    private var lastPulse = Date.distantPast

    func update(nearest: Float?) {
        guard hapticsEnabled || soundEnabled, let nearest, nearest < alertRange else { return }
        // 0.12 s between pulses when touching distance, 0.9 s at the edge of range.
        let closeness = max(0, min(1, (nearest - 0.3) / (alertRange - 0.3)))
        let interval = 0.12 + 0.78 * Double(closeness)
        guard Date().timeIntervalSince(lastPulse) >= interval else { return }
        lastPulse = Date()
        if hapticsEnabled {
            generator.impactOccurred(intensity: CGFloat(1 - 0.6 * closeness))
            generator.prepare()
        }
        if soundEnabled { AudioServicesPlaySystemSound(1104) }
    }
}
