// Web Worker entry point. Runs Pyodide off the main thread so a long-running
// model build never blocks the UI, and hosts exactly one PyodideEngine for
// the Worker's lifetime.

import { MessageType } from "./types.mjs";
import { PyodideEngine } from "./pyodideEngine.mjs";
import { compositeGrid } from "./compositeGrid.mjs";
import { renderViews } from "./threeRenderer.mjs";

const DEFAULT_RENDER_VIEWS = ["iso", "front", "back", "top", "bottom", "left", "right"];

const engine = new PyodideEngine();
const ready = engine.init();
const assemblyBaselines = new Map();

function isAssemblySuccess(result) {
  return result?.ok === true && result.result_type === "Assembly" && result.assembly != null;
}
self.onmessage = async (event) => {
  const { id, type, data } = event.data;

  try {
    await ready;

    let result;
    switch (type) {
      case MessageType.RUN_CODE:
        result = await engine.runCode(data.code, data.sessionId ?? "default");
        if (data.artifactVersion && isAssemblySuccess(result)) {
          assemblyBaselines.set(data.sessionId ?? "default", data.artifactVersion);
        }
        break;
      case MessageType.RUN_ASSEMBLY_SECTIONS: {
        const sessionId = data.sessionId ?? "default";
        const baseline = assemblyBaselines.get(sessionId);
        if (!baseline || baseline !== data.previousArtifactVersion) {
          result = {
            ...(await engine.runCode(data.code, sessionId)),
            execution_mode: "full",
            fallback_reason: "worker_baseline_mismatch",
            executed_sections: [],
          };
        } else {
          const partial = await engine.runAssemblySections(data.code, sessionId, data.sections ?? []);
          const inspection = isAssemblySuccess(partial)
            ? await engine.inspectAssemblyRenderState(sessionId, "result")
            : null;
          if (isAssemblySuccess(partial) && inspection?.ok) {
            result = {
              ...partial,
              execution_mode: "partial",
              fallback_reason: null,
              executed_sections: data.sections ?? [],
            };
          } else {
            await engine.resetSession(sessionId);
            const fallback = await engine.runCode(data.code, sessionId);
            result = {
              ...fallback,
              execution_mode: "partial_then_full_fallback",
              fallback_reason: "partial_execution_failed",
              executed_sections: [],
            };
            if (!isAssemblySuccess(fallback)) {
              assemblyBaselines.delete(sessionId);
              await engine.resetSession(sessionId);
            }
          }
        }
        if (isAssemblySuccess(result)) {
          assemblyBaselines.set(sessionId, data.nextArtifactVersion);
        } else {
          assemblyBaselines.delete(sessionId);
        }
        break;
      }
      case MessageType.ANALYZE_ASSEMBLY_SECTIONS:
        result = await engine.analyzeAssemblySections(data.code);
        break;
      case MessageType.EXPORT_SHAPE:
        result = await engine.exportShape(
          data.sessionId ?? "default",
          data.shapeName,
          data.format,
          data.path,
        );
        break;
      case MessageType.READ_FILE:
        result = { bytes: engine.readFile(data.path) };
        break;
      case MessageType.INSPECT_ASSEMBLY_RENDER_STATE:
        result = await engine.inspectAssemblyRenderState(
          data.sessionId ?? "default",
          data.shapeName ?? "result",
          { pathPrefix: data.pathPrefix },
        );
        break;
      case MessageType.RENDER_ASSEMBLY_PART_MESHES: {
        const workerStartedAt = performance.now();
        const meshResult = await engine.renderAssemblyPartMeshes(
          data.sessionId ?? "default",
          data.shapeName ?? "result",
          data.partIds ?? [],
          {
            pathPrefix: data.pathPrefix,
            meshTolerance: data.meshTolerance,
            meshAngularTolerance: data.meshAngularTolerance,
            shading: data.shading,
          },
        );
        meshResult.timing = {
          worker_ms: performance.now() - workerStartedAt,
        };
        if (meshResult?.ok) {
          const transfers = meshResult.parts
            .map((part) => part.bytes?.buffer)
            .filter(Boolean);
          self.postMessage({ id, type, data: meshResult }, transfers);
          return;
        }
        result = meshResult;
        break;
      }
      case MessageType.RENDER_VIEWS: {
        const meshResult = await engine.renderMeshBuffers(
          data.sessionId ?? "default",
          data.shapeName,
          {
            highlightTags: data.highlightTags,
            highlightColors: data.highlightColors,
            tagLabels: data.tagLabels,
            pathPrefix: data.pathPrefix ?? "/tmp/preview_mesh",
          },
        );
        if (meshResult.ok) {
          const images = await renderViews(
            meshResult,
            data.views ?? DEFAULT_RENDER_VIEWS,
            {
              imageSize: data.imageSize ?? 512,
              showAxes: data.showAxes ?? true,
              showEdges: data.showEdges ?? true,
            },
          );
          const compositeBlob = await compositeGrid(images, { legend: meshResult.legend });
          result = {
            ok: true,
            images: images.map(({ view, bytes }) => ({ view, size: bytes.length })),
            composite: new Uint8Array(await compositeBlob.arrayBuffer()),
            error: null,
          };
        } else {
          result = { ok: false, images: [], composite: null, error: meshResult.error };
        }
        break;
      }
      case MessageType.RESET_SESSION:
        result = await engine.resetSession(data.sessionId ?? "default");
        assemblyBaselines.delete(data.sessionId ?? "default");
        break;
      case MessageType.INSPECT_GEOMETRY:
        result = await engine.inspectGeometry(
          data.sessionId ?? "default",
          data.shapeName
        );
        break;
      default:
        throw new Error(`Unknown message type: ${type}`);
    }

    self.postMessage({ id, type, data: result });
  } catch (error) {
    self.postMessage({
      id,
      type,
      data: null,
      err: { message: error && error.message ? error.message : String(error) },
    });
  }
};
self.postMessage({ type: 'ready' });
