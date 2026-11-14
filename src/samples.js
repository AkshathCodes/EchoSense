import { positions, thumbnail } from './archive.js';
import { mockFrame } from './mock.js';

export const MOCK_SPACE = 'echosense-living-room-meters-v1';

function earlyReturn(x, y, z) {
  return !(x > 2.55 && (z > -0.42 || y > 2.2)) && !(z > 1.9 && x < 0.4);
}

export function sampleScans(room, viewer, canvas) {
  const full = positions(room.cloud);
  const partial = new Float32Array(full.length);
  let cursor = 0;
  for (let i = 0; i < full.length; i += 3) {
    if (earlyReturn(...full.subarray(i, i + 3))) {
      partial.set(full.subarray(i, i + 3), cursor);
      cursor += 3;
    }
  }
  const specs = [
    ['demo-01', 'Living room · First pass', '2026-11-14T16:20:00Z', partial.subarray(0, cursor)],
    ['demo-02', 'Living room · Second pass', '2026-11-14T16:24:00Z', full],
  ];
  const scans = specs.map(([id, name, date, points], index) => {
    const history = Array.from({ length: 12 }, (_, i) => {
      const t = i * 1000;
      const end = 3 * Math.floor(points.length / 3 * (0.08 + (i / 11) * 0.92));
      return { ...mockFrame(t + index * 700), t, points: points.subarray(0, end),
        target: i >= 4 && i <= 6 ? null : mockFrame(t + index * 700).target };
    });
    viewer.replaceCloud(points);
    viewer.draw({ mode: 'points', pointSize: 5, pointCap: 100000, time: 0, dimensions: [800, 450] });
    return { id, name, date, points, source: 'mock', space: MOCK_SPACE, history,
      target: history.at(-1).target, thumb: thumbnail(canvas) };
  });
  viewer.replaceCloud();
  return scans;
}
