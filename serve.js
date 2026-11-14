import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const mime = { html: 'text/html', css: 'text/css', js: 'text/javascript', mjs: 'text/javascript',
  svg: 'image/svg+xml', json: 'application/json' };
const acousticAssets = new Set([
  'style.css', 'app.mjs', 'audio.mjs', 'capture.mjs', 'map.mjs', 'room-view.mjs', 'recorder.js',
  'sample-map.json', 'room-map.json',
]);
const acousticPrefix = '/acoustic/';
const port = Number(process.env.PORT ?? 4173);
const server = createServer(async (req, res) => {
  const path = req.url.split('?')[0];
  if (path === '/acoustic') {
    res.writeHead(308, { Location: acousticPrefix }).end();
    return;
  }
  const acousticAsset = path.startsWith(acousticPrefix) && acousticAssets.has(path.slice(acousticPrefix.length));
  if (path !== '/' && path !== acousticPrefix && !acousticAsset &&
      !/^\/(?:src\/[a-z-]+\.js|style\.css|logo\.svg)$/.test(path)) {
    res.writeHead(404).end();
    return;
  }
  const file = path === '/' ? 'index.html' : path === acousticPrefix ? 'acoustic/index.html' : path.slice(1);
  try {
    const body = await readFile(new URL(file, import.meta.url));
    res.writeHead(200, { 'Content-Type': mime[file.split('.').at(-1)] + '; charset=utf-8',
      'Cache-Control': 'no-store' }).end(body);
  } catch (error) {
    if (error.code === 'ENOENT') {
      res.writeHead(404).end();
    } else {
      console.error('Could not serve EchoSense file', { file, error });
      res.writeHead(500).end();
    }
  }
});
server.listen(port, process.env.HOST ?? '127.0.0.1', () => {
  console.log(`EchoSense: http://127.0.0.1:${server.address().port}/`);
});
