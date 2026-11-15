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
 *  0. Stray points are set aside first. A point stays UNCLASSIFIED unless its
 *     own and neighbouring 10 cm cells hold enough evidence: `minSupport`
 *     points, or, when per-point hit counts are supplied, `minSupportHits`
 *     frame hits in total. A real surface is seen again and again; a stray
 *     return is not.
 *     Depth sensors produce isolated "flying pixels" at edges and on shiny
 *     surfaces, and a single one below the floor would otherwise move it.
 *  1. Floor height = the lowest 5 cm height layer that holds a real share of
 *     the points, refined to the local peak.
 *  2. Ceiling height = the highest such layer, accepted only if it is at least
 *     `minCeiling` above the floor and stands out against the layers below it
 *     (a ceiling is a horizontal sheet; the top of a wall is not).
 *  3. A 10 cm plan-view column is WALL when its points reach `wallHeight`
 *     above the floor and fill at least `wallFill` of that span. Tall cabinets
 *     and doors pass this test too: WALL means "tall vertical structure".
 *  4. Points within `floorBand` of the floor are FLOOR and within
 *     `ceilingBand` of the ceiling are CEILING. Points beyond either are
 *     UNCLASSIFIED. Of the rest, points in a WALL column are WALL and
 *     everything else is OBJECT.
 *  5. OBJECT columns that touch (8-neighbour) form one object. Groups that are
 *     small or thinly populated are left as loose OBJECT points and not
 *     listed. An object's height is the 95th percentile of its points.
 *
 * It does not recognise what an object is. It reports size and height only.
 *
 * `layer` (height step) and `column` (plan step) default to 5 and 10 cm, which
 * suits points about 5 cm apart. For a thinned map pass larger steps, or
 * walls look half empty and stop counting as walls.
 */
export const UNCLASSIFIED = 0, FLOOR = 1, WALL = 2, CEILING = 3, OBJECT = 4;
export const classNames = ['Unclassified', 'Floor', 'Wall', 'Ceiling', 'Object'];
/** RGB 0..1 per class, chosen to stay distinct on the viewer's dark background. */
export const classColors = [[0.45, 0.5, 0.55], [0.16, 0.5, 0.56], [0.93, 0.95, 0.97], [0.42, 0.4, 0.75], [1.0, 0.62, 0.2]];

const key = (a, b) => (a + 32768) * 65536 + (b + 32768);
const unkey = k => [Math.floor(k / 65536) - 32768, k % 65536 - 32768];

function peakNear(histogram, from, to) {
  let best = from;
  for (let i = Math.max(0, from); i <= Math.min(histogram.length - 1, to); i++) if (histogram[i] > histogram[best]) best = i;
  return best;
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[sorted.length >> 1];
}

/** True for points with enough retained neighbours to be a surface and not a stray return. */
function supported(points, n, hits, threshold) {
  const size = 0.1, cells = new Map(), index = new Float64Array(n), ok = new Uint8Array(n);
  const pack = (a, b, c) => ((a + 4096) * 8192 + (b + 4096)) * 8192 + (c + 4096);
  for (let i = 0; i < n; i++) {
    const k = pack(Math.floor(points[i * 3] / size), Math.floor(points[i * 3 + 1] / size), Math.floor(points[i * 3 + 2] / size));
    index[i] = k;
    cells.set(k, (cells.get(k) ?? 0) + (hits ? hits[i] : 1));
  }
  const verdict = new Map();
  for (let i = 0; i < n; i++) {
    const k = index[i];
    let good = verdict.get(k);
    if (good === undefined) {
      let total = 0;
      for (let dx = -1; dx <= 1 && total < threshold; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
        total += cells.get(k + (dx * 8192 + dy) * 8192 + dz) ?? 0;
      }
      verdict.set(k, good = total >= threshold);
    }
    ok[i] = good ? 1 : 0;
  }
  return ok;
}

export function classifyRoom(points, { column = 0.1, layer = 0.05, floorBand = 0.1, ceilingBand = 0.12, wallHeight = 1.2,
  wallFill = 0.4, minCeiling = 1.9, minObjectCells = 6, minObjectPoints = 15, objectClearance = 0.12,
  minObjectDensity = 2.5, minSupport = 6, minSupportHits = 14, hits = null } = {}) {
  const n = points.length / 3;
  const labels = new Uint8Array(n);
  const empty = { labels, floorY: null, ceilingY: null, wallCells: [], floorCells: [], objects: [],
    counts: [n, 0, 0, 0, 0], column, roomHeight: null, floorArea: 0 };
  if (n < 50) return empty;

  const counted = hits?.length === n ? hits : null;
  const solid = supported(points, n, counted, counted ? minSupportHits : minSupport);
  let low = Infinity, high = -Infinity, kept = 0;
  for (let i = 0; i < n; i++) if (solid[i]) {
    low = Math.min(low, points[i * 3 + 1]);
    high = Math.max(high, points[i * 3 + 1]);
    kept++;
  }
  if (kept < 50) return empty;
  const layers = Math.max(1, Math.ceil((high - low) / layer) + 1);
  const histogram = new Uint32Array(layers);
  for (let i = 0; i < n; i++) if (solid[i]) histogram[Math.floor((points[i * 3 + 1] - low) / layer)]++;
  // "A real share": well above what a few leftover strays could add up to.
  const share = Math.max(20, kept * 0.004);
  let floorLayer = 0;
  while (floorLayer < layers - 1 && histogram[floorLayer] < share) floorLayer++;
  floorLayer = peakNear(histogram, floorLayer, floorLayer + 3);
  const floorY = low + (floorLayer + 0.5) * layer;
  let ceilingLayer = layers - 1;
  while (ceilingLayer > 0 && histogram[ceilingLayer] < share) ceilingLayer--;
  ceilingLayer = peakNear(histogram, ceilingLayer - 3, ceilingLayer);
  const ceilingGuess = low + (ceilingLayer + 0.5) * layer;
  // Compare with the layers 0.3 to 1.0 m below: wall-only layers all look alike.
  const below = median(Array.from(histogram.subarray(Math.max(0, ceilingLayer - 20), Math.max(0, ceilingLayer - 6))));
  const ceilingY = ceilingGuess - floorY >= minCeiling && histogram[ceilingLayer] >= 2 * below ? ceilingGuess : null;

  // Column statistics above the floor band and below the ceiling band.
  const top = ceilingY === null ? Infinity : ceilingY - ceilingBand;
  const columns = new Map();
  for (let i = 0; i < n; i++) {
    const y = points[i * 3 + 1];
    if (!solid[i] || y <= floorY + floorBand || y >= top) continue;
    const k = key(Math.floor(points[i * 3] / column), Math.floor(points[i * 3 + 2] / column));
    let c = columns.get(k);
    if (!c) columns.set(k, c = { min: Infinity, max: -Infinity, layers: new Set() });
    c.min = Math.min(c.min, y);
    c.max = Math.max(c.max, y);
    c.layers.add(Math.floor((y - floorY) / layer));
  }
  const wall = new Set();
  for (const [k, c] of columns) {
    const span = c.max - Math.min(c.min, floorY + floorBand);
    if (c.max - floorY >= wallHeight && c.layers.size * layer >= span * wallFill) wall.add(k);
  }
  // Sensor noise spreads a wall over neighbouring columns that are tall but sparse.
  // Adopt them (two passes, so up to 20 cm) or they show up as thin tall "objects".
  for (let pass = 0; pass < 2; pass++) {
    const adopted = [];
    for (const [k, c] of columns) {
      if (wall.has(k) || c.max - floorY < wallHeight * 0.6) continue;
      const [cx, cz] = unkey(k);
      if ([[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dz]) => wall.has(key(cx + dx, cz + dz)))) adopted.push(k);
    }
    for (const k of adopted) wall.add(k);
  }

  const counts = [0, 0, 0, 0, 0];
  const floorSet = new Set(), objectColumns = new Map();
  for (let i = 0; i < n; i++) {
    const x = points[i * 3], y = points[i * 3 + 1], z = points[i * 3 + 2];
    const k = key(Math.floor(x / column), Math.floor(z / column));
    let label;
    // Bands first: the bottom and top few centimeters of a wall are labelled
    // floor and ceiling. Letting wall columns win instead costs about 10% of the floor.
    if (!solid[i] || y < floorY - floorBand || ceilingY !== null && y > ceilingY + ceilingBand) label = UNCLASSIFIED;
    else if (ceilingY !== null && y >= top) label = CEILING;
    else if (y <= floorY + floorBand) label = FLOOR;
    else if (wall.has(k)) label = WALL;
    else label = OBJECT;
    labels[i] = label;
    counts[label]++;
    if (label === FLOOR) floorSet.add(k);
    else if (label === OBJECT && y >= floorY + objectClearance) {
      let o = objectColumns.get(k);
      if (!o) objectColumns.set(k, o = { heights: [] });
      o.heights.push(y - floorY);
    }
  }

  // Connected components over object columns.
  const objects = [], seen = new Set();
  for (const start of objectColumns.keys()) {
    if (seen.has(start)) continue;
    const stack = [start], cells = [];
    seen.add(start);
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
    const heights = [];
    while (stack.length) {
      const k = stack.pop(), [cx, cz] = unkey(k), o = objectColumns.get(k);
      cells.push([cx, cz]);
      x0 = Math.min(x0, cx); x1 = Math.max(x1, cx); z0 = Math.min(z0, cz); z1 = Math.max(z1, cz);
      heights.push(...o.heights);
      for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) {
        const next = key(cx + dx, cz + dz);
        if (objectColumns.has(next) && !seen.has(next)) { seen.add(next); stack.push(next); }
      }
    }
    // Sparse groups are leftover strays, not furniture.
    if (cells.length < minObjectCells || heights.length < minObjectPoints ||
        heights.length < cells.length * minObjectDensity) continue;
    // 95th percentile, so one high stray point does not set the object's height.
    heights.sort((a, b) => a - b);
    const height = heights[Math.floor((heights.length - 1) * 0.95)];
    objects.push({ cells, height, points: heights.length, width: (x1 - x0 + 1) * column, depth: (z1 - z0 + 1) * column,
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
