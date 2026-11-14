import { sampleAt } from './archive.js';

const el = id => document.getElementById(id);

export function createReplay() {
  const seek = el('playhead'), play = el('play-replay');
  let map, start = 0, duration = 0, time = 0, playing = false, previous;

  function update() {
    seek.value = time;
    el('replay-time').textContent = `${(time / 1000).toFixed(1)} / ${(duration / 1000).toFixed(1)} s`;
    play.textContent = playing ? 'Pause' : time >= duration && duration ? 'Replay' : 'Play';
  }

  function pause() {
    playing = false;
    previous = undefined;
    update();
  }
  seek.addEventListener('input', () => { time = Number(seek.value); pause(); });
  play.addEventListener('click', () => {
    if (playing) return pause();
    if (time >= duration) time = 0;
    playing = true;
    update();
  });

  return {
    open(scan) {
      map = scan;
      start = scan.history[0]?.t ?? 0;
      duration = (scan.history.at(-1)?.t ?? start) - start;
      time = duration;
      seek.max = duration;
      seek.disabled = play.disabled = !duration;
      el('replay-name').textContent = scan.name;
      pause();
    },
    pause,
    frame(now) {
      if (playing) {
        time = Math.min(duration, time + (previous === undefined ? 0 : now - previous));
        previous = now;
        if (time >= duration) pause();
        else update();
      }
      const t = start + time;
      if (time >= duration) return { sample: map, t, history: map.history };
      return { sample: sampleAt(map.history, t), t, history: map.history };
    },
  };
}
