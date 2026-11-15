import ARKit
import AVFoundation
import SwiftUI

/// Runs the ARKit session, turns LiDAR depth into points, and feeds the screen,
/// the proximity pulses and the laptop bridge.
final class LiDARScanner: NSObject, ObservableObject, ARSessionDelegate {
    enum Mode: String, CaseIterable, Identifiable {
        /// What the phone sees right now, relative to the phone. Works in the dark.
        case live = "Live"
        /// Points accumulated into a room map. Needs camera tracking, so needs some light.
        case map = "Room map"
        var id: String { rawValue }
    }

    @Published private(set) var depthImage: UIImage?
    @Published private(set) var nearest: Float?
    @Published private(set) var trackingText = "Starting"
    @Published private(set) var trackingNormal = false
    @Published private(set) var pointCount = 0
    @Published private(set) var problem: String?
    @Published var mode: Mode = .live {
        didSet { let next = mode; queue.async { self.activeMode = next } }
    }
    @Published var includeLowConfidence = false {
        didSet { let floor: UInt8 = includeLowConfidence ? 0 : 1; queue.async { self.liveConfidence = floor } }
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

    // Everything below is touched only on `queue`.
    private let map = VoxelMap()
    private var activeMode: Mode = .live
    private var liveConfidence: UInt8 = 1
    private var lastProcessed: TimeInterval = 0
    private var lastSent: TimeInterval = 0
    private var trackingKey = "not_available"
    private var trackingIsNormal = false

    func start() {
        guard ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) else {
            problem = "This device has no LiDAR scanner. Use an iPhone 12 Pro or later Pro model."
            return
        }
        let configuration = ARWorldTrackingConfiguration()
        configuration.worldAlignment = .gravity
        configuration.frameSemantics = .sceneDepth
        session.delegate = self
        session.delegateQueue = queue
        session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        problem = nil
    }

    func resetMap() {
        queue.async { self.map.reset() }
    }

    // MARK: ARSessionDelegate (called on `queue`)

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // About 10 frames a second is plenty and keeps the phone cool.
        guard frame.timestamp - lastProcessed >= 0.1, let depth = frame.sceneDepth else { return }
        lastProcessed = frame.timestamp

        let image = DepthProjection.image(depth: depth)
        let closest = DepthProjection.nearestObstacle(depth: depth)
        var shown = 0

        switch activeMode {
        case .live:
            // Every 3rd pixel of the 256 x 192 map: about 5,500 points.
            let points = DepthProjection.points(depth: depth, camera: frame.camera, step: 3,
                                                minConfidence: liveConfidence, reference: .sensor)
            shown = points.count
            if frame.timestamp - lastSent >= 0.12, bridge.readyForFrame {
                lastSent = frame.timestamp
                bridge.send(WireFormat.message(points: points, timestamp: frame.timestamp,
                                               tracking: trackingKey, reference: .sensor))
            }
        case .map:
            // Without tracking the session frame drifts, which would smear the map.
            if trackingIsNormal {
                map.insert(DepthProjection.points(depth: depth, camera: frame.camera, step: 4,
                                                  minConfidence: 2, reference: .world))
            }
            shown = map.count
            if frame.timestamp - lastSent >= 0.5, bridge.readyForFrame {
                lastSent = frame.timestamp
                bridge.send(WireFormat.message(points: map.sample(limit: 15_000), timestamp: frame.timestamp,
                                               tracking: trackingKey, reference: .world))
            }
        }

        DispatchQueue.main.async {
            self.depthImage = image
            self.nearest = closest
            self.pointCount = shown
            self.feedback.update(nearest: closest)
        }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let text: String
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
            case .insufficientFeatures: text = "Too dark to track"
            case .relocalizing: text = "Relocalizing"
            @unknown default: text = "Limited tracking"
            }
        }
        trackingIsNormal = trackingKey == "normal"
        let normal = trackingIsNormal
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
        // The session frame is not trustworthy after an interruption.
        map.reset()
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
