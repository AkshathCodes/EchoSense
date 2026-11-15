import { comparable, compareReturns } from './archive.js';
import { createViewer } from './viewer.js';
import { sonarLabel } from './sonar.js';
import { lidarLabel } from './lidar.js';

const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const format = new Intl.NumberFormat('en-US');
const el = id => document.getElementById(id);

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function button(text, perform, className) {
  const element = node('button', text, className);
  element.type = 'button';
  element.addEventListener('click', perform);
  return element;
}

export function createLibrary({ show, open, scan }) {
  const list = el('map-list'), search = el('map-search'), filter = el('map-filter');
  const compare = el('compare-maps'), dialog = el('map-dialog'), name = el('map-name');
  const feedback = el('library-status');
  const selected = new Set();
  let archive, maps = [], action, closingComparison, returnFocus;

  function selection() {
    compare.disabled = selected.size !== 2;
    el('compare-selection').textContent = selected.size ? `${selected.size} / 2 selected` : 'Choose two maps';
    for (const input of list.querySelectorAll('input[type="checkbox"]')) {
      input.checked = selected.has(input.value);
      input.disabled = selected.size === 2 && !input.checked;
    }
  }

  function edit(kind, map) {
    returnFocus = document.activeElement;
    el('dialog-title').textContent = { save: 'Save snapshot', rename: 'Rename map', delete: 'Delete map' }[kind];
    el('dialog-text').textContent = kind === 'delete' ? `Remove “${map.name}” from this browser?` : '';
    el('dialog-error').textContent = '';
    el('name-label').hidden = kind === 'delete';
    name.required = kind !== 'delete';
    name.value = map.name;
    el('confirm-map').textContent = { save: 'Save map', rename: 'Save name', delete: 'Delete map' }[kind];
    action = { kind, map };
    dialog.showModal();
    (kind === 'delete' ? el('cancel-map') : name).focus();
    if (kind !== 'delete') name.select();
  }

  function card(map) {
    const article = node('article', '', 'map-card');
    const preview = button('', () => open(map), 'map-preview');
    preview.setAttribute('aria-label', `Open map ${map.name}`);
    const thumb = node('img');
    thumb.src = map.thumb;
    thumb.alt = '';
    const badge = node('span', map.lidar ? lidarLabel(map.lidar) : map.sonar ? sonarLabel(map.sonar)
      : map.source === 'live' ? 'Live capture' : 'Mock', 'map-source');
    badge.dataset.source = map.source;
    preview.append(thumb, badge);
    const info = node('div', '', 'map-info');
    const heading = node('h3', map.name);
    const time = node('time', date.format(new Date(map.date)));
    time.dateTime = map.date;
    const data = node('p', `${format.format(map.points.length / 3)} points · ${map.history.length > 1
      ? `${((map.history.at(-1).t - map.history[0].t) / 1000).toFixed(1)} s replay` : 'Single frame'}`);
    const actions = node('div', '', 'map-actions');
    const check = node('label', 'Compare');
    const input = node('input');
    input.type = 'checkbox';
    input.value = map.id;
    input.setAttribute('aria-label', `Compare ${map.name}`);
    input.addEventListener('change', () => {
      if (input.checked && selected.size < 2) selected.add(map.id);
      else selected.delete(map.id);
      selection();
    });
    check.prepend(input);
    actions.append(check, button('Rename', () => edit('rename', map)), button('Delete', () => edit('delete', map)));
    info.append(heading, time, data, actions);
    article.append(preview, info);
    return article;
  }

  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    const filtered = maps.filter(map => map.name.toLocaleLowerCase().includes(query) &&
      (filter.value === 'all' || filter.value === map.source));
    const count = maps.filter(map => map.source === 'live').length;
    el('total-maps').textContent = maps.length;
    el('live-maps').textContent = count;
    el('mock-maps').textContent = maps.length - count;
    list.replaceChildren(...filtered.map(card));
    if (!filtered.length && archive) list.append(node('p', maps.length
      ? 'No maps match your search.' : 'No maps saved yet. Capture a snapshot from the scanner.', 'empty-maps'));
    selection();
  }

  async function refresh() {
    maps = (await archive.list()).sort((a, b) => b.date.localeCompare(a.date));
    const ids = new Set(maps.map(map => map.id));
    for (const id of selected) if (!ids.has(id)) selected.delete(id);
    render();
  }

  search.addEventListener('input', render);
  filter.addEventListener('change', render);
  el('new-scan').addEventListener('click', scan);
  el('cancel-map').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { if (returnFocus?.isConnected) returnFocus.focus(); });
  el('map-form').addEventListener('submit', async event => {
    event.preventDefault();
    const { kind, map } = action;
    if (kind !== 'delete' && !name.value.trim()) {
      el('dialog-error').textContent = 'Enter a map name.';
      return;
    }
    const confirm = el('confirm-map');
    confirm.disabled = true;
    try {
      if (kind === 'delete') await archive.remove(map.id);
      else await archive.save({ ...map, name: name.value.trim() });
      await refresh();
      dialog.close();
      if (kind === 'save') {
        el('capture-status').textContent = 'Snapshot saved';
        show('library');
      }
      feedback.textContent = { save: 'Snapshot saved.', rename: 'Map renamed.', delete: 'Map deleted.' }[kind];
    } catch {
      el('dialog-error').textContent = 'This browser could not write to the map archive.';
    } finally {
      confirm.disabled = false;
    }
  });

  el('exit-comparison').addEventListener('click', () => show('library'));
  compare.addEventListener('click', () => {
    const pair = maps.filter(map => selected.has(map.id)).sort((a, b) => a.date.localeCompare(b.date));
    if (pair.length !== 2) return;
    show('compare');
    try {
      closingComparison = mountComparison(pair);
    } catch {
      show('library');
      feedback.textContent = 'Could not start the WebGL comparison. The saved maps are still available.';
    }
  });

  return {
    async ready(store) {
      archive = store;
      await refresh();
      feedback.textContent = '';
    },
    fail() { feedback.textContent = 'The browser could not open local storage. The scanner is still available.'; },
    save(map) { if (archive) edit('save', map); },
    endCompare() { closingComparison?.(); closingComparison = undefined; },
  };
}

function mountComparison([first, second]) {
  const panes = [...document.querySelectorAll('.comparison-canvas')];
  const changeToggle = el('show-changes'), reset = el('reset-comparison');
  const aligned = comparable(first, second);
  const diff = aligned ? compareReturns(first.points, second.points) : new Float32Array();
  changeToggle.checked = false;
  changeToggle.disabled = !aligned;
  el('first-map').textContent = first.name;
  el('second-map').textContent = second.name;
  const viewers = [];
  let fitPoints;
  if (!aligned && (first.sonar || second.sonar || first.lidar || second.lidar)) {
    fitPoints = new Float32Array(first.points.length + second.points.length);
    fitPoints.set(first.points);
    fitPoints.set(second.points, first.points.length);
  }
  let animation;
  function dispose() {
    cancelAnimationFrame(animation);
    viewers.forEach(viewer => viewer.dispose());
    panes.forEach(pane => pane.replaceChildren());
    reset.onclick = null;
    changeToggle.onchange = null;
  }
  try {
    for (const [i, map] of [first, second].entries()) {
      const canvas = document.createElement('canvas');
      canvas.tabIndex = 0;
      canvas.setAttribute('aria-label', `Interactive comparison: ${map.name}`);
      panes[i].replaceChildren(canvas);
      viewers[i] = createViewer(canvas, { cloud: new Float32Array(), mesh: new Float32Array() },
        (camera, view) => viewers[1 - i]?.follow(camera, view));
      viewers[i].replaceCloud(map.points);
    }
    if (aligned) viewers[1].replaceChanges(diff);
    if (fitPoints) viewers[0].frameCloud(fitPoints);
  } catch (error) {
    dispose();
    throw error;
  }
  function describe() {
    el('comparison-note').textContent = !aligned
      ? 'Alignment unknown. Change overlay requires scans in the same coordinate frame.'
      : changeToggle.checked
        ? `${format.format(diff.length / 3)} newly observed returns in cyan. Gray areas do not establish what was missed or removed.`
        : 'Earlier capture on the left. Drag either map to move both cameras.';
  }
  changeToggle.onchange = describe;
  reset.onclick = () => {
    viewers[0].preset('orbit');
    if (fitPoints) viewers[0].frameCloud(fitPoints);
  };
  describe();
  function draw() {
    for (const viewer of viewers) viewer.draw({ mode: 'points', pointSize: 10,
      pointCap: 100000, time: 0, changeOverlay: changeToggle.checked, comparison: true });
    animation = requestAnimationFrame(draw);
  }
  draw();
  return dispose;
}
