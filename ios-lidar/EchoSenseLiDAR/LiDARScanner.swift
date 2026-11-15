import ARKit
import AVFoundation
import SwiftUI

/// Runs the ARKit session, turns LiDAR depth into world-space points, and
/// publishes lidar_frame v1 messages to the bridge while scanning.
final class LiDARScanner: NSObject, ObservableObject, ARSessionDelegate {
    @Published private(set) var depthImage: UIImage?
    @Published private(set) var nearest: Float?
    @Published private(set) var trackingText = "Starting"
    @Published private(set) var trackingNormal = false
    @Published private(set) var pointsPerFrame = 0
    @Published private(set) var problem: String?
    @Published private(set) var sessionLabel = ""
    /// True while frames are being sent to the bridge.
    @Published var scanning = false {
        didSet { let on = scanning; queue.async { self.sending = on } }
    }
    @Published var torchOn = false {
        didSet { setTorch(torchOn) }
    }
    @Published var hapticsOn = true {
        didSet { feedback.hapticsEnabled = hapticsOn }
    }
    @Published var soundOn = false {
        didSet { feedback.soundEnabled = soundOn }
    }

    let bridge = BridgeClient()

    private let session = ARSession()
    private let queue = DispatchQueue(label: "echosense.lidar", qos: .userInitiated)
    private let feedback = ProximityFeedback()
    private let deviceID = "iphone-" + String((UIDevice.current.identifierForVendor?.uuidString ?? "unknown").prefix(8))

    // Everything below is touched only on `queue`.
    private var sending = false
    private var sessionID = UUID().uuidString
    private var sequence = 0
    private var lastProcessed: TimeInterval = 0
    private var lastSent: TimeInterval = 0
    private var trackingKey = "not_available"
    private var wasRelocalizing = false

    func start() {
        guard ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else {
            problem = "This device has no LiDAR scanner. Use an iPhone 12 Pro or later Pro model."
            return
        }
        problem = nil
        session.delegate = self
        session.delegateQueue = queue
        runSession()
        queue.async { self.beginSession() }
    }

    /// Resets ARKit's world origin and starts a new mapping session.
    /// The viewer and bridge treat a new session as a separate map.
    func newSession() {
        runSession()
        queue.async { self.beginSession() }
    }

    private func runSession() {
        let configuration = ARWorldTrackingConfiguration()
        configuration.worldAlignment = .gravity
        configuration.frameSemantics = .sceneDepth
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
    }

    /// Call on `queue`. A new id tells every consumer the coordinate origin changed.
    private func beginSession() {
        sessionID = UUID().uuidString
        sequence = 0
        let label = String(sessionID.prefix(8))
        DispatchQueue.main.async { self.sessionLabel = label }
    }

    // MARK: ARSessionDelegate (called on `queue`)

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // The screen updates about 10 times a second. Frames go to the bridge at about 3.
        guard frame.timestamp - lastProcessed >= 0.1, let depth = frame.sceneDepth else { return }
        lastProcessed = frame.timestamp

        let image = DepthProjection.image(depth: depth)
        let closest = DepthProjection.nearestObstacle(depth: depth)
        var sent: Int?

        if sending, frame.timestamp - lastSent >= 0.33, bridge.readyForFrame {
            lastSent = frame.timestamp
            // World coordinates are only valid while tracking is normal. Otherwise send the
            // pose and status with no points, so the viewer can show that tracking was lost.
            // Every 7th pixel of the 256 x 192 map is about 1,000 points.
            let points = trackingKey == "normal"
                ? DepthProjection.worldPoints(depth: depth, camera: frame.camera, step: 7, minConfidence: 1)
                : []
            bridge.send(WireFormat.message(points: points, cameraToWorld: frame.camera.transform,
                                           sessionID: sessionID, deviceID: deviceID, sequence: sequence,
                                           timestamp: frame.timestamp, tracking: trackingKey))
            sequence += 1
            sent = points.count
        }

        let sentCount = sent
        DispatchQueue.main.async {
            self.depthImage = image
            self.nearest = closest
            if let sentCount { self.pointsPerFrame = sentCount }
            self.feedback.update(nearest: closest)
        }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let text: String
        var relocalizing = false
        switch camera.trackingState {
        case .normal:
            text = "Tracking"
            trackingKey = "normal"
        case .notAvailable:
            text = "No tracking"
            trackingKey = "not_available"
        case .limited(let reason):
            trackingKey = "limited"
            switch reason {
            case .initializing: text = "Starting"
            case .excessiveMotion: text = "Moving too fast"
            case .insufficientFeatures: text = "Too dark or featureless"
            case .relocalizing:
                text = "Relocalizing"
                relocalizing = true
            @unknown default: text = "Limited tracking"
            }
        }
        // Coming out of relocalization, ARKit may have re-anchored the world. Start a new
        // session so two origins are never merged into one map.
        if wasRelocalizing && !relocalizing { beginSession() }
        wasRelocalizing = relocalizing
        let normal = trackingKey == "normal"
        DispatchQueue.main.async {
            self.trackingText = text
            self.trackingNormal = normal
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        let text = error.localizedDescription
        DispatchQueue.main.async { self.problem = text }
    }

    func sessionInterruptionEnded(_ session: ARSession) {
        // The world origin is not trustworthy after an interruption (call, app switch).
        beginSession()
    }

    // MARK: Torch

    private func setTorch(_ on: Bool) {
        guard let device = AVCaptureDevice.default(for: .video), device.hasTorch else { return }
        do {
            try device.lockForConfiguration()
            device.torchMode = on ? .on : .off
            device.unlockForConfiguration()
        } catch {
            // The torch is a convenience. Scanning carries on without it.
        }
    }
}
