import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const mime = { html: 'text/html', css: 'text/css', js: 'text/javascript', svg: 'image/svg+xml' };
const port = Number(process.env.PORT ?? 4173);
const server = createServer(async (req, res) => {
  const path = req.url.split('?')[0];
  if (path !== '/' && !/^\/(?:src\/[a-z-]+\.js|style\.css|logo\.svg)$/.test(path)) {
    res.writeHead(404).end();
    return;
  }
  const file = path === '/' ? 'index.html' : path.slice(1);
  try {
    const body = await readFile(new URL(file, import.meta.url));
    res.writeHead(200, { 'Content-Type': mime[file.split('.').at(-1)] + '; charset=utf-8' }).end(body);
  } catch {
    res.writeHead(404).end();
  }
});
server.listen(port, '127.0.0.1', () => {
  console.log(`EchoSense: http://127.0.0.1:${server.address().port}/`);
});
