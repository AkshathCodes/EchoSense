const colors = {
  floor: "#162738", grid: "#314b61", scan: "#8c9fb0", hit: "#79d1f8",
  invalid: "#edb467", person: "#f6d887", selected: "#e6f7ff",
};

export const initialView = Object.freeze({ yaw: -0.55, tilt: 0.57, zoom: 1 });

function bounds(points) {
  let minX = 0;
  let maxX = 0;
  let minZ = 0;
  let maxZ = 0;
  let minY = 0;
  let maxY = 1.5;
  for (const { x, y, z } of points) {
    minX = Math.min(x, minX);
    maxX = Math.max(x, maxX);
    minY = Math.min(y, minY);
    maxY = Math.max(y, maxY);
    minZ = Math.min(z, minZ);
    maxZ = Math.max(z, maxZ);
  }
  return {
    minX: Math.floor(minX - 0.35), maxX: Math.ceil(maxX + 0.35),
    minZ: Math.floor(minZ - 0.35), maxZ: Math.ceil(maxZ + 0.35),
    minY, maxY,
  };
}

function projection(width, height, box, view) {
  const cos = Math.cos(view.yaw);
  const sin = Math.sin(view.yaw);
  const elevation = Math.sin(view.tilt);
  const vertical = Math.cos(view.tilt);
  function rotate({ x, y, z }) {
    const depth = x * sin + z * cos;
    return { u: x * cos - z * sin, v: y * vertical + depth * elevation,
      depth: depth * vertical - y * elevation };
  }
  const corners = [box.minX, box.maxX].flatMap((x) => [box.minZ, box.maxZ]
    .flatMap((z) => [box.minY, box.maxY].map((y) => rotate({ x, y, z }))));
  const left = Math.min(...corners.map((point) => point.u));
  const right = Math.max(...corners.map((point) => point.u));
  const bottom = Math.min(...corners.map((point) => point.v));
  const top = Math.max(...corners.map((point) => point.v));
  const scale = Math.min((width - 36) / (right - left), (height - 48) / (top - bottom)) * view.zoom;
  return (point) => {
    const { u, v, depth } = rotate(point);
    return { x: width / 2 + (u - (left + right) / 2) * scale,
      y: height / 2 - (v - (bottom + top) / 2) * scale, depth };
  };
}

function line(context, a, b, color, width, dashed) {
  context.strokeStyle = color;
  context.lineWidth = width;
  context.setLineDash(dashed ? [4, 5] : []);
  context.beginPath();
  context.moveTo(a.x, a.y);
  context.lineTo(b.x, b.y);
  context.stroke();
  context.setLineDash([]);
}

function polygon(context, points, fill, stroke) {
  context.beginPath();
  context.moveTo(points[0].x, points[0].y);
  points.slice(1).forEach(({ x, y }) => context.lineTo(x, y));
  context.closePath();
  context.fillStyle = fill;
  context.fill();
  context.strokeStyle = stroke;
  context.lineWidth = 0.8;
  context.stroke();
}

function dot(context, point, radius, color) {
  context.beginPath();
  context.arc(point.x, point.y, radius, 0, Math.PI * 2);
  context.fillStyle = color;
  context.fill();
}

function drawGrid(context, project, box) {
  const floor = (x, z) => project({ x, y: 0, z });
  const { minX, maxX, minZ, maxZ } = box;
  polygon(context, [floor(minX, minZ), floor(maxX, minZ), floor(maxX, maxZ), floor(minX, maxZ)],
    colors.floor, colors.grid);
  for (let x = minX; x <= maxX; x += 1) {
    line(context, floor(x, minZ), floor(x, maxZ), colors.grid, 1, false);
  }
  for (let z = minZ; z <= maxZ; z += 1) {
    line(context, floor(minX, z), floor(maxX, z), colors.grid, 1, false);
  }
}

function drawLabel(context, width, point, content, color) {
  context.font = "600 13px system-ui";
  const textWidth = context.measureText(content).width;
  const x = Math.max(6, Math.min(width - textWidth - 13, point.x - textWidth / 2));
  const y = Math.max(6, point.y - 30);
  context.fillStyle = "#0c121a";
  context.fillRect(x - 5, y, textWidth + 10, 23);
  context.fillStyle = color;
  context.fillText(content, x, y + 16);
}

export function drawRoom(canvas, model, person, view, selectedKey) {
  const { width, height } = canvas.getBoundingClientRect();
  const scale = Math.min(window.devicePixelRatio, 3);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d");
  context.scale(scale, scale);
  const box = bounds([...model.stations.map(({ pose }) => pose), ...model.groups.flatMap((group) =>
    group.hits.map(({ position }) => position)), person]);
  const project = projection(width, height, box, view);
  drawGrid(context, project, box);

  const patches = model.patches.map(({ key, vertices }) => ({ key, points: vertices.map(project) }))
    .sort((a, b) => b.points[0].depth - a.points[0].depth);
  for (const patch of patches) {
    polygon(context, patch.points, patch.key === selectedKey ? "#79d1f846" : "#79d1f824", "#79d1f875");
  }
  for (const { pose, valid } of model.stations) {
    const marker = project({ x: pose.x, y: 0, z: pose.z });
    dot(context, marker, 3, valid ? colors.scan : colors.invalid);
  }
  const hits = model.groups.flatMap((group) => group.hits.map(({ position }) =>
    ({ key: group.key, point: project(position) })));
  hits.sort((a, b) => b.point.depth - a.point.depth);
  for (const hit of hits) {
    dot(context, hit.point, hit.key === selectedKey ? 4.5 : 3, hit.key === selectedKey ? colors.selected : colors.hit);
  }

  const position = project(person);
  const feet = project({ ...person, y: 0 });
  const target = model.groups.find((group) => group.key === selectedKey)?.nearest;
  line(context, feet, position, colors.person, 1.5, true);
  dot(context, feet, 4, colors.person);
  if (target) {
    const end = project(target.position);
    line(context, position, end, colors.person, 1.7, true);
    dot(context, end, 5, colors.selected);
    drawLabel(context, width, end, `${target.distance.toFixed(2)} m`, colors.selected);
  }
  dot(context, position, 7, colors.person);
  dot(context, position, 3, "#162738");
  drawLabel(context, width, position, "You", colors.person);
  return hits;
}
