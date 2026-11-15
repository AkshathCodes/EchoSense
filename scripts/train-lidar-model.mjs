import { writeFileSync } from 'node:fs';
import { classifyRoom, classNames } from '../src/room-classifier.js';
import { lidarFeatures, FEATURE_COUNT } from '../src/lidar-features.js';
import { predictLidar } from '../src/lidar-predict.js';
import { rng, syntheticScan } from './lidar-training-data.mjs';

const trainSeeds = Array.from({ length: 32 }, (_, i) => 1409 + i * 919);
const validationSeeds = Array.from({ length: 8 }, (_, i) => 50111 + i * 1831);
const testSeeds = Array.from({ length: 12 }, (_, i) => 80953 + i * 2203);
const K = classNames.length, random = rng(1729);
const open = seed => {
  const { points, hits, labels } = syntheticScan(seed, { rough: seed % 3 !== 0 });
  const start = performance.now(), baseline = classifyRoom(points, { hits });
  const baselineMs = performance.now() - start;
  const features = lidarFeatures(points, hits, baseline);
  return { points, hits, truth: labels, features, baseline: baseline.labels, baselineMs };
};

function train() {
  const byClass = Array.from({ length: K }, () => []);
  for (const seed of trainSeeds) {
    const { truth, features } = open(seed);
    for (let i = 0; i < truth.length; i++) if (random() < 0.24) byClass[truth[i]].push([features, i, truth[i]]);
  }
  function branch(rows, depth) {
    const counts = new Uint32Array(K);
    for (const row of rows) counts[row[2]]++;
    const best = counts.indexOf(Math.max(...counts));
    if (!depth || rows.length < 24 || counts[best] === rows.length) return best;
    let choice, gain = 0;
    const purity = (a, n) => a.reduce((sum, x) => sum + x * x, 0) / n;
    const parent = purity(counts, rows.length);
    const start = Math.floor(random() * FEATURE_COUNT);
    for (let j = 0; j < 6; j++) {
      const feature = (start + j * 5) % FEATURE_COUNT;
      const value = ([data, i]) => data[i * FEATURE_COUNT + feature];
      const samples = Array.from({ length: 22 }, () => value(rows[Math.floor(random() * rows.length)])).sort((a, b) => a - b);
      for (let q = 1; q < samples.length; q += 2) {
        const threshold = (samples[q - 1] + samples[q]) / 2, left = new Uint32Array(K);
        let n = 0;
        for (const row of rows) if (value(row) <= threshold) { left[row[2]]++; n++; }
        if (n < 10 || rows.length - n < 10) continue;
        const improved = purity(left, n) + purity(counts.map((x, i) => x - left[i]), rows.length - n) - parent;
        if (improved > gain) { gain = improved; choice = [feature, threshold]; }
      }
    }
    if (!choice) return best;
    const [feature, threshold] = choice, a = [], b = [];
    for (const row of rows) (row[0][row[1] * FEATURE_COUNT + feature] <= threshold ? a : b).push(row);
    return [feature, threshold, branch(a, depth - 1), branch(b, depth - 1)];
  }
  const trees = Array.from({ length: 17 }, () => branch(byClass.flatMap(pool =>
    Array.from({ length: Math.min(pool.length, 4200) }, () => pool[Math.floor(random() * pool.length)])), 8));
  return { name: 'LiDAR surface forest v1', trees, agreement: 0 };
}

function measure(rooms, model, analyse) {
  const confusion = Array.from({ length: K }, () => Array(K).fill(0)), votes = new Uint8Array(K);
  let correct = 0, total = 0;
  for (const room of rooms) {
    const predictions = analyse?.(room.points, { hits: room.hits }).labels;
    for (let i = 0; i < room.truth.length; i++) {
      const found = predictions ? predictions[i] : model ? predictLidar(room.features, i, model, votes) : room.baseline[i];
      confusion[room.truth[i]][found]++;
      correct += found === room.truth[i]; total++;
    }
  }
  const f1 = confusion.map((row, i) => 2 * row[i] / Math.max(1, row.reduce((a, b) => a + b) + confusion.reduce((n, r) => n + r[i], 0)));
  return { total, accuracy: correct / total, macroF1: f1.reduce((a, b) => a + b) / K,
    f1: Object.fromEntries(classNames.map((name, i) => [name, f1[i]])),
    unclassified: confusion.reduce((n, row) => n + row[0], 0) / total, confusion };
}

const measureOnly = process.argv.includes('--evaluate');
const target = new URL('../src/lidar-model.js', import.meta.url);
const model = measureOnly ? (await import(target.href)).lidarModel : train();
if (!measureOnly) {
  const validation = validationSeeds.map(open);
  model.agreement = [0, 0.42, 0.53, 0.59].map(agreement => ({
    agreement, score: measure(validation, { ...model, agreement }).macroF1,
  })).sort((a, b) => b.score - a.score)[0].agreement;
  const lines = model.trees.map(tree => JSON.stringify(tree)).join(',\n');
  writeFileSync(target, `// Generated: node scripts/train-lidar-model.mjs\nexport const lidarModel = { name: ${JSON.stringify(model.name)}, agreement: ${model.agreement}, trees: [\n${lines}\n] };\n`);
}
const test = testSeeds.map(open);
const { analyseLidar } = await import('../src/lidar-analysis.js');
const timings = test.map(({ points, hits }) => {
  const start = performance.now();
  analyseLidar(points, { hits });
  return performance.now() - start;
}).sort((a, b) => a - b);
const baselineTimings = test.map(room => room.baselineMs).sort((a, b) => a - b);
console.log(JSON.stringify({ trainingRooms: trainSeeds.length, validationRooms: validationSeeds.length,
  testRooms: testSeeds.length, agreement: model.agreement, classes: classNames,
  baseline: measure(test), trained: measure(test, model, analyseLidar),
  analysisMs: { geometricMedian: baselineTimings[Math.floor(baselineTimings.length / 2)],
    trainedMedian: timings[Math.floor(timings.length / 2)], trainedMax: timings.at(-1),
    maxPoints: Math.max(...test.map(room => room.truth.length)) } }, null, 2));
