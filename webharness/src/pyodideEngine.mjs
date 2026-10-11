// Owns one Pyodide interpreter for the lifetime of the Worker.
//
// Unlike CADAM's OpenSCADWrapper (which spins up a fresh OpenSCAD instance
// per compile because of a bug in reusing instances), this keeps a single
// persistent Pyodide interpreter and a persistent Python-side namespace per
// session_id (see simplecadapi/webharness.py). That's an intentional
// architecture difference, not an oversight: SimpleCADAPI's own spike
// findings say Pyodide/OCP.wasm cold start is the expensive part (30-45s),
// while modeling calls themselves are millisecond-scale, so paying the
// import/setup cost once per Worker (not once per agent iteration) is the
// whole point.

import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/pyodide.mjs";

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/";

export class PyodideEngine {
  /**
   * @param {Object} [opts]
   * @param {string} [opts.ocpWheelUrl] - URL to the OCP.wasm wheel (cadquery-ocp-novtk-OCP.wasm)
   * @param {string} [opts.simplecadapiWheelUrl] - URL to the simplecadapi wheel
   */
  constructor(opts = {}) {
    this.ocpWheelUrl =
      opts.ocpWheelUrl ??
      "/test/vendor/cadquery_ocp_novtk_ocp_wasm-7.9.3.1.post202607021200-cp314-cp314-pyemscripten_2026_0_wasm32.whl";
    this.simplecadapiWheelUrl =
      opts.simplecadapiWheelUrl ?? "/test/vendor/simplecadapi-2.0.1b7-py3-none-any.whl";
    this.pyodide = null;
    this._harness = null;
  }

  async init() {
    this.pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX_URL });
    await this.pyodide.loadPackage(["micropip", "numpy"]);

    // Install order matters: the OCP.wasm wheel first (provides the real
    // `OCP` module), then a micropip mock package named "cadquery-ocp" so
    // that simplecadapi's declared dependency on `cadquery-ocp>=7.9.3.1`
    // resolves against the mock instead of micropip trying (and failing) to
    // fetch a desktop-only wheel. This is the same mechanism used by
    // yeicor/OCP.wasm's own build123d bootstrap.
    await this.pyodide.runPythonAsync(`
import importlib.metadata
import micropip

await micropip.install("${this.ocpWheelUrl}")
_ocp_wasm_version = importlib.metadata.version("cadquery-ocp-novtk-OCP.wasm")
micropip.add_mock_package("cadquery-ocp", _ocp_wasm_version)

await micropip.install("${this.simplecadapiWheelUrl}")
`);

    this._harness = this.pyodide.pyimport("simplecadapi.webharness");
  }

  /**
   * @param {string} code
   * @param {string} sessionId
   * @returns {Promise<Object>} parsed JSON, see simplecadapi.webharness.run_code
   */
  async runCode(code, sessionId) {
    const jsonStr = await this._harness.run_code(code, sessionId);
    return JSON.parse(jsonStr);
  }

  async runAssemblySections(code, sessionId, sections) {
    const jsonStr = await this._harness.run_assembly_sections(
      code,
      sessionId,
      JSON.stringify(sections),
    );
    return JSON.parse(jsonStr);
  }

  /** Analyze CADAM Assembly dependencies without executing model code. */
  async analyzeAssemblySections(code) {
    const jsonStr = await this._harness.analyze_assembly_sections(code);
    return JSON.parse(jsonStr);
  }

  /**
   * @param {string} sessionId
   * @param {string} shapeName
   * @param {"step"|"stl"} format
   * @param {string} path - path on the Pyodide virtual FS to write to
   * @returns {Promise<Object>} parsed JSON plus a `bytes` Uint8Array on success
   */
  async exportShape(sessionId, shapeName, format, path) {
    const jsonStr = await this._harness.export_shape(
      sessionId,
      shapeName,
      format,
      path,
    );
    const result = JSON.parse(jsonStr);
    if (result.ok) {
      result.bytes = this.pyodide.FS.readFile(path);
    }
    return result;
  }

  /** Read an already-created file from the Pyodide virtual filesystem. */
  readFile(path) {
    return this.pyodide.FS.readFile(path);
  }

  /**
   * Builds one flat-shaded render mesh for `shapeName` and reads back its
   * packed position/normal/color buffers as typed-array views. This does
   * not loop over camera views: tessellation is view-independent, so it
   * happens once here and the caller (a Three.js renderer) renders as many
   * views as it wants from the same buffers.
   *
   * @param {string} sessionId
   * @param {string} shapeName
   * @param {Object} [opts]
   * @param {string[]} [opts.highlightTags]
   * @param {Object<string,string>} [opts.highlightColors]
   * @param {Object<string,string>} [opts.tagLabels]
   * @param {string} [opts.pathPrefix] - Pyodide virtual FS path prefix;
   *   buffers are packed into `${pathPrefix}.bin`
   * @param {number} [opts.meshTolerance] - linear tessellation tolerance;
   *   omit to keep Python default (coarse; used by seven-view path)
   * @param {number} [opts.meshAngularTolerance] - angular tessellation tolerance;
   *   omit to keep Python default
   * @param {'flat'|'smooth'} [opts.shading] - omit for flat (seven-view);
   *   pass ``smooth`` for interactive preview vertex normals
   * @returns {Promise<Object>} parsed JSON (see simplecadapi.webharness.render_mesh)
   *   plus, on success: `bytes` (the raw Uint8Array read back from the
   *   virtual FS) and `positions`/`normals`/`colors` (Float32Array views
   *   into `bytes`, sliced per `bufferViews`' byte offsets - zero-copy).
   */
  async renderMeshBuffers(sessionId, shapeName, opts = {}) {
    // Pyodide auto-converts a JS Array argument to a Python list, but a
    // plain JS object is left as a JsProxy (which lacks dict methods like
    // .get()) unless explicitly converted - highlightColors/tagLabels are
    // dict-shaped, so they need `pyodide.toPy()` here to actually arrive as
    // Python dicts on the other side.
    const toPyDict = (value) => (value == null ? null : this.pyodide.toPy(value));
    // Always pass concrete floats/strings (never JS null) so Pyodide never
    // sees JsNull inside Python float(). Defaults match mesh_export coarse path.
    const meshTolerance =
      typeof opts.meshTolerance === "number" ? opts.meshTolerance : 0.35;
    const meshAngularTolerance =
      typeof opts.meshAngularTolerance === "number"
        ? opts.meshAngularTolerance
        : 0.22;
    const shading =
      opts.shading === "smooth" || opts.shading === "flat"
        ? opts.shading
        : "flat";
    const jsonStr = await this._harness.render_mesh(
      sessionId,
      shapeName,
      opts.highlightTags ?? null,
      toPyDict(opts.highlightColors),
      toPyDict(opts.tagLabels),
      opts.pathPrefix ?? "/tmp/preview_mesh",
      meshTolerance,
      meshAngularTolerance,
      shading,
    );
    const result = JSON.parse(jsonStr);
    if (result.ok) {
      result.bytes = this.pyodide.FS.readFile(result.path);
      for (const [name, view] of Object.entries(result.bufferViews)) {
        result[name] = new Float32Array(
          result.bytes.buffer,
          result.bytes.byteOffset + view.byteOffset,
          view.byteLength / 4,
        );
      }
    }
    return result;
  }

  /** Inspect unique Part fingerprints and independent Component Placements. */
  async inspectAssemblyRenderState(sessionId, shapeName, opts = {}) {
    const jsonStr = await this._harness.inspect_assembly_render_state(
      sessionId,
      shapeName,
      opts.pathPrefix ?? "/tmp/assembly_part_fingerprint",
    );
    return JSON.parse(jsonStr);
  }

  /** Tessellate requested unique Parts in Part-local coordinates. */
  async renderAssemblyPartMeshes(sessionId, shapeName, partIds, opts = {}) {
    const meshTolerance =
      typeof opts.meshTolerance === "number" ? opts.meshTolerance : 0.12;
    const meshAngularTolerance =
      typeof opts.meshAngularTolerance === "number"
        ? opts.meshAngularTolerance
        : 0.1;
    const shading =
      opts.shading === "smooth" || opts.shading === "flat"
        ? opts.shading
        : "smooth";
    const requestedPartIds = this.pyodide.toPy(partIds);
    let jsonStr;
    try {
      jsonStr = await this._harness.render_assembly_part_meshes(
        sessionId,
        shapeName,
        requestedPartIds,
        opts.pathPrefix ?? "/tmp/assembly_part_mesh",
        meshTolerance,
        meshAngularTolerance,
        shading,
      );
    } finally {
      requestedPartIds.destroy?.();
    }
    const result = JSON.parse(jsonStr);
    if (result.ok) {
      for (const part of result.parts) {
        part.bytes = this.pyodide.FS.readFile(part.path);
        for (const [name, view] of Object.entries(part.bufferViews)) {
          part[name] = new Float32Array(
            part.bytes.buffer,
            part.bytes.byteOffset + view.byteOffset,
            view.byteLength / 4,
          );
        }
      }
    }
    return result;
  }

  /**
   * @param {string} sessionId
   */
  async resetSession(sessionId) {
    await this._harness.reset_session(sessionId);
    return { ok: true };
  }
  async inspectGeometry(sessionId, shapeName){
    const jsonStr = await this._harness.inspect_geometry(
      sessionId,
      shapeName
    );
    const result = JSON.parse(jsonStr);
    return result;
  }
}
