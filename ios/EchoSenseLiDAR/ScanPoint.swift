import Foundation

/// One LiDAR return in the EchoSense wire frame: X forward, Y left, Z up, meters.
/// `confidence` is ARKit's depth confidence: 0 low, 1 medium, 2 high.
struct ScanPoint {
    var x: Float
    var y: Float
    var z: Float
    var confidence: UInt8
}

enum ReferenceFrame: String {
    /// Relative to the phone for this frame, leveled with gravity. Needs no tracking.
    case sensor
    /// Accumulated in the ARKit session frame. Needs working camera tracking.
    case world
}

enum WireFormat {
    /// Builds the `lidar_frame` 0.1 JSON message the bridge accepts on /ingest.
    /// Hand-built because JSONEncoder is slow for thousands of small arrays.
    static func message(points: [ScanPoint], timestamp: TimeInterval,
                        tracking: String, reference: ReferenceFrame) -> String {
        var text = String()
        text.reserveCapacity(points.count * 24 + 200)
        text += "{\"type\":\"lidar_frame\",\"version\":\"0.1\",\"timestamp\":"
        text += centimeters(timestamp)
        text += ",\"sensor_id\":\"iphone-lidar\",\"tracking\":\""
        text += tracking
        text += "\",\"reference\":\""
        text += reference.rawValue
        text += "\",\"points\":["
        var first = true
        for point in points {
            if !first { text += "," }
            first = false
            text += "["
            text += centimeters(Double(point.x))
            text += ","
            text += centimeters(Double(point.y))
            text += ","
            text += centimeters(Double(point.z))
            text += ","
            text += String(point.confidence)
            text += "]"
        }
        text += "]}"
        return text
    }

    /// Fixed two-decimal text, e.g. -1.07. LiDAR depth is no better than a centimeter.
    static func centimeters(_ value: Double) -> String {
        guard value.isFinite else { return "0" }
        let scaled = Int((value * 100).rounded())
        let magnitude = abs(scaled)
        let fraction = magnitude % 100
        return (scaled < 0 ? "-" : "") + String(magnitude / 100) + (fraction < 10 ? ".0" : ".") + String(fraction)
    }
}
