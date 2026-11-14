import { captureTrials, openRecorder, readSerialBatch, toWave } from "./capture.mjs";
import { buildRoom, parseRangeTrials, previewReport, scanKey, stationPose, validateReport } from "./map.mjs";
import { drawRoom, initialView } from "./room-view.mjs";

const byId = (id) => document.getElementById(id);
const elements = {
  source: byId("source"),
  scene: byId("scene"),
  sceneLabel: byId("scene-label"),
  map: byId("map"),
  mapBody: byId("map-body"),
  mapMessage: byId("map-message"),
  readings: byId("readings"),
  file: byId("load-report"),
  demo: byId("load-demo"),
  published: byId("load-published"),
  form: byId("scan-form"),
  scan: byId("scan"),
  addRanges: byId("add-ranges"),
  readSerial: byId("read-serial"),
  ranges: byId("ranges"),
  download: byId("download"),
  downloadAudio: byId("download-audio"),
  captureMessage: byId("capture-message"),
  position: byId("person-position"),
  personHeight: byId("person-height"),
  downloadMap: byId("download-map"),
};

let currentReport;
let capturedTrials = [];
let latestAudio;
let person;
let model;
let view = initialView;
let selectedKey;
let drawnHits = [];

const panelCases = {
  one: { scene: "Panel at 1 m", reference: 1, surface: "Panel" },
  two: { scene: "Panel at 2 m", reference: 2, surface: "Panel" },
  clear: { scene: "Panel removed", reference: "", surface: "Background" },
};

function selectedPoints() {
  return currentReport.points.filter((point) => point.scene === elements.scene.value)
    .sort((left, right) => left.station_m - right.station_m);
}

function refreshMap() {
  if (model) drawnHits = drawRoom(elements.map, model, person, view, selectedKey);
}

function showDistances() {
  model = buildRoom(selectedPoints(), person);
  const selectable = model.groups.filter((group) => group.nearest);
  if (!selectable.some((group) => group.key === selectedKey)) selectedKey = selectable[0]?.key;
  const focusedKey = elements.readings.contains(document.activeElement) ? document.activeElement.dataset.returnKey : null;
  elements.position.textContent = `X ${person.x.toFixed(2)} · Z ${person.z.toFixed(2)} m`;
  elements.readings.replaceChildren(...model.groups.map((group) => {
    const row = document.createElement("li");
    const button = document.createElement("button");
    const name = document.createElement("span");
    const distance = document.createElement("strong");
    const detail = document.createElement("small");
    name.textContent = group.name;
    distance.textContent = group.nearest ? `${group.nearest.distance.toFixed(2)} m` : "Uncertain";
    detail.textContent = group.hits.length === 1 ? "1 return" : `${group.hits.length} returns`;
    if (group.rejected) detail.textContent += ` · ${group.rejected} uncertain`;
    button.type = "button";
    button.dataset.returnKey = group.key;
    button.setAttribute("aria-pressed", String(group.key === selectedKey));
    button.disabled = !group.nearest;
    button.append(name, distance, detail);
    row.append(button);
    return row;
  }));
  if (focusedKey) {
    [...elements.readings.querySelectorAll("button")].find((button) => button.dataset.returnKey === focusedKey)?.focus();
  }
  refreshMap();
}

function resetPerson() {
  const { x, y, z } = stationPose(selectedPoints()[0]);
  person = { x, y, z };
  elements.personHeight.value = y;
  showDistances();
}

function selectReturn(key) {
  selectedKey = key;
  for (const button of elements.readings.querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.returnKey === key));
  }
  refreshMap();
}

function showReport(payload, preferredScene) {
  currentReport = validateReport(payload);
  const scenes = [...new Set(currentReport.points.map((point) => point.scene))];
  elements.scene.replaceChildren(...scenes.map((scene) => new Option(scene, scene)));
  if (scenes.includes(preferredScene)) elements.scene.value = preferredScene;
  elements.sceneLabel.hidden = scenes.length === 1;
  elements.source.textContent = currentReport.source === "simulated" ? "SIMULATED DATA" : "MEASURED DATA";
  elements.source.classList.toggle("measured", currentReport.source === "measured");
  elements.source.hidden = false;
  elements.mapMessage.textContent = "";
  elements.mapMessage.classList.remove("error");
  elements.mapBody.hidden = false;
  showQuality(currentReport.points);
  selectedKey = undefined;
  resetPerson();
}

function showQuality(points) {
  const mapped = points.filter((point) => point.range_m !== null);
  const usable = points.reduce((count, point) => count + point.accepted, 0);
  const total = points.reduce((count, point) => count + point.total, 0);
  const errors = mapped.flatMap((point) => point.error_m === null ? [] : [point.error_m]);
  const meanError = errors.reduce((sum, error) => sum + error, 0) / errors.length;
  const accuracy = errors.length ? ` · ${(meanError * 100).toFixed(1)} cm mean error across ${errors.length} mapped tape references` : "";
  byId("quality-summary").textContent = `${usable}/${total} usable readings · ${mapped.length}/${points.length} mapped positions${accuracy}`;
  const results = [];
  for (const { scene } of Object.values(panelCases)) {
    const batches = points.filter((point) => point.scene === scene);
    for (const point of batches) {
      const row = document.createElement("li");
      const expected = point.reference_m === null ? "" : ` · Tape ${point.reference_m.toFixed(2)} m`;
      const actual = point.range_m === null ? "Uncertain" : `${point.range_m.toFixed(2)} m return`;
      row.textContent = `${scene} · ${actual}${expected} · ${point.accepted}/${point.total} usable`;
      results.push(row);
    }
  }
  byId("quality-results").replaceChildren(...results);
  byId("quality-results").hidden = results.length === 0;
  byId("scan-quality").hidden = false;
}

function showError(element, error) {
  element.textContent = error instanceof Error ? error.message : String(error);
  element.classList.add("error");
}

elements.scene.addEventListener("change", () => {
  selectedKey = undefined;
  resetPerson();
});
window.addEventListener("resize", refreshMap);
elements.readings.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-return-key]");
  if (button && !button.disabled) selectReturn(button.dataset.returnKey);
});
byId("reset-person").addEventListener("click", resetPerson);
elements.personHeight.addEventListener("change", () => {
  if (!elements.personHeight.value || !elements.personHeight.validity.valid) {
    elements.personHeight.value = person.y;
    return;
  }
  person = { ...person, y: elements.personHeight.valueAsNumber };
  showDistances();
});
for (const button of document.querySelectorAll("button[data-axis]")) {
  button.addEventListener("click", () => {
    const { axis, meters } = button.dataset;
    person = { ...person, [axis]: Math.max(-30, Math.min(30, person[axis] + Number(meters))) };
    showDistances();
  });
}

function setView(next) {
  view = next;
  const top = view.tilt === Math.PI / 2;
  byId("view-top").setAttribute("aria-pressed", String(top));
  byId("view-3d").setAttribute("aria-pressed", String(!top));
  refreshMap();
}

byId("view-3d").addEventListener("click", () => setView(initialView));
byId("view-top").addEventListener("click", () => setView({ ...view, yaw: 0, tilt: Math.PI / 2 }));
byId("zoom-in").addEventListener("click", () => setView({ ...view, zoom: Math.min(1.7, view.zoom + 0.15) }));
byId("zoom-out").addEventListener("click", () => setView({ ...view, zoom: Math.max(0.55, view.zoom - 0.15) }));

let drag;
elements.map.addEventListener("pointerdown", (event) => {
  if (!event.isPrimary || event.button !== 0) return;
  elements.map.setPointerCapture(event.pointerId);
  drag = { x: event.clientX, y: event.clientY, view };
});
elements.map.addEventListener("pointermove", (event) => {
  if (!drag || !event.isPrimary) return;
  const dx = event.clientX - drag.x;
  const dy = event.clientY - drag.y;
  if (Math.hypot(dx, dy) < 5) return;
  setView({ ...drag.view, yaw: drag.view.yaw + dx * 0.009,
    tilt: Math.max(0.15, Math.min(1.49, drag.view.tilt + dy * 0.008)) });
});
elements.map.addEventListener("pointerup", (event) => {
  if (!drag || !event.isPrimary) return;
  if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 5) {
    const { left, top } = elements.map.getBoundingClientRect();
    const x = event.clientX - left;
    const y = event.clientY - top;
    const hit = drawnHits.map((entry) => ({ ...entry, gap: Math.hypot(entry.point.x - x, entry.point.y - y) }))
      .filter((entry) => entry.gap < 18).sort((a, b) => a.gap - b.gap)[0];
    if (hit) selectReturn(hit.key);
  }
  drag = undefined;
});
elements.map.addEventListener("lostpointercapture", () => { drag = undefined; });

async function loadMap(path, onMissing) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (response.status === 404) throw new Error(onMissing);
    if (!response.ok) throw new Error(`Map request failed (HTTP ${response.status}).`);
    const report = await response.json();
    showReport(report, path === "./sample-map.json" ? "Sample room" : undefined);
  } catch (error) {
    showError(elements.mapMessage, error);
  }
}

elements.demo.addEventListener("click", () => loadMap("./sample-map.json", "The sample map file is missing."));
elements.published.addEventListener("click", () => loadMap("./room-map.json",
  "No shared scan report yet. On the laptop, save your report as acoustic/room-map.json."));

elements.file.addEventListener("change", async () => {
  const file = elements.file.files[0];
  if (!file) return;
  try {
    showReport(JSON.parse(await file.text()));
  } catch (error) {
    showError(elements.mapMessage, error);
  } finally {
    elements.file.value = "";
  }
});

function addTrials(pose, results) {
  const key = scanKey(pose);
  const rows = results.map((result, index) => ({
    source: "measured", ...pose, trial: index + 1, ...result,
  }));
  capturedTrials = [...capturedTrials.filter((row) => scanKey(row) !== key), ...rows];
  showReport(previewReport(capturedTrials), pose.scene);
  elements.download.disabled = false;
  elements.downloadMap.disabled = false;
  const accepted = results.filter((result) => result.status === "ok");
  const distances = accepted.map((result) => `${result.range_m.toFixed(2)} m`).join(", ");
  const statuses = results.filter((result) => result.status !== "ok")
    .map((result) => result.status.replaceAll("_", " ")).join(", ");
  elements.captureMessage.textContent = `${accepted.length}/${results.length} usable` +
    (distances ? ` (${distances})` : "") + (statuses ? `. Rejected: ${statuses}.` : ".");
}

function readScanPose() {
  const fields = new FormData(elements.form);
  const scene = String(fields.get("scene")).trim();
  if (!scene) throw new TypeError("Give the scene a name.");
  const reference = fields.get("reference") === "" ? null : Number(fields.get("reference"));
  return { scene, station_m: Number(fields.get("station")), depth_m: Number(fields.get("depth")),
    height_m: Number(fields.get("height")), heading_deg: Number(fields.get("heading")) % 360,
    pitch_deg: Number(fields.get("pitch")), surface: String(fields.get("surface")).trim(), reference_m: reference };
}

byId("panel-test").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-panel-case]");
  if (!button || elements.scan.disabled) return;
  const setup = panelCases[button.dataset.panelCase];
  byId("scene-name").value = setup.scene;
  byId("surface").value = setup.surface;
  byId("reference").value = "";
  byId("reference").placeholder = setup.reference === "" ? "" : setup.reference.toFixed(2);
  elements.captureMessage.classList.remove("error");
  elements.captureMessage.textContent = setup.reference === "" ?
    "Move the panel out of the beam. Keep the scanner in the same position." :
    `Set the panel at ${setup.reference} m from the scanner. Enter your actual tape measurement before recording.`;
});

function setCaptureBusy(busy) {
  elements.scan.disabled = busy;
  elements.addRanges.disabled = busy;
  elements.readSerial.disabled = busy || !navigator.serial;
}

elements.readSerial.disabled = !navigator.serial;
elements.readSerial.addEventListener("click", async () => {
  if (elements.scan.disabled || !elements.form.reportValidity()) return;
  setCaptureBusy(true);
  elements.captureMessage.classList.remove("error");
  try {
    const pose = readScanPose();
    const baudRate = Number(byId("sensor-baud").value);
    const port = await navigator.serial.requestPort();
    elements.captureMessage.textContent = "Keep the scanner still while EchoSense reads five pings.";
    const ranges = await readSerialBatch(port, baudRate, 10000);
    addTrials(pose, parseRangeTrials(ranges));
  } catch (error) {
    showError(elements.captureMessage, error);
  } finally {
    setCaptureBusy(false);
  }
});

elements.addRanges.addEventListener("click", () => {
  if (elements.scan.disabled || !elements.form.reportValidity()) return;
  elements.captureMessage.classList.remove("error");
  try {
    addTrials(readScanPose(), parseRangeTrials(elements.ranges.value));
    elements.ranges.value = "";
  } catch (error) {
    showError(elements.captureMessage, error);
  }
});

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (elements.scan.disabled) return;
  setCaptureBusy(true);
  elements.captureMessage.classList.remove("error");
  elements.captureMessage.textContent = "Keep the scanner still during the five chirps.";
  let recorder;
  try {
    const pose = readScanPose();
    recorder = await openRecorder();
    const { results, recording, rate } = await captureTrials(recorder);
    latestAudio = toWave(recording, rate);
    addTrials(pose, results);
    elements.downloadAudio.disabled = false;
  } catch (error) {
    showError(elements.captureMessage, error);
  } finally {
    if (recorder) {
      recorder.stream.getTracks().forEach((track) => track.stop());
      await recorder.context.close();
    }
    setCaptureBusy(false);
  }
});

function csvField(value) {
  if (value === null) return "";
  return `"${String(value).replaceAll('"', '""')}"`;
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

elements.download.addEventListener("click", () => {
  const fields = ["source", "scene", "station_m", "depth_m", "height_m", "heading_deg", "pitch_deg",
    "surface", "reference_m", "trial", "status", "range_m", "echo_ratio"];
  const lines = capturedTrials.map((trial) => fields.map((field) => csvField(trial[field])).join(","));
  const csv = [fields.join(","), ...lines].join("\r\n") + "\r\n";
  download(new Blob([csv], { type: "text/csv;charset=utf-8" }), "echosense-scans.csv");
});

elements.downloadAudio.addEventListener("click", () => download(latestAudio, "echosense-last-scan.wav"));
elements.downloadMap.addEventListener("click", () => {
  const report = JSON.stringify(previewReport(capturedTrials), null, 2);
  download(new Blob([report], { type: "application/json" }), "room-map.json");
});
