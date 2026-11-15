import ARKit
import simd

/// Turns an ARKit LiDAR depth map into 3D points and a false-color image.
enum DepthProjection {
    /// Beyond about 5 m the iPhone LiDAR returns little usable depth.
    static let maxRange: Float = 5.0

    /// Unprojects every `step`-th depth pixel into ARKit world coordinates.
    /// The result is only meaningful while camera tracking is normal.
    static func worldPoints(depth: ARDepthData, camera: ARCamera, step: Int, minConfidence: UInt8) -> [ScanPoint] {
        let depthMap = depth.depthMap
        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }
        guard let depthBase = CVPixelBufferGetBaseAddress(depthMap) else { return [] }
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let depthRow = CVPixelBufferGetBytesPerRow(depthMap)

        let confidenceMap = depth.confidenceMap
        if let confidenceMap { CVPixelBufferLockBaseAddress(confidenceMap, .readOnly) }
        defer { if let confidenceMap { CVPixelBufferUnlockBaseAddress(confidenceMap, .readOnly) } }
        let confidenceBase = confidenceMap.flatMap { CVPixelBufferGetBaseAddress($0) }
        let confidenceRow = confidenceMap.map { CVPixelBufferGetBytesPerRow($0) } ?? 0

        // Intrinsics describe the full camera image. Scale them to the depth map.
        let resolution = camera.imageResolution
        let scaleX = Float(width) / Float(resolution.width)
        let scaleY = Float(height) / Float(resolution.height)
        let intrinsics = camera.intrinsics
        let fx = intrinsics[0][0] * scaleX
        let fy = intrinsics[1][1] * scaleY
        let cx = intrinsics[2][0] * scaleX
        let cy = intrinsics[2][1] * scaleY
        let transform = camera.transform

        var result: [ScanPoint] = []
        result.reserveCapacity((width / step + 1) * (height / step + 1))
        var v = 0
        while v < height {
            let depthLine = depthBase.advanced(by: v * depthRow).assumingMemoryBound(to: Float32.self)
            let confidenceLine = confidenceBase?.advanced(by: v * confidenceRow).assumingMemoryBound(to: UInt8.self)
            var u = 0
            while u < width {
                let d = depthLine[u]
                let confidence = confidenceLine?[u] ?? 2
                if d.isFinite && d > 0.1 && d < maxRange && confidence >= minConfidence {
                    // ARKit camera space: +X right, +Y up, -Z into the scene. Image Y runs down.
                    let local = simd_float4((Float(u) - cx) * d / fx, -(Float(v) - cy) * d / fy, -d, 1)
                    result.append(ScanPoint(position: simd_make_float3(transform * local), confidence: confidence))
                }
                u += step
            }
            v += step
        }
        return result
    }

    /// Distance to the closest thing in the middle third of the view, in meters.
    /// A low percentile, not the minimum, so one noisy pixel cannot trigger it.
    static func nearestObstacle(depth: ARDepthData) -> Float? {
        let depthMap = depth.depthMap
        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(depthMap) else { return nil }
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let row = CVPixelBufferGetBytesPerRow(depthMap)
        var samples: [Float] = []
        samples.reserveCapacity(width * height / 36 + 1)
        var v = height / 3
        while v < height * 2 / 3 {
            let line = base.advanced(by: v * row).assumingMemoryBound(to: Float32.self)
            var u = width / 3
            while u < width * 2 / 3 {
                let d = line[u]
                if d.isFinite && d > 0.05 && d < maxRange { samples.append(d) }
                u += 2
            }
            v += 2
        }
        guard samples.count >= 20 else { return nil }
        samples.sort()
        return samples[samples.count / 20]
    }

    /// False-color picture of the depth map: near is red, far is blue, no return is black.
    /// The map is in the sensor's landscape layout, so the image is tagged `.right`
    /// to stand upright on a portrait screen.
    static func image(depth: ARDepthData) -> UIImage? {
        let depthMap = depth.depthMap
        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(depthMap) else { return nil }
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let row = CVPixelBufferGetBytesPerRow(depthMap)
        var pixels = [UInt8](repeating: 255, count: width * height * 4)
        for v in 0..<height {
            let line = base.advanced(by: v * row).assumingMemoryBound(to: Float32.self)
            for u in 0..<width {
                let d = line[u]
                let offset = (v * width + u) * 4
                if d.isFinite && d > 0.05 {
                    let index = min(255, Int(d / maxRange * 255)) * 3
                    pixels[offset] = palette[index]
                    pixels[offset + 1] = palette[index + 1]
                    pixels[offset + 2] = palette[index + 2]
                } else {
                    pixels[offset] = 0
                    pixels[offset + 1] = 0
                    pixels[offset + 2] = 0
                }
            }
        }
        guard let provider = CGDataProvider(data: Data(pixels) as CFData),
              let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                                  bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                                  provider: provider, decode: nil, shouldInterpolate: true,
                                  intent: .defaultIntent) else { return nil }
        return UIImage(cgImage: image, scale: 1, orientation: .right)
    }

    /// 256 RGB entries. Hue runs red to blue with distance and dims toward the far end.
    private static let palette: [UInt8] = {
        var table = [UInt8](repeating: 0, count: 256 * 3)
        for i in 0..<256 {
            let t = Float(i) / 255
            let hue = t * 4            // 0 red, 1 yellow, 2 green, 3 cyan, 4 blue
            let sector = min(3, Int(hue))
            let f = hue - Float(sector)
            let rgb: (Float, Float, Float)
            switch sector {
            case 0: rgb = (1, f, 0)
            case 1: rgb = (1 - f, 1, 0)
            case 2: rgb = (0, 1, f)
            default: rgb = (0, 1 - f, 1)
            }
            let value = 1 - 0.55 * t
            table[i * 3] = UInt8(rgb.0 * value * 255)
            table[i * 3 + 1] = UInt8(rgb.1 * value * 255)
            table[i * 3 + 2] = UInt8(rgb.2 * value * 255)
        }
        return table
    }()
}
