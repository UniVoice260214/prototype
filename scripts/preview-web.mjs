import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';

const port = Number(process.env.WEB_PREVIEW_PORT || 4173);
const root = join(process.cwd(), 'public');
const vendorRoot = join(
  process.cwd(),
  'node_modules',
  'livekit-client',
  'dist',
);
const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', `http://${request.headers.host}`);
  const vendor = url.pathname.startsWith('/vendor/livekit/');
  const relativePath = vendor
    ? url.pathname.slice('/vendor/livekit/'.length)
    : url.pathname === '/' ||
        url.pathname === '/join' ||
        url.pathname === '/student' ||
        url.pathname === '/professor'
      ? 'index.html'
      : url.pathname.slice(1);
  const base = vendor ? vendorRoot : root;
  const filePath = normalize(join(base, relativePath));

  if (!filePath.startsWith(base)) {
    response.writeHead(403).end('Forbidden');
    return;
  }

  try {
    const file = await stat(filePath);
    if (!file.isFile()) throw new Error('Not a file');
    response.writeHead(200, {
      'Content-Type':
        contentTypes[extname(filePath)] ?? 'application/octet-stream',
    });
    createReadStream(filePath).pipe(response);
  } catch {
    response.writeHead(404).end('Not found');
  }
}).listen(port, () => {
  console.log(`UniVoice web preview: http://localhost:${port}`);
});
