import { drawRoomPlan } from './room-plan.js';

// Same X/Z extent for the additional plan-view layers.
export function drawLidarSchematic(canvas, analysis, options) {
  const { width, height } = canvas;
  const plan = document.createElement('canvas');
  plan.width = width;
  plan.height = height - 184;
  const objects = analysis.objects.map(object => ({ ...object,
    name: `${object.name} · ${object.width.toFixed(1)}×${object.depth.toFixed(1)} m` }));
  drawRoomPlan(plan, { ...analysis, objects }, options);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(plan, 0, 0);
  const top = plan.height;
  ctx.fillStyle = '#0d1821';
  ctx.fillRect(0, top, width, height - top);
  ctx.font = '600 13px system-ui';
  ctx.fillStyle = '#d5e4ed';
  ctx.fillText(analysis.model + ' · trained on labeled synthetic rooms', 28, top + 22);
  ctx.font = '12px system-ui';
  const names = ['Unclassified', 'Floor', 'Wall', 'Ceiling', 'Object'];
  ctx.fillText(analysis.counts.map((count, i) => `${names[i]} ${count.toLocaleString('en-US')}`).join('   ·   '), 28, top + 43);
  const layers = [analysis.floorCells, analysis.wallCells, analysis.objectCells, analysis.ceilingCells, analysis.uncertainCells];
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const layer of layers) for (const [x, z] of layer) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z);
  }
  const w = width / 3 - 40;
  const size = Math.min(w / (x1 - x0 + 1), 87 / (z1 - z0 + 1));
  for (const [i, label, layer, tint] of [
    [0, 'CEILING RETURNS · plan projection', analysis.ceilingCells, '#a99cf4'],
    [1, 'OBJECT RETURNS · all measured points', analysis.objectCells, '#ff9f33'],
    [2, 'UNCLASSIFIED · observed, uncertain', analysis.uncertainCells, '#b6c6d3'],
  ]) {
    const x = 28 + i * width / 3;
    ctx.fillStyle = '#bacdd8';
    ctx.fillText(label, x, top + 67);
    ctx.fillStyle = '#070d13';
    ctx.fillRect(x, top + 76, w, 87);
    if (!Number.isFinite(x0)) continue;
    for (const [data, color] of [[analysis.wallCells, '#2a4555'], [layer, tint]]) {
      ctx.fillStyle = color;
      for (const [px, pz] of data) ctx.fillRect(x + (px - x0) * size, top + 76 + (pz - z0) * size,
        Math.max(1, size), Math.max(1, size));
    }
  }
  ctx.fillStyle = '#8fa6b5';
  ctx.fillText('Black = no evidence in this layer. Person detection is unavailable.', 28, height - 8);
}
