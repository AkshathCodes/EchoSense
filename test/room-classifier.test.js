import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyRoom, colorsFor, classColors, FLOOR, WALL, CEILING, OBJECT } from '../src/room-classifier.js';
import { score } from './scan-simulator.js';

// SYNTHETIC room with known labels: 5 x 4 m, floor at y = -1.3, ceiling at y = 1.2,
// a 1.0 x 0.6 x 0.75 m table and a 0.5 m cube. Points carry up to 1.5 cm of noise.
function syntheticRoom(seed = 3, { ceiling = true } = {}) {
  let s = seed;
  const random = () => (s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const noise = () => (random() - 0.5) * 0.03;
  const points = [], truth = [];
  const add = (x, y, z, label) => { points.push(x + noise(), y + noise(), z + noise()); truth.push(label); };
  const floor = -1.3, top = 1.2;
  for (let x = -2.5; x <= 2.5; x += 0.05) for (let z = -2; z <= 2; z += 0.05) {
    // The floor under furniture is hidden from a real sensor too.
    const underTable = x > 0.5 && x < 1.5 && z > -0.3 && z < 0.3, underBox = x > -1.5 && x < -1 && z > 1 && z < 1.5;
    if (!underTable && !underBox) add(x, floor, z, FLOOR);
    if (ceiling) add(x, top, z, CEILING);
  }
  for (let y = floor + 0.05; y < top; y += 0.05) {
    for (let x = -2.5; x <= 2.5; x += 0.05) { add(x, y, -2, WALL); add(x, y, 2, WALL); }
    for (let z = -2; z <= 2; z += 0.05) { add(-2.5, y, z, WALL); add(2.5, y, z, WALL); }
  }
  for (let x = 0.5; x <= 1.5; x += 0.04) for (let z = -0.3; z <= 0.3; z += 0.04) add(x, floor + 0.75, z, OBJECT);
  for (let y = floor + 0.15; y < floor + 0.75; y += 0.05) for (let x = 0.5; x <= 1.5; x += 0.05) {
    add(x, y, -0.3, OBJECT); add(x, y, 0.3, OBJECT);
  }
  for (let x = -1.5; x <= -1; x += 0.04) for (let z = 1; z <= 1.5; z += 0.04) add(x, floor + 0.5, z, OBJECT);
  for (let y = floor + 0.15; y < floor + 0.5; y += 0.05) for (let x = -1.5; x <= -1; x += 0.05) {
    add(x, y, 1, OBJECT); add(x, y, 1.5, OBJECT);
  }
  return { points: new Float32Array(points), truth };
}

function recall(labels, truth, wanted) {
  let hit = 0, total = 0;
  truth.forEach((t, i) => { if (t === wanted) { total++; if (labels[i] === wanted) hit++; } });
  return hit / total;
}

test('labels a synthetic furnished room with high per-class recall', () => {
  const { points, truth } = syntheticRoom();
  const result = classifyRoom(points);
  const scores = Object.fromEntries([[FLOOR, 'floor'], [WALL, 'wall'], [CEILING, 'ceiling'], [OBJECT, 'object']]
    .map(([label, name]) => [name, +recall(result.labels, truth, label).toFixed(3)]));
  console.log('synthetic recall', scores);
  // Walls lose their bottom 10 cm and top 12 cm to the floor and ceiling bands by design.
  for (const [name, score] of Object.entries(scores)) assert.ok(score > 0.9, `${name} recall ${score}`);
  assert.ok(Math.abs(result.floorY + 1.3) < 0.05);
  assert.ok(Math.abs(result.roomHeight - 2.5) < 0.08);
});

test('finds the two objects with plausible size and height', () => {
  const result = classifyRoom(syntheticRoom().points);
  assert.equal(result.objects.length, 2);
  const [table, box] = result.objects;
  assert.equal(table.name, 'A');                               // largest footprint first
  assert.ok(Math.abs(table.height - 0.75) < 0.08, `table height ${table.height}`);
  assert.ok(Math.abs(table.width - 1.0) < 0.25 && Math.abs(table.depth - 0.6) < 0.25);
  assert.ok(Math.abs(table.center[0] - 1.0) < 0.15 && Math.abs(table.center[1]) < 0.15);
  assert.ok(Math.abs(box.height - 0.5) < 0.08 && Math.abs(box.center[0] + 1.25) < 0.15);
});

test('does not invent a ceiling when none was scanned', () => {
  const result = classifyRoom(syntheticRoom(5, { ceiling: false }).points);
  assert.equal(result.ceilingY, null);
  assert.equal(result.roomHeight, null);
  assert.equal(result.counts[CEILING], 0);
  assert.equal(result.objects.length, 2);
});

test('too few points returns an empty, unclassified result', () => {
  const result = classifyRoom(new Float32Array([0, 0, 0, 1, 1, 1]));
  assert.equal(result.floorY, null);
  assert.deepEqual([...result.labels], [0, 0]);
  assert.equal(result.objects.length, 0);
});

test('colours follow labels and unlabelled tail points are neutral', () => {
  const colors = colorsFor(Uint8Array.of(WALL, OBJECT), 3);
  assert.deepEqual([...colors.slice(0, 3)].map(n => +n.toFixed(2)), classColors[WALL]);
  assert.deepEqual([...colors.slice(6, 9)].map(n => +n.toFixed(2)), classColors[0]);
});

// Simulated scans with known answers. The real furniture is a sofa (2.0 x 0.9 x 0.8 m),
// a table (1.0 x 0.6 x 0.75 m) and a crate (0.5 x 0.5 x 0.5 m).
const scans = {
  'typical 40 s scan with 2% stray returns': {},
  'short 12 s scan': { seconds: 12 },
  'scan that never looks up': { lookUp: false },
  'noisy scan, 3 cm error and 5% stray returns': { noise: 0.03, outliers: 0.05 },
};
for (const [name, options] of Object.entries(scans)) {
  test(`simulated ${name}`, () => {
    const result = score(options);
    console.log(name, JSON.stringify({ accuracy: result.accuracy, recall: result.recall, objects: result.objects }));
    assert.ok(result.accuracy >= 0.88, `accuracy ${result.accuracy}`);
    assert.ok(Math.abs(result.floorY + 1.3) < 0.06, `floor at ${result.floorY}`);
    if (options.lookUp === false) assert.equal(result.height, null);
    else assert.ok(Math.abs(result.height - 2.5) < 0.1, `room height ${result.height}`);
    // The three real pieces of furniture are found near their true positions and heights.
    // Footprints come out up to about 30 cm too large, which shifts centres by up to 0.4 m.
    // A 12 s scan has not reached the crate yet, so it is not expected there.
    const expected = [[0, -1.55, 0.8], [1.5, 0, 0.75], ...(options.seconds === 12 ? [] : [[-1.55, 1.25, 0.5]])];
    for (const [x, z, h] of expected) {
      assert.ok(result.objects.some(o => Math.abs(o.x - x) < 0.4 && Math.abs(o.z - z) < 0.4 && Math.abs(o.height - h) < 0.15),
        `no object near ${x}, ${z} with height ${h}: ${JSON.stringify(result.objects)}`);
    }
    // Partly scanned walls can still show up as extra objects. Keep that bounded.
    assert.ok(result.objects.length <= 6, `${result.objects.length} objects listed`);
  });
}
