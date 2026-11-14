export const SAMPLE_INTERVAL = 1000;
const WINDOW_SIZE = 12;

// Preserve missing estimates as samples. A snapshot owns its geometry references.
export function sampleHistory(samples, sample) {
  if (samples.length && sample.t - samples.at(-1).t < SAMPLE_INTERVAL) return;
  samples.push(sample);
  if (samples.length > WINDOW_SIZE) samples.shift();
}

export function sampleAt(samples, time) {
  return samples.findLast(sample => sample.t <= time);
}

export function comparable(a, b) {
  return Boolean(a?.space && a.space === b?.space);
}

export function compareReturns(before, after) {
  const key = (p, i) => [p[i], p[i + 1], p[i + 2]].map(n => Math.floor(n / 0.25)).join(',');
  const baseline = new Set();
  for (let i = 0; i < before.length; i += 3) baseline.add(key(before, i));
  const changes = new Float32Array(after.length);
  let cursor = 0;
  for (let i = 0; i < after.length; i += 3) {
    if (!baseline.has(key(after, i))) {
      changes.set(after.subarray(i, i + 3), cursor);
      cursor += 3;
    }
  }
  return changes.subarray(0, cursor);
}

export function positions(cloud) {
  const xyz = new Float32Array(cloud.length / 3);
  for (let i = 0; i < cloud.length; i += 9) xyz.set(cloud.subarray(i, i + 3), i / 3);
  return xyz;
}

export function thumbnail(canvas) {
  const image = document.createElement('canvas');
  image.width = 480;
  image.height = 270;
  const ctx = image.getContext('2d');
  const scale = Math.min(480 / canvas.width, 270 / canvas.height);
  const w = canvas.width * scale, h = canvas.height * scale;
  ctx.fillStyle = '#080e15';
  ctx.fillRect(0, 0, 480, 270);
  ctx.drawImage(canvas, (480 - w) / 2, (270 - h) / 2, w, h);
  return image.toDataURL('image/webp', 0.84);
}

export async function openArchive() {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open('echosense-archive', 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('scans', { keyPath: 'id' });
      request.result.createObjectStore('settings');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const transaction = (stores, write, operation) => new Promise((resolve, reject) => {
    const tx = db.transaction(stores, write ? 'readwrite' : 'readonly');
    const request = operation(tx);
    tx.oncomplete = () => resolve(request?.result);
    tx.onabort = () => reject(tx.error ?? new Error('Archive transaction aborted'));
  });
  return {
    list: () => transaction(['scans'], false, tx => tx.objectStore('scans').getAll()),
    save: scan => transaction(['scans'], true, tx => tx.objectStore('scans').put(scan)),
    remove: id => transaction(['scans'], true, tx => tx.objectStore('scans').delete(id)),
    initialize: scans => transaction(['scans', 'settings'], true, tx => {
      const settings = tx.objectStore('settings');
      const seeded = settings.get('seeded');
      seeded.onsuccess = () => {
        if (seeded.result) return;
        for (const scan of scans) tx.objectStore('scans').put(scan);
        settings.put(true, 'seeded');
      };
    }),
  };
}
