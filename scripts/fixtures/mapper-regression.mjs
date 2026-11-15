/** Fixed SYNTHETIC scan for comparing current main with the reliability port. */
import { simulate } from '../../test/scan-simulator.js';

export const fixtureConfig = Object.freeze({ seconds: 20, seed: 17, noise: 0.015, outliers: 0.01, lookUp: true, fps: 3 });
let rows;
export function fixedMapperMessage({ delivery = 'live', acquisition = 'simulated', sequence = 7 } = {}) {
  if (!rows) {
    const { memory } = simulate(fixtureConfig), cloud = memory.cloud(), hits = memory.hits();
    rows = [];
    for (let i = 0; i < hits.length; i++) if (hits[i] >= 2) {
      rows.push([-cloud[i * 3 + 2], -cloud[i * 3], cloud[i * 3 + 1], Math.min(50, hits[i])]
        .map(n => +n.toFixed(3)));
    }
  }
  return JSON.stringify({ protocol_version: '0.1', type: 'sonar_frame', sequence, timestamp: 12.5,
    source: delivery, acquisition_source: acquisition, detections: null,
    frame: { format_version: '0.2', points: rows,
      meta: { format_version: '0.2', kind: 'lidar_map', sensor_id: 'synthetic-regression',
        source: acquisition, view: 'map', tilt_deg: 0 } } });
}
