// Static file server + API proxy for local development.
// Serves index.html and proxies /api/* and /media/* to the Python backend.
//
// Run:  node server.js
// Then: open http://localhost:4321
//
// Requires the Python backend on BACKEND (default http://localhost:8000).
// Keyless capsule-only:  .venv/bin/python -m uvicorn poc_demo.server.capsule_app:app --port 8000
// Full (with principles): doppler run -- .venv/bin/python -m cli serve --port 8000

const http = require('http');
const fs   = require('fs');
const path = require('path');

const ROOT    = __dirname;
const PORT    = process.env.PORT    || 4321;
const BACKEND = process.env.BACKEND || 'http://localhost:8000';

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'text/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.svg':  'image/svg+xml',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.json': 'application/json',
};

const backendUrl = new URL(BACKEND);

http.createServer((req, res) => {
  const urlPath = decodeURIComponent(req.url.split('?')[0]);

  // Proxy /api/* and /media/* to the Python backend.
  if (urlPath.startsWith('/api/') || urlPath.startsWith('/media/')) {
    const opts = {
      hostname: backendUrl.hostname,
      port:     Number(backendUrl.port) || 80,
      path:     req.url,
      method:   req.method,
      headers:  { ...req.headers, host: backendUrl.host },
    };
    const proxy = http.request(opts, proxyRes => {
      // Pass CORS headers through so browser is satisfied.
      const headers = { ...proxyRes.headers };
      headers['access-control-allow-origin'] = '*';
      res.writeHead(proxyRes.statusCode, headers);
      proxyRes.pipe(res, { end: true });
    });
    proxy.on('error', () => {
      res.writeHead(502, { 'content-type': 'text/plain' });
      res.end('Backend unavailable — start the Python server:\n  .venv/bin/python -m uvicorn poc_demo.server.capsule_app:app --port 8000');
    });
    req.pipe(proxy, { end: true });
    return;
  }

  // Static files.
  const file = urlPath === '/' ? '/index.html' : urlPath;
  const filePath = path.join(ROOT, file);

  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403); res.end('Forbidden'); return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    const ct = TYPES[path.extname(filePath)] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': ct });
    res.end(data);
  });
}).listen(PORT, () => {
  console.log(`recapsule  →  http://localhost:${PORT}`);
  console.log(`API proxy  →  ${BACKEND}`);
});
