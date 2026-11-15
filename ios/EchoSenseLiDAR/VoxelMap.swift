import Foundation

/// Room map built by keeping one point per occupied cell of a 3D grid.
/// Used only from the scanner's queue.
final class VoxelMap {
    private struct Key: Hashable {
        let x: Int32
        let y: Int32
        let z: Int32
    }

    /// 6 cm cells: a furnished room fits in well under the cell cap.
    private let cell: Float = 0.06
    private let maxCells = 250_000
    private var occupied = Set<Key>()
    private var points: [ScanPoint] = []

    var count: Int { points.count }

    func insert(_ incoming: [ScanPoint]) {
        for point in incoming where points.count < maxCells {
            let key = Key(x: Int32((point.x / cell).rounded(.down)),
                          y: Int32((point.y / cell).rounded(.down)),
                          z: Int32((point.z / cell).rounded(.down)))
            if occupied.insert(key).inserted { points.append(point) }
        }
    }

    /// At most `limit` points spread evenly over the map in insertion order,
    /// so the picture stays steady between sends.
    func sample(limit: Int) -> [ScanPoint] {
        guard points.count > limit else { return points }
        var result: [ScanPoint] = []
        result.reserveCapacity(limit)
        let step = Double(points.count) / Double(limit)
        for i in 0..<limit { result.append(points[Int(Double(i) * step)]) }
        return result
    }

    func reset() {
        occupied.removeAll(keepingCapacity: true)
        points.removeAll(keepingCapacity: true)
    }
}
