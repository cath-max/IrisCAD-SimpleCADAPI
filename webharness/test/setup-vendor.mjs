// Regenerates the browser-test wheel fixtures under test/vendor/ (gitignored
// because they're large binaries). Run this after cloning, or whenever the
// OCP.wasm build or the simplecadapi source changes.
//
// Usage:
//   node webharness/test/setup-vendor.mjs
//   node webharness/test/setup-vendor.mjs --force-ocp
//
// Step [2/2] downloads ~22MB from PyPI. If a cadquery_ocp*.whl already exists
// and looks like a real zip, the download is skipped (use --force-ocp to
// refresh). curl is invoked without -s so progress is visible.

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..");
const VENDOR_DIR = path.join(HERE, "vendor");
const OCP_WASM_PACKAGE = "cadquery-ocp-novtk-OCP.wasm";
const OCP_MIN_BYTES = 1_000_000;
const forceOcp = process.argv.includes("--force-ocp");

fs.mkdirSync(VENDOR_DIR, { recursive: true });

console.log("[1/2] Building the simplecadapi wheel (uv build --wheel)...");
execSync("uv build --wheel", { cwd: REPO_ROOT, stdio: "inherit" });

const distDir = path.join(REPO_ROOT, "dist");
const builtWheels = fs
  .readdirSync(distDir)
  .filter((f) => f.startsWith("simplecadapi-") && f.endsWith(".whl"))
  .map((f) => ({ name: f, mtime: fs.statSync(path.join(distDir, f)).mtimeMs }))
  .sort((a, b) => b.mtime - a.mtime);
const builtWheel = builtWheels[0]?.name;
if (!builtWheel) throw new Error("uv build did not produce a simplecadapi wheel");
// Drop stale package wheels so CADAM sync cannot pick an older filename.
for (const f of fs.readdirSync(VENDOR_DIR)) {
  if (f.startsWith("simplecadapi-") && f.endsWith(".whl")) {
    fs.unlinkSync(path.join(VENDOR_DIR, f));
  }
}
fs.copyFileSync(path.join(distDir, builtWheel), path.join(VENDOR_DIR, builtWheel));
console.log(`  -> ${builtWheel}`);

function existingOcpWheel() {
  const names = fs
    .readdirSync(VENDOR_DIR)
    .filter((f) => f.startsWith("cadquery_ocp") && f.endsWith(".whl"));
  for (const name of names) {
    const full = path.join(VENDOR_DIR, name);
    const size = fs.statSync(full).size;
    if (size < OCP_MIN_BYTES) continue;
    const fd = fs.openSync(full, "r");
    const buf = Buffer.alloc(2);
    fs.readSync(fd, buf, 0, 2, 0);
    fs.closeSync(fd);
    if (buf[0] === 0x50 && buf[1] === 0x4b) return { name, size };
  }
  return null;
}

const cached = forceOcp ? null : existingOcpWheel();
if (cached) {
  console.log(
    `[2/2] Reusing existing OCP.wasm wheel ${cached.name} (${cached.size} bytes). ` +
      "Pass --force-ocp to download again from PyPI.",
  );
} else {
  console.log(`[2/2] Fetching the latest ${OCP_WASM_PACKAGE} wheel from PyPI...`);
  console.log("      (this is ~22MB; if it sits idle, Ctrl+C and re-run without --force-ocp if a wheel already exists)");
  const pkgJson = await fetch(`https://pypi.org/pypi/${OCP_WASM_PACKAGE}/json`).then((r) =>
    r.json(),
  );
  const latestVersion = pkgJson.info.version;
  const release = pkgJson.releases[latestVersion].find((f) =>
    f.filename.endsWith(".whl"),
  );
  if (!release) throw new Error(`No wasm32 wheel found for ${OCP_WASM_PACKAGE}==${latestVersion}`);

  const wheelPath = path.join(VENDOR_DIR, release.filename);
  // No -s: progress meter so this does not look hung. -L follows redirects.
  execSync(`curl -L --progress-bar -o "${wheelPath}" "${release.url}"`, {
    stdio: "inherit",
  });
  console.log(`  -> ${release.filename}`);
}

console.log("\nDone. Update the default filenames in src/pyodideEngine.mjs if the OCP.wasm version changed.");
