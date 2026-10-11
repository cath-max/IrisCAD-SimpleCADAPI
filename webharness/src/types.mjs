// Message envelope for the main-thread <-> Worker RPC.
//
// Architecture note: this mirrors the {id, type, data}/{id, type, data, err}
// postMessage-RPC pattern used by CADAM's OpenSCAD worker
// (https://github.com/Adam-CAD/CADAM, src/worker/{types,worker}.ts) — a
// per-request id correlates a response to its caller via a pending-requests
// map on the main-thread side. The pattern is generic (not OpenSCAD-specific)
// so it's reimplemented here rather than copied; the actual engine underneath
// (Pyodide + OCP.wasm instead of OpenSCAD-wasm) and message shapes are new.

export const MessageType = Object.freeze({
  RUN_CODE: "run_code",
  RUN_ASSEMBLY_SECTIONS: "run_assembly_sections",
  ANALYZE_ASSEMBLY_SECTIONS: "analyze_assembly_sections",
  EXPORT_SHAPE: "export_shape",
  READ_FILE: "read_file",
  INSPECT_ASSEMBLY_RENDER_STATE: "inspect_assembly_render_state",
  RENDER_ASSEMBLY_PART_MESHES: "render_assembly_part_meshes",
  // Renders N named camera angles of a shape and composites them into one
  // PNG for vision-model feedback. 

  RENDER_VIEWS: "render_views",
  RESET_SESSION: "reset_session",
  INSPECT_GEOMETRY:"inspect_geometry",
  READY:"ready"
});

/**
 * @typedef {Object} WorkerRequest
 * @property {string} id
 * @property {string} type - one of MessageType
 * @property {Object} data
 */

/**
 * @typedef {Object} WorkerResponse
 * @property {string} id
 * @property {string} type
 * @property {*} data
 * @property {{message: string}} [err]
 */
