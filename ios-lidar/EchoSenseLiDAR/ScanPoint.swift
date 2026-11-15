import Foundation
import simd

/// One LiDAR return in ARKit world coordinates (meters, +Y up), exactly as ARKit reports it.
/// `confidence` is ARKit's depth confidence: 0 low, 1 medium, 2 high.
struct ScanPoint {
    var position: simd_float3
    var confidence: UInt8
}

/// Builds `lidar_frame` schema version 1 messages.
/// The field list is fixed by websocket-bridge/LIDAR_PROTOCOL.md. Do not add or rename fields here
/// without changing that document first: the bridge rejects anything else.
enum WireFormat {
    static func message(points: [ScanPoint], cameraToWorld: simd_float4x4, sessionID: String,
                        deviceID: String, sequence: Int, timestamp: TimeInterval, tracking: String) -> String {
        var text = String()
        text.reserveCapacity(points.count * 30 + 500)
        text += "{\"type\":\"lidar_frame\",\"schema_version\":1,\"session_id\":\""
        text += sessionID
        text += "\",\"device_id\":\""
        text += deviceID
        text += "\",\"sequence\":"
        text += String(sequence)
        text += ",\"timestamp\":"
        text += fixed(timestamp, thousandths: true)
        text += ",\"source\":\"arkit_scene_depth\",\"coordinate_frame\":\"arkit_world\",\"units\":\"meters\",\"tracking\":\""
        text += tracking
        text += "\",\"camera_to_world\":["
        // Column-major: four columns of four, translation in elements 12 to 14.
        let columns = [cameraToWorld.columns.0, cameraToWorld.columns.1, cameraToWorld.columns.2, cameraToWorld.columns.3]
        var first = true
        for column in columns {
            for value in [column.x, column.y, column.z, column.w] {
                if !first { text += "," }
                first = false
                text += fixed(Double(value), thousandths: false)
            }
        }
        text += "],\"points\":["
        first = true
        for point in points {
            if !first { text += "," }
            first = false
            text += "["
            text += fixed(Double(point.position.x), thousandths: true)
            text += ","
            text += fixed(Double(point.position.y), thousandths: true)
            text += ","
            text += fixed(Double(point.position.z), thousandths: true)
            text += "]"
        }
        text += "],\"confidences\":["
        first = true
        for point in points {
            if !first { text += "," }
            first = false
            text += String(point.confidence)
        }
        text += "]}"
        return text
    }

    /// Fixed-point decimal text: 3 places (millimeters) or 5 places for rotation terms.
    static func fixed(_ value: Double, thousandths: Bool) -> String {
        guard value.isFinite else { return "0" }
        let scale = thousandths ? 1_000 : 100_000
        let width = thousandths ? 3 : 5
        let scaled = Int((value * Double(scale)).rounded())
        let magnitude = abs(scaled)
        let fraction = String(magnitude % scale)
        let padding = String(repeating: "0", count: width - fraction.count)
        return (scaled < 0 ? "-" : "") + String(magnitude / scale) + "." + padding + fraction
    }
}
