/**
 * Draws the classified room as a labelled floor plan. Everything a reader needs
 * (legend, scale, caveats) is drawn on the canvas, so a saved PNG stands alone.
 */
import { classColors, FLOOR, WALL, OBJECT } from './room-classifier.js';

const css = ([r, g, b]) => `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
const objectTints = ['#ff9f33', '#f2c14e', '#ef6f6c', '#c58af9', '#7bd88f', '#5cc8ff'];

/** `path` is the scanner trajectory as [x, y, z]; `simulated` adds a visible label. */
export function drawRoomPlan(canvas, analysis, { path = [], simulated = false, title = 'ECHO room analysis' } = {}) {
  const ctx = canvas.getContext('2d'), { width, height } = canvas;
  const header = 54, footer = 64, margin = 28;
  ctx.fillStyle = '#080d13';
  ctx.fillRect(0, 0, width, height);
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#e8f1f5';
  ctx.font = '600 20px system-ui, sans-serif';
  ctx.fillText(title, margin, 26);
  ctx.font = '13px system-ui, sans-serif';
  ctx.fillStyle = '#8fa6b5';
  const { column, wallCells, floorCells, objects } = analysis;
  const summary = [
    `Floor seen ${analysis.floorArea.toFixed(1)} m²`,
    analysis.roomHeight === null ? 'Ceiling not seen' : `Ceiling ${analysis.roomHeight.toFixed(2)} m`,
    `${objects.length} object${objects.length === 1 ? '' : 's'}`,
  ].join('   ·   ');
  ctx.fillText(summary, margin, 46);
  if (simulated) {
    ctx.fillStyle = '#f2c14e';
    ctx.font = '600 13px system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText('SIMULATED DATA', width - margin, 26);
    ctx.textAlign = 'left';
  }

  const all = [...wallCells, ...floorCells, ...objects.flatMap(o => o.cells)];
  if (!all.length) {
    ctx.fillStyle = '#8fa6b5';
    ctx.fillText('Not enough points to analyse yet. Keep scanning.', margin, header + 40);
    return;
  }
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const [x, z] of all) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z); }
  const size = Math.min((width - margin * 2) / (x1 - x0 + 1), (height - header - footer - margin) / (z1 - z0 + 1));
  const left = (width - (x1 - x0 + 1) * size) / 2, top = header + (height - header - footer - (z1 - z0 + 1) * size) / 2;
  const cell = (x, z, grow = 0) => ctx.fillRect(left + (x - x0) * size - grow, top + (z - z0) * size - grow,
    Math.ceil(size) + grow * 2, Math.ceil(size) + grow * 2);
  const meters = (mx, mz) => [left + (mx / column - x0) * size, top + (mz / column - z0) * size];

  ctx.fillStyle = '#17323c';
  for (const [x, z] of floorCells) cell(x, z);
  objects.forEach((object, i) => {
    ctx.fillStyle = objectTints[i % objectTints.length];
    for (const [x, z] of object.cells) cell(x, z);
  });
  ctx.fillStyle = css(classColors[WALL]);
  for (const [x, z] of wallCells) cell(x, z, Math.max(0.5, size * 0.15));

  if (path.length) {
    ctx.strokeStyle = '#ff7a59';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    path.forEach(([x, , z], i) => i ? ctx.lineTo(...meters(x, z)) : ctx.moveTo(...meters(x, z)));
    ctx.stroke();
    ctx.setLineDash([]);
    const [px, py] = meters(path.at(-1)[0], path.at(-1)[2]);
    ctx.fillStyle = '#ff7a59';
    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.fill();
  }

  // Object labels last so nothing covers them.
  ctx.font = '600 13px system-ui, sans-serif';
  ctx.textAlign = 'center';
  for (const object of objects) {
    const [cx, cy] = meters(object.center[0], object.center[1]);
    const text = `${object.name} · ${object.height.toFixed(1)} m`;
    const w = ctx.measureText(text).width + 10;
    ctx.fillStyle = '#080d13e0';
    ctx.fillRect(cx - w / 2, cy - 10, w, 20);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(text, cx, cy);
  }
  ctx.textAlign = 'left';

  // Scale bar: one meter.
  const bar = size / column, by = height - footer + 14;
  ctx.fillStyle = '#e8f1f5';
  ctx.fillRect(width - margin - bar, by, bar, 3);
  ctx.font = '12px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText('1 m', width - margin, by + 14);
  ctx.textAlign = 'left';

  // Legend.
  let lx = margin;
  const swatch = (color, label) => {
    ctx.fillStyle = color;
    ctx.fillRect(lx, by - 4, 12, 12);
    ctx.fillStyle = '#c5d3dc';
    ctx.fillText(label, lx + 17, by + 2);
    lx += ctx.measureText(label).width + 36;
  };
  swatch(css(classColors[WALL]), 'Wall or tall structure');
  swatch('#17323c', 'Floor seen');
  swatch(objectTints[0], 'Object (letter · height)');
  if (path.length) swatch('#ff7a59', 'Scanner path');
  ctx.strokeStyle = '#33485a';
  ctx.strokeRect(lx + 0.5, by - 3.5, 11, 11);
  ctx.fillStyle = '#c5d3dc';
  ctx.fillText('Black: not observed', lx + 17, by + 2);
  ctx.fillStyle = '#8fa6b5';
  ctx.fillText('Geometric classification from LiDAR depth. Objects are sized, not identified. ' +
    'Not observed is not the same as empty or safe.', margin, height - 16);
}

export { FLOOR, WALL, OBJECT };
