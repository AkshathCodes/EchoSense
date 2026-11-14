import { trialCount } from "./audio.mjs";

function nonnegative(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function parseRangeTrials(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length !== trialCount) {
    throw new RangeError(`Enter ${trialCount} readings, one per line in meters. Use timeout for a missed return.`);
  }
  return lines.map((line, index) => {
    const value = line.trim();
    if (value === "timeout") return { status: "no_echo", range_m: null, echo_ratio: null };
    const range = Number(value);
    if (!/^\d*\.?\d+$/.test(value) || !inRange(range, 0.001, 50)) {
      throw new RangeError(`Reading ${index + 1} must be a distance from 0.001 to 50 m or timeout.`);
    }
    return { status: "ok", range_m: range, echo_ratio: null };
  });
}

export function validateReport(report) {
  if (!report || !["measured", "simulated"].includes(report.source) ||
      !Array.isArray(report.points) || report.points.length === 0) {
    throw new TypeError("This file is not an EchoSense report with at least one scan station.");
  }
  const seen = new Set();
  for (const point of report.points) {
    if (!point || typeof point.scene !== "string" || !point.scene.trim() ||
        !inRange(point.station_m, -30, 30) || !Number.isInteger(point.accepted) ||
        !Number.isInteger(point.total) || point.total < 1 || point.accepted < 0 ||
        point.accepted > point.total ||
        (point.range_m !== null && !inRange(point.range_m, 0, 50)) ||
        ["range_m", "reference_m", "spread_m", "error_m"].some((key) =>
          point[key] !== null && !nonnegative(point[key]))) {
      throw new TypeError("An EchoSense station has missing or invalid values.");
    }
    const pose = stationPose(point);
    if (!inRange(pose.y, 0, 10) || !inRange(pose.z, -30, 30) ||
        !inRange(pose.heading, 0, 360) || !inRange(pose.pitch, -90, 90) ||
        (point.surface !== undefined && typeof point.surface !== "string")) {
      throw new TypeError("A scan station has an invalid position or aiming angle.");
    }
    const key = scanKey(point);
    if (seen.has(key)) throw new TypeError("The report contains a duplicate scan pose and surface.");
    seen.add(key);
  }
  return report;
}

function inRange(value, low, high) {
  return Number.isFinite(value) && value >= low && value <= high;
}

export function stationPose(point) {
  return {
    x: point.station_m,
    y: point.height_m === undefined ? 1 : point.height_m,
    z: point.depth_m === undefined ? 0 : point.depth_m,
    heading: point.heading_deg === undefined || point.heading_deg === 360 ? 0 : point.heading_deg,
    pitch: point.pitch_deg === undefined ? 0 : point.pitch_deg,
  };
}

export function locateEcho(point) {
  if (point.range_m === null) return null;
  const { x, y, z, heading, pitch } = stationPose(point);
  const radians = Math.PI / 180;
  const horizontal = point.range_m * Math.cos(pitch * radians);
  return {
    x: x + horizontal * Math.sin(heading * radians),
    y: y + point.range_m * Math.sin(pitch * radians),
    z: z + horizontal * Math.cos(heading * radians),
  };
}

export function distanceBetween(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
}

export function groupReturns(points, person) {
  const groups = new Map();
  points.forEach((point, index) => {
    const name = point.surface?.trim();
    const key = name ? `surface:${name}` : `return:${index}`;
    const group = groups.get(key) ?? { key, name: name || `Scan ${index + 1}`, hits: [], rejected: 0 };
    const position = locateEcho(point);
    if (position) group.hits.push({ position, distance: distanceBetween(position, person) });
    else group.rejected += 1;
    groups.set(key, group);
  });
  return [...groups.values()].map((group) => {
    const nearest = group.hits.reduce((best, hit) => best === null || hit.distance < best.distance ? hit : best, null);
    return { ...group, nearest };
  }).sort((a, b) => (a.nearest?.distance ?? Infinity) - (b.nearest?.distance ?? Infinity));
}

function surfacePatches(group) {
  if (!group.key.startsWith("surface:")) return [];
  const locations = group.hits.map(({ position }) => position);
  const faces = new Map();
  locations.forEach((origin, index) => {
    const neighbors = locations.map((point, other) =>
      ({ other, gap: distanceBetween(origin, point) })).filter(({ gap }) => gap >= 0.08 && gap <= 1.35)
      .sort((a, b) => a.gap - b.gap).slice(0, 2);
    if (neighbors.length < 2) return;
    const a = locations[neighbors[0].other];
    const b = locations[neighbors[1].other];
    const u = { x: a.x - origin.x, y: a.y - origin.y, z: a.z - origin.z };
    const v = { x: b.x - origin.x, y: b.y - origin.y, z: b.z - origin.z };
    const area = Math.hypot(u.y * v.z - u.z * v.y, u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x) / 2;
    if (area < 0.025 || distanceBetween(a, b) > 1.6) return;
    const key = [index, ...neighbors.map(({ other }) => other)].sort((a, b) => a - b).join(",");
    faces.set(key, { key: group.key, vertices: [origin, a, b] });
  });
  return [...faces.values()];
}

export function buildRoom(points, person) {
  const groups = groupReturns(points, person);
  return {
    groups,
    stations: points.map((point) => ({ pose: stationPose(point), valid: point.range_m !== null })),
    patches: groups.flatMap(surfacePatches),
  };
}

export function previewReport(trials) {
  const groups = new Map();
  for (const trial of trials) {
    const key = scanKey(trial);
    const group = groups.get(key) ?? [];
    group.push(trial);
    groups.set(key, group);
  }
  const points = [...groups.values()].map((group) => {
    const { trial, status, echo_ratio, source, ...point } = group[0];
    const accepted = group.flatMap((row) => row.range_m === null ? [] : [row.range_m]).sort((a, b) => a - b);
    const count = accepted.length;
    const spread = count >= 2 ? accepted.at(-1) - accepted[0] : null;
    const range = count >= 3 && count > group.length / 2 && spread <= 0.35 ?
      (accepted[Math.floor((count - 1) / 2)] + accepted[Math.floor(count / 2)]) / 2 : null;
    return { ...point, range_m: range, spread_m: spread, accepted: count, total: group.length,
      error_m: range !== null && point.reference_m !== null ? Math.abs(range - point.reference_m) : null };
  });
  return { source: "measured", points };
}

export function scanKey(point) {
  return JSON.stringify([point.scene, stationPose(point), point.surface?.trim() ?? ""]);
}
