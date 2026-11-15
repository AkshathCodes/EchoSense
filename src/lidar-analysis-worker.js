import { analyseLidar } from './lidar-analysis.js';

self.onmessage = ({ data: { id, points, options } }) => {
  try {
    const analysis = analyseLidar(points, options);
    self.postMessage({ id, analysis }, [analysis.labels.buffer]);
  } catch (error) {
    self.postMessage({ id, error: error.message });
  }
};
