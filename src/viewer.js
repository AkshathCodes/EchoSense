import { anchors } from './room.js';

const VERTEX = `
  attribute vec3 position, scanColor, naturalColor;
  uniform mat4 vp;
  uniform float size, pixelRatio, style;
  varying vec3 tint;
  varying float worldY;
  void main() {
    gl_Position = vp * vec4(position, 1.);
    worldY = position.y;
    gl_PointSize = max(1., size * pixelRatio * clamp(10. / gl_Position.w, .47, 1.85));
    vec3 elevation = mix(vec3(.12,.63,.51), vec3(.74,.64,.83), clamp(position.y / 3., 0., 1.));
    tint = style == 2. ? naturalColor : style == 3. ? mix(scanColor, vec3(.66,.74,.79), .70)
      : style == 4. ? elevation : style == 1. ? mix(scanColor, vec3(.12,.76,.65), .57) : scanColor;
  }`;
const FRAGMENT = `
  precision mediump float;
  varying vec3 tint;
  varying float worldY;
  uniform vec2 heightRange;
  uniform float opacity, points;
  void main() {
    if (worldY < heightRange.x || worldY > heightRange.y) discard;
    float falloff = 1.;
    if (points > .5) {
      float r = length(gl_PointCoord - .5) * 2.;
      if (r > 1.) discard;
      falloff = exp(-1.8*r*r) * (1. - smoothstep(.68, 1., r));
    }
    gl_FragColor = vec4(tint, opacity * falloff);
  }`;
const sub = (a, b) => a.map((n, i) => n - b[i]);
const dot = (a, b) => a.reduce((s, n, i) => s + n * b[i], 0);
const cross = ([x, y, z], [a, b, c]) => [y * c - z * b, z * a - x * c, x * b - y * a];
const unit = a => a.map(n => n / Math.hypot(...a));
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

function viewProjection(eye, center, aspect, offset) {
  const back = unit(sub(eye, center)), right = unit(cross([0, 1, 0], back)), up = cross(back, right);
  const tx = -dot(right, eye), ty = -dot(up, eye), tz = -dot(back, eye);
  const f = 1 / Math.tan(Math.PI / 8.8), a = f / aspect, c = -1.001, d = -0.14;
  return new Float32Array([
    a * right[0] - offset * back[0], f * up[0], c * back[0], -back[0],
    a * right[1] - offset * back[1], f * up[1], c * back[1], -back[1],
    a * right[2] - offset * back[2], f * up[2], c * back[2], -back[2],
    a * tx - offset * tz, f * ty, c * tz + d, -tz,
  ]);
}

function shader(gl, type, source) {
  const stage = gl.createShader(type);
  gl.shaderSource(stage, source);
  gl.compileShader(stage);
  if (!gl.getShaderParameter(stage, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(stage));
  return stage;
}

function makeGrid() {
  const vertices = [];
  const line = (a, b, color) => vertices.push(...a, ...color, ...color, ...b, ...color, ...color);
  for (let n = -10; n <= 10; n++) {
    const minor = [0.135, 0.205, 0.26];
    line([n, -0.044, -10], [n, -0.044, 10], n === 0 ? [0.24, 0.36, 0.41] : minor);
    line([-10, -0.044, n], [10, -0.044, n], n === 0 ? [0.38, 0.25, 0.26] : minor);
  }
  return new Float32Array(vertices);
}

function makeSignals(time, target, ringLayer, trail) {
  const data = [];
  const line = (a, b, col) => data.push(...a, ...col, ...col, ...b, ...col, ...col);
  const circle = ([x, y, z], radius, color, dashed = false) => {
    for (let i = 0; i < 80; i++) {
      if (dashed && i % 6 > 3) continue;
      const a = i * Math.PI / 40, b = (i + 1) * Math.PI / 40;
      line([x + radius * Math.cos(a), y, z + radius * Math.sin(a)],
        [x + radius * Math.cos(b), y, z + radius * Math.sin(b)], color);
    }
  };
  if (ringLayer) anchors.forEach(([x, , z], i) => {
    for (let j = 1; j <= 10; j++) {
      const r = (j * 0.22 + time / 3000 + i * 0.16) % 2.2 + 0.06;
      const glow = 0.87 - r * 0.25;
      circle([x, 0.058, z], r, [0.14 * glow, 0.83 * glow, 0.65 * glow]);
    }
    line([x, 0, z], [x, 0.48, z], [0.43, 0.91, 0.75]);
  });
  if (target) {
    const [x, y, z] = target.position;
    const color = [0.97, 0.61, 0.22], ground = Math.max(y, 0.065);
    circle([x, ground, z], 0.52, color, true);
    circle([x, ground, z], 0.38, [0.66, 0.38, 0.15]);
    circle([x, ground, z], 0.53 + (time % 1400) / 2800, [0.51, 0.25, 0.08], true);
    line([x - 0.13, ground, z], [x + 0.13, ground, z], color);
    line([x, ground, z - 0.13], [x, ground, z + 0.13], color);
    line([x, ground, z], [x, ground + 0.48, z], color);
  }
  trail?.forEach((sample, i) => {
    const previous = trail[i - 1];
    if (!previous?.target || !sample.target || sample.t - previous.t > 1500) return;
    const color = [0.56 + i / trail.length * 0.36, 0.34, 0.14];
    const foot = ([x, y, z]) => [x, Math.max(y, 0.095), z];
    line(foot(previous.target.position), foot(sample.target.position), color);
    circle(foot(sample.target.position), 0.09, color);
  });
  return new Float32Array(data);
}

export function createViewer(canvas, room, onCamera = () => {}, onReset) {
  const gl = canvas.getContext('webgl', { antialias: true, alpha: false });
  if (!gl) throw new Error('WebGL is unavailable in this browser.');
  const program = gl.createProgram();
  gl.attachShader(program, shader(gl, gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, shader(gl, gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
  gl.useProgram(program);
  const attributes = ['position', 'scanColor', 'naturalColor'].map(name => gl.getAttribLocation(program, name));
  attributes.forEach(location => gl.enableVertexAttribArray(location));
  const uniforms = Object.fromEntries(['vp', 'size', 'pixelRatio', 'style', 'opacity', 'points', 'heightRange']
    .map(name => [name, gl.getUniformLocation(program, name)]));
  const upload = (data, service = gl.STATIC_DRAW, buffer = gl.createBuffer()) => {
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, service);
    return buffer;
  };
  const samples = upload(room.cloud), wireframe = upload(room.mesh), grid = upload(makeGrid());
  const live = gl.createBuffer(), signals = gl.createBuffer();
  const changes = gl.createBuffer();
  let changeCount = 0;
  let cloud = samples, cloudCount = room.cloud.length / 9, demoGeometry = true;
  let lastSignalTime, lastTarget, lastRings, lastTrail, signalCount = 0, projection;
  const events = new AbortController();
  const listen = (type, listener, options) =>
    canvas.addEventListener(type, listener, { ...options, signal: events.signal });
  const presets = {
    orbit: { yaw: -0.61, pitch: 0.38, distance: 11.75, center: [0, 1.25, -0.3] },
    camera: { yaw: -0.13, pitch: 0.055, distance: 4.9, center: [0.23, 1.31, -1.72] },
    top: { yaw: 0, pitch: 1.565, distance: 13.9, center: [0, 0.04, 0.10] },
  };
  let desired, current, viewMode = 'orbit';
  const pointers = new Map();
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const clone = state => ({ ...state, center: [...state.center] });
  const moved = () => onCamera(clone(desired), viewMode);
  function preset(name, immediate = false) {
    viewMode = name;
    desired = clone(presets[name]);
    if (immediate || motion.matches) current = clone(desired);
    canvas.dataset.view = name;
    moved();
  }
  preset('orbit', true);
  function pan(dx, dy) {
    const scale = 0.00155 * desired.distance;
    desired.center[0] -= dx * scale * Math.cos(desired.yaw);
    desired.center[2] += dx * scale * Math.sin(desired.yaw);
    if (viewMode === 'top') {
      desired.center[0] -= dy * scale * Math.sin(desired.yaw);
      desired.center[2] -= dy * scale * Math.cos(desired.yaw);
    } else {
      desired.center[1] += dy * scale;
    }
  }
  function orbit(dx, dy) {
    desired.yaw -= dx * 0.006;
    if (viewMode !== 'top') desired.pitch = clamp(desired.pitch + dy * 0.005, -0.08, 1.55);
  }
  function zoom(factor) { desired.distance = clamp(desired.distance * factor, 1.5, 34); moved(); }
  listen('pointerdown', e => {
    if (pointers.size >= 2) return;
    pointers.set(e.pointerId, [e.clientX, e.clientY, e.button !== 0 || e.shiftKey]);
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add('dragging');
  });
  listen('pointermove', e => {
    const pointer = pointers.get(e.pointerId);
    if (!pointer) return;
    const dx = e.clientX - pointer[0], dy = e.clientY - pointer[1];
    if (pointers.size === 2) {
      const other = [...pointers.values()].find(p => p !== pointer);
      const before = Math.hypot(pointer[0] - other[0], pointer[1] - other[1]);
      const after = Math.hypot(e.clientX - other[0], e.clientY - other[1]);
      if (before > 3 && after > 3) zoom(before / after);
      pan(dx / 2, dy / 2);
    } else {
      (e.shiftKey || pointer[2] || viewMode === 'top' ? pan : orbit)(dx, dy);
    }
    pointer[0] = e.clientX;
    pointer[1] = e.clientY;
    moved();
  });
  listen('lostpointercapture', e => {
    pointers.delete(e.pointerId);
    if (!pointers.size) canvas.classList.remove('dragging');
  });
  listen('contextmenu', e => e.preventDefault());
  listen('wheel', e => {
    e.preventDefault();
    zoom(Math.exp(clamp(e.deltaY, -200, 200) * (e.deltaMode ? 0.025 : 0.0011)));
  }, { passive: false });
  listen('keydown', e => {
    const arrows = { ArrowLeft: [-22, 0], ArrowRight: [22, 0], ArrowUp: [0, -22], ArrowDown: [0, 22] };
    if (Object.hasOwn(arrows, e.key)) (e.shiftKey || viewMode === 'top' ? pan : orbit)(...arrows[e.key]);
    else if (e.key === '+' || e.key === '=') zoom(0.86);
    else if (e.key === '-') zoom(1.16);
    else if (e.key === '0' && onReset) onReset();
    else if (e.key === '0') preset(viewMode);
    else return;
    e.preventDefault();
    moved();
  });
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.enable(gl.DEPTH_TEST);
  gl.depthFunc(gl.LEQUAL);
  gl.clearColor(0.033, 0.053, 0.078, 1);
  function drawBuffer(buffer, count, primitive, style, opacity) {
    if (!count) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    attributes.forEach((location, i) => gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 36, 12 * i));
    gl.uniform1f(uniforms.style, style);
    gl.uniform1f(uniforms.opacity, opacity);
    gl.uniform1f(uniforms.points, primitive === gl.POINTS ? 1 : 0);
    gl.drawArrays(primitive, 0, count);
  }

  return {
    preset, zoom,
    frameCloud(points) {
      if (!points.length) return;
      const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < points.length; i++) {
        const axis = i % 3;
        low[axis] = Math.min(low[axis], points[i]);
        high[axis] = Math.max(high[axis], points[i]);
      }
      desired.center = low.map((n, i) => (n + high[i]) / 2);
      desired.distance = clamp(Math.hypot(...high.map((n, i) => n - low[i])) * 1.8, 2.8, 34);
      current = clone(desired);
      moved();
    },
    get heading() { return (Math.round(-current.yaw * 180 / Math.PI) % 360 + 360) % 360; },
    camera: () => ({ state: clone(desired), view: viewMode }),
    follow(camera, name) {
      desired = clone(camera);
      viewMode = name;
      canvas.dataset.view = name;
    },
    replaceChanges(points) {
      const data = new Float32Array(points.length * 3);
      for (let i = 0; i < points.length; i += 3) {
        data.set(points.subarray(i, i + 3), i * 3);
        data.set([0.35, 0.93, 1], i * 3 + 3);
      }
      upload(data, gl.STATIC_DRAW, changes);
      changeCount = points.length / 3;
    },
    dispose() {
      events.abort();
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    },
    get count() { return cloudCount; },
    get meshCount() { return room.mesh.length / 9; },
    get hasMesh() { return demoGeometry; },
    replaceCloud(points) {
      demoGeometry = points === undefined;
      if (demoGeometry) {
        cloud = samples;
        cloudCount = room.cloud.length / 9;
      } else {
        const vertices = new Float32Array(points.length * 3);
        for (let i = 0; i < points.length / 3; i++) {
          vertices.set(points.subarray(i * 3, i * 3 + 3), i * 9);
          vertices.set([0.23, 0.65, 1, 0.49, 0.64, 0.72], i * 9 + 3);
        }
        cloud = upload(vertices, gl.DYNAMIC_DRAW, live);
        cloudCount = points.length / 3;
      }
    },
    project(position) {
      if (!projection) return null;
      const [x, y, z] = position, m = projection;
      const w = m[3] * x + m[7] * y + m[11] * z + m[15];
      if (w <= 0.1) return null;
      const sx = (m[0] * x + m[4] * y + m[8] * z + m[12]) / w;
      const sy = (m[1] * x + m[5] * y + m[9] * z + m[13]) / w;
      if (Math.abs(sx) > 0.96 || Math.abs(sy) > 0.91) return null;
      return [(sx + 1) * 50, (1 - sy) * 50];
    },
    draw({ mode, pointSize, pointCap, showGrid, rings, target, time, meshTint,
      heightRange = [-10001, 10001], changeOverlay = false, trail, dimensions, comparison = false }) {
      const mobile = !dimensions && canvas.clientWidth < 650;
      const ratio = dimensions ? 1 : Math.min(devicePixelRatio, 2);
      const width = dimensions?.[0] ?? Math.max(1, Math.round(canvas.clientWidth * ratio));
      const height = dimensions?.[1] ?? Math.max(1, Math.round(canvas.clientHeight * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, width, height);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const lerp = motion.matches ? 1 : 0.16;
      for (const field of ['yaw', 'pitch', 'distance']) current[field] += (desired[field] - current[field]) * lerp;
      current.center = current.center.map((n, i) => n + (desired.center[i] - n) * lerp);
      const { yaw, pitch, distance, center } = current;
      const fit = comparison ? clamp((height / width) * 1.55, 1, 2.5)
        : mobile && viewMode !== 'camera' ? clamp((height / width) * 1.38, 1.12, 2.85) : 1;
      const range = distance * fit;
      const eye = [Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)]
        .map((n, i) => center[i] + n * range);
      projection = viewProjection(eye, center, Math.max(width / height, 0.01),
        mobile || comparison || viewMode === 'camera' ? 0 : -0.12);
      gl.uniformMatrix4fv(uniforms.vp, false, projection);
      gl.uniform1f(uniforms.size, (1.15 + pointSize * 0.195) * (mobile ? 1.17 : 1));
      gl.uniform1f(uniforms.pixelRatio, ratio);
      gl.uniform2f(uniforms.heightRange, -10001, 10001);
      if (showGrid) drawBuffer(grid, 84, gl.LINES, 0, 0.65);
      gl.uniform2fv(uniforms.heightRange, heightRange);
      if (mode === 'mesh' && demoGeometry) {
        drawBuffer(wireframe, Math.min(pointCap, room.mesh.length / 9), gl.LINES,
          meshTint === 'ice' ? 3 : meshTint === 'height' ? 4 : 0, 0.58);
      } else {
        gl.depthMask(false);
        gl.blendFunc(gl.SRC_ALPHA, mode === 'color' ? gl.ONE_MINUS_SRC_ALPHA : gl.ONE);
        drawBuffer(cloud, Math.min(pointCap, cloudCount), gl.POINTS,
          changeOverlay ? 3 : mode === 'color' ? 2 : rings ? 1 : 0, changeOverlay ? 0.27 : 0.96);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.depthMask(true);
      }
      if (changeOverlay) drawBuffer(changes, changeCount, gl.POINTS, 0, 1);
      gl.uniform2f(uniforms.heightRange, -10001, 10001);
      if (lastSignalTime !== time || lastTarget !== target || lastRings !== rings || lastTrail !== trail) {
        const data = makeSignals(time, target, rings, trail);
        upload(data, gl.DYNAMIC_DRAW, signals);
        signalCount = data.length / 9;
        lastSignalTime = time;
        lastTarget = target;
        lastRings = rings;
        lastTrail = trail;
      }
      drawBuffer(signals, signalCount, gl.LINES, 0, 0.83);
    },
  };
}
