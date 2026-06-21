// Static file server + API proxy for local development / LAN sharing.
// Serves index.html and proxies /api/* and /media/* to the Python backend.
//
// Run (LAN, passcode-gated):  PASSCODE=yourcode node server.js
//   then others on the same wifi open  http://<your-ip>:4321  and type the
//   passcode (leave the username blank). Without PASSCODE the app is open.
// Run (local only):  node server.js   →  http://localhost:4321
//
// Requires the Python backend on BACKEND (default http://localhost:8000).
// Keyless capsule-only:  .venv/bin/python -m uvicorn poc_demo.server.capsule_app:app --port 8000
// Full (with principles): doppler run -- .venv/bin/python -m cli serve --port 8000

const http  = require('http');
const https = require('https');
const fs    = require('fs');
const path  = require('path');
const os    = require('os');

const ROOT     = __dirname;
const PORT     = process.env.PORT     || 4321;
const HOST     = process.env.HOST     || '0.0.0.0';   // bind all interfaces → LAN reachable
const BACKEND  = process.env.BACKEND  || 'http://localhost:8000';
const PASSCODE = process.env.PASSCODE || '';           // set to require a passcode

// HTTPS when a cert exists — REQUIRED for the camera to work on phones over the
// LAN (browsers only allow getUserMedia on https or localhost). Generate one with:
//   openssl req -x509 -newkey rsa:2048 -nodes -keyout certs/key.pem \
//     -out certs/cert.pem -days 825 -subj "/CN=recapsule-dev" \
//     -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:<your-lan-ip>"
// Falls back to http if the cert files are absent.
const CERT_DIR  = process.env.CERT_DIR || path.join(ROOT, 'certs');
const KEY_FILE  = path.join(CERT_DIR, 'key.pem');
const CRT_FILE  = path.join(CERT_DIR, 'cert.pem');
const HAS_CERT  = fs.existsSync(KEY_FILE) && fs.existsSync(CRT_FILE);

// HTTP Basic Auth gate: the browser shows a native prompt; we only check the
// password field against PASSCODE (the username is ignored — "just a passcode").
// Returns true if the request may proceed, false if a 401 challenge was sent.
function passcodeOK(req, res) {
  if (!PASSCODE) return true;                          // no passcode configured → open
  const hdr = req.headers['authorization'] || '';
  if (hdr.startsWith('Basic ')) {
    const decoded = Buffer.from(hdr.slice(6), 'base64').toString('utf8');
    const pass = decoded.slice(decoded.indexOf(':') + 1); // user:pass → take pass
    if (pass === PASSCODE) return true;
  }
  res.writeHead(401, {
    'WWW-Authenticate': 'Basic realm="recapsule - enter the passcode", charset="UTF-8"',
    'Content-Type': 'text/plain',
  });
  res.end('Passcode required.');
  return false;
}

// Best-effort LAN IPv4 for the "open this on your phone" hint.
function lanIP() {
  for (const ifs of Object.values(os.networkInterfaces())) {
    for (const i of ifs || []) {
      if (i.family === 'IPv4' && !i.internal) return i.address;
    }
  }
  return 'localhost';
}

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

const handler = (req, res) => {
  // Gate EVERYTHING behind the passcode (page, API, media) before any work.
  if (!passcodeOK(req, res)) return;

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
};

// HTTPS when a cert exists (camera works on phones); plain http otherwise.
const scheme = HAS_CERT ? 'https' : 'http';
const server = HAS_CERT
  ? https.createServer({ key: fs.readFileSync(KEY_FILE), cert: fs.readFileSync(CRT_FILE) }, handler)
  : http.createServer(handler);

server.listen(PORT, HOST, () => {
  const ip = lanIP();
  console.log(`recapsule  →  ${scheme}://localhost:${PORT}`);
  if (HOST === '0.0.0.0' && ip !== 'localhost') {
    console.log(`on the LAN  →  ${scheme}://${ip}:${PORT}   (same wifi)`);
  }
  console.log(`API proxy  →  ${BACKEND}`);
  console.log(PASSCODE
    ? `passcode   →  REQUIRED (enter it in the browser prompt; leave username blank)`
    : `passcode   →  none (open — set PASSCODE=... to require one)`);
  console.log(HAS_CERT
    ? `camera     →  enabled (https) — accept the one-time cert warning on each device`
    : `camera     →  disabled (http) — add certs/ for https so phones can use the camera`);
});
