/**
 * Short audio cues for scan events. Silent between events by design.
 * Each event has its own shape so it can be told apart without looking.
 */
const patterns = {
  session_started: [[523, 0.09], [784, 0.12]],          // rising pair
  tracking_lost: [[220, 0.16], [220, 0.16]],            // low double
  tracking_restored: [[880, 0.1]],                      // single high
  publisher_connected: [[659, 0.08]],
  publisher_lost: [[440, 0.12], [294, 0.18]],           // falling pair
  scan_saved: [[1047, 0.05], [1319, 0.07]],
  replay_complete: [[587, 0.2]],
  lidar_blind: [[988, 0.07], [740, 0.07], [988, 0.07]],  // sonar found a surface the LiDAR cannot see
};
export const cueNames = Object.keys(patterns);

export function createCues({ context = () => new AudioContext() } = {}) {
  let audio, enabled = false, lastAt = new Map();
  return {
    get enabled() { return enabled; },
    /** Call from a click or change handler: browsers only start audio on a user gesture. */
    setEnabled(on) {
      enabled = Boolean(on);
      if (enabled) {
        audio ??= context();
        audio.resume?.();
      }
    },
    /** Returns true if the cue was played. The same cue is not repeated within 1.5 s. */
    play(name, now = Date.now()) {
      const pattern = patterns[name];
      if (!enabled || !audio || !pattern || now - (lastAt.get(name) ?? -Infinity) < 1500) return false;
      lastAt.set(name, now);
      let start = audio.currentTime + 0.01;
      for (const [frequency, seconds] of pattern) {
        const tone = audio.createOscillator(), gain = audio.createGain();
        tone.frequency.value = frequency;
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.18, start + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + seconds);
        tone.connect(gain).connect(audio.destination);
        tone.start(start);
        tone.stop(start + seconds + 0.02);
        start += seconds + 0.05;
      }
      return true;
    },
  };
}
