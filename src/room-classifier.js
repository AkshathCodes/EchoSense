/**
 * Geometric room classifier for accumulated LiDAR points.
 *
 * This is a rule-based model, not a trained network. It labels every retained
 * point as FLOOR, WALL, CEILING or OBJECT from room geometry alone, then groups
 * object points into separate items with a footprint and height.
 *
 * Input is flat XYZ in ARKit world meters (+Y up, gravity aligned).
 *
 * Rules, in order:
 *  1. Floor height = the most populated 5 cm height layer in the bottom 40 cm.
 *  2. Ceiling height = the most populated layer in the top 40 cm, accepted only
 *     if it is at least `minCeiling` above the floor and holds enough points to
 *     be a surface. Otherwise the room has no ceiling label.
 *  3. A 10 cm plan-view column is WALL when its points span at least
 *     `wallHeight` above the floor and fill at least half of that span.
 *     Tall cabinets and doors pass this test too: WALL means "tall vertical
 *     structure", which is what it looks like to a depth sensor.
 *  4. Points within `floorBand` of the floor are FLOOR and within
 *     `ceilingBand` of the ceiling are CEILING. Of the rest, points in a WALL
 *     column are WALL and everything else is OBJECT.
 *  5. OBJECT columns that touch (8-neighbour) form one object. Groups smaller
 *     than `minObjectCells` are left as loose OBJECT points and not listed.
 *
 * It does not recognise what an object is. It reports size and height only.
 */
export const UNCLASSIFIED = 0, FLOOR = 1, WALL = 2, CEILING = 3, OBJECT = 4;
export const classNames = ['Unclassified', 'Floor', 'Wall', 'Ceiling', 'Object'];
/** RGB 0..1 per class, chosen to stay distinct on the viewer's dark background. */
export const classColors = [[0.45, 0.5, 0.55], [0.16, 0.5, 0.56], [0.93, 0.95, 0.97], [0.42, 0.4, 0.75], [1.0, 0.62, 0.2]];

const LAYER = 0.05;
const key = (a, b) => (a + 32768) * 65536 + (b + 32768);
const unkey = k => [Math.floor(k / 65536) - 32768, k % 65536 - 32768];

function busiestLayer(histogram, from, to) {
  let best = -1, bestCount = 0;
  for (let i = from; i <= to; i++) if ((histogram[i] ?? 0) > bestCount) { bestCount = histogram[i]; best = i; }
  return [best, bestCount];
}

export function classifyRoom(points, { column = 0.1, floorBand = 0.1, ceilingBand = 0.12, wallHeight = 1.2,
  wallFill = 0.5, minCeiling = 1.9, minObjectCells = 6, objectClearance = 0.12 } = {}) {
  const n = points.length / 3;
  const labels = new Uint8Array(n);
  const empty = { labels, floorY: null, ceilingY: null, wallCells: [], floorCells: [], objects: [],
    counts: [n, 0, 0, 0, 0], column, roomHeight: null, floorArea: 0 };
  if (n < 50) return empty;

  let low = Infinity, high = -Infinity;
  for (let i = 1; i < points.length; i += 3) { low = Math.min(low, points[i]); high = Math.max(high, points[i]); }
  const layers = Math.max(1, Math.ceil((high - low) / LAYER) + 1);
  const histogram = new Uint32Array(layers);
  for (let i = 1; i < points.length; i += 3) histogram[Math.floor((points[i] - low) / LAYER)]++;
  const [floorLayer] = busiestLayer(histogram, 0, Math.min(layers - 1, 8));
  const floorY = low + (floorLayer + 0.5) * LAYER;
  const [ceilingLayer, ceilingCount] = busiestLayer(histogram, Math.max(0, layers - 9), layers - 1);
  const ceilingGuess = low + (ceilingLayer + 0.5) * LAYER;
  // A ceiling is a surface: it should hold a real share of the points, not a few strays.
  const ceilingY = ceilingGuess - floorY >= minCeiling && ceilingCount >= Math.max(30, n * 0.02) ? ceilingGuess : null;

  // Column statistics above the floor band and below the ceiling band.
  const top = ceilingY === null ? Infinity : ceilingY - ceilingBand;
  const columns = new Map();
  for (let i = 0; i < n; i++) {
    const y = points[i * 3 + 1];
    if (y <= floorY + floorBand || y >= top) continue;
    const k = key(Math.floor(points[i * 3] / column), Math.floor(points[i * 3 + 2] / column));
    let c = columns.get(k);
    if (!c) columns.set(k, c = { min: Infinity, max: -Infinity, layers: new Set() });
    c.min = Math.min(c.min, y);
    c.max = Math.max(c.max, y);
    c.layers.add(Math.floor((y - floorY) / LAYER));
  }
  const wall = new Set();
  for (const [k, c] of columns) {
    const span = c.max - Math.min(c.min, floorY + floorBand);
    if (c.max - floorY >= wallHeight && c.layers.size * LAYER >= span * wallFill) wall.add(k);
  }
  // A thin wall can straddle two columns, leaving one of them sparse. Adopt
  // tall-enough neighbours of wall columns so the wall is not half "object".
  for (const [k, c] of columns) {
    if (wall.has(k) || c.max - floorY < wallHeight * 0.6) continue;
    const [cx, cz] = unkey(k);
    for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      if (wall.has(key(cx + dx, cz + dz)) && columns.get(key(cx + dx, cz + dz)).layers.size >= c.layers.size) {
        wall.add(k);
        break;
      }
    }
  }

  const counts = [0, 0, 0, 0, 0];
  const floorSet = new Set(), objectColumns = new Map();
  for (let i = 0; i < n; i++) {
    const x = points[i * 3], y = points[i * 3 + 1], z = points[i * 3 + 2];
    const k = key(Math.floor(x / column), Math.floor(z / column));
    let label;
    // Bands first: the bottom and top few centimeters of a wall are labelled
    // floor and ceiling. Letting wall columns win instead costs about 10% of the floor.
    if (ceilingY !== null && y >= top) label = CEILING;
    else if (y <= floorY + floorBand) label = FLOOR;
    else if (wall.has(k)) label = WALL;
    else label = OBJECT;
    labels[i] = label;
    counts[label]++;
    if (label === FLOOR) floorSet.add(k);
    else if (label === OBJECT && y >= floorY + objectClearance) {
      let o = objectColumns.get(k);
      if (!o) objectColumns.set(k, o = { top: -Infinity, points: 0 });
      o.top = Math.max(o.top, y);
      o.points++;
    }
  }

  // Connected components over object columns.
  const objects = [], seen = new Set();
  for (const start of objectColumns.keys()) {
    if (seen.has(start)) continue;
    const stack = [start], cells = [];
    seen.add(start);
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity, height = 0, pointCount = 0;
    while (stack.length) {
      const k = stack.pop(), [cx, cz] = unkey(k), o = objectColumns.get(k);
      cells.push([cx, cz]);
      x0 = Math.min(x0, cx); x1 = Math.max(x1, cx); z0 = Math.min(z0, cz); z1 = Math.max(z1, cz);
      height = Math.max(height, o.top - floorY);
      pointCount += o.points;
      for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) {
        const next = key(cx + dx, cz + dz);
        if (objectColumns.has(next) && !seen.has(next)) { seen.add(next); stack.push(next); }
      }
    }
    if (cells.length < minObjectCells) continue;
    objects.push({ cells, height, points: pointCount, width: (x1 - x0 + 1) * column, depth: (z1 - z0 + 1) * column,
      center: [(x0 + x1 + 1) / 2 * column, (z0 + z1 + 1) / 2 * column], footprint: cells.length * column * column });
  }
  objects.sort((a, b) => b.footprint - a.footprint);
  objects.forEach((object, i) => { object.name = String.fromCharCode(65 + i % 26) + (i >= 26 ? Math.floor(i / 26) : ''); });

  return { labels, floorY, ceilingY, counts, column, objects,
    wallCells: [...wall].map(unkey), floorCells: [...floorSet].map(unkey),
    roomHeight: ceilingY === null ? null : ceilingY - floorY, floorArea: floorSet.size * column * column };
}

/** Flat RGB per point for the viewer. Points beyond `labels.length` are drawn as unclassified. */
export function colorsFor(labels, count) {
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) colors.set(classColors[i < labels.length ? labels[i] : UNCLASSIFIED], i * 3);
  return colors;
}
