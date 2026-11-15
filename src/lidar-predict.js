import { FEATURE_COUNT } from './lidar-features.js';

// Each branch stores [feature, threshold, left, right]; leaves store a class ID.
export function predictLidar(features, i, model, votes) {
  votes.fill(0);
  for (const tree of model.trees) {
    let node = tree;
    while (Array.isArray(node)) node = features[i * FEATURE_COUNT + node[0]] <= node[1] ? node[2] : node[3];
    votes[node]++;
  }
  let winner = 0;
  for (let k = 1; k < votes.length; k++) if (votes[k] > votes[winner]) winner = k;
  return votes[winner] / model.trees.length >= model.agreement ? winner : 0;
}
