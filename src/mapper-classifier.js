import { analyseLidar } from './lidar-analysis.js';

// The mapper adapter allows one distinct map to be classified at a time.
export function createMapperClassifier() {
  let worker, sequence = 0;
  const requests = new Map();
  return (points, options) => {
    if (typeof Worker === 'undefined') return analyseLidar(points, options);
    if (!worker) {
      worker = new Worker(new URL('./lidar-analysis-worker.js', import.meta.url), { type: 'module' });
      worker.onmessage = ({ data }) => {
        const request = requests.get(data.id);
        requests.delete(data.id);
        if (data.error) request?.reject(new Error(data.error));
        else request?.resolve(data.analysis);
      };
      worker.onerror = () => {
        worker.terminate();
        worker = undefined;
        for (const request of requests.values()) request.reject(new Error('LiDAR analysis worker failed'));
        requests.clear();
      };
    }
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      requests.set(id, { resolve, reject });
      worker.postMessage({ id, points, options });
    });
  };
}
