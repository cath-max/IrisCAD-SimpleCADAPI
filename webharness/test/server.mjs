// Minimal static file server for browser-testing the webharness Worker.
// Serves the webharness/ directory as web root so /src/*.mjs and
// /test/vendor/*.whl are both reachable from /test/index.html.
//
// Usage: node webharness/test/server.mjs [port]

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = Number(process.argv[2] ?? 8743);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".whl": "application/octet-stream",
  ".wasm": "application/wasm",
  ".json": "application/json",
};

const server = http.createServer((req, res) => {
  const urlPath = decodeURIComponent(req.url.split("?")[0]);
  const filePath = path.join(ROOT, urlPath);

  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404);
      res.end("Not found: " + urlPath);
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, {
      "Content-Type": MIME[ext] ?? "application/octet-stream",
      // This server only exists for iterating on local edits. Wheel filenames
      // may stay stable across local rebuilds, so cache nothing here.
      "Cache-Control": "no-store",
    });
    res.end(content);
  });
});

server.listen(PORT, () => {
  console.log(`webharness test server: http://localhost:${PORT}/test/index.html`);
});
