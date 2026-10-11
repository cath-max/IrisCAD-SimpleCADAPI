# MVP Agent Contract

This document freezes the **minimum viable** Text→CAD Agent contract for the CADAM + SimpleCADAPI / webharness path.  
It is the shared agreement for prompts, client tool execution, and export.  
It does **not** replace the longer formal checklist; that remains for the full product plan.

**Status:** frozen for MVP  
**Runtime:** Pyodide executes SimpleCADAPI Python; geometry is computed by **OCP.wasm** (not OpenSCAD WASM)

---

## 1. Scope of this MVP

**In scope**

- User sends a natural-language request in CADAM chat
- Optional user **reference image** upload (jpeg/png/webp) on vision-capable
  parametric models; images persist as message `file` parts and are rehydrated
  into every model turn (including tool-loop retries)
- When reference images are present: a vision model (Gemini) produces a
  short headed **plain-text feature summary** (not JSON) injected into the
  system prompt; the user-selected codegen model receives **both** that
  summary and the original images (dual-channel). The summary's **Overall**
  and **Features** sections (shape description only — no build steps) are
  folded into API-retrieval query text with the user text (so vague “make
  the model in the image” turns still retrieve relevant APIs).
  Seven-view review still treats the reference image(s) as the true visual
  target.
- Model returns SimpleCADAPI Python via `build_parametric_model`
- Browser runs `run_code` on that Python
- Failures return structured `ErrorGuidance` into the next model turn
- Success exports `result` as STEP and/or STL
- Parameter sliders for top-level numeric/bool/string **literal** assignments
  (optional `# [min:max]` / `# [min:step:max]` range comments); edits rewrite
  the Python source and re-run the full script via `run_code`, then refresh
  mesh / STEP / STL

**Out of scope (for now)**

- Treating `Assembly` as the final exportable / renderable result
- Expression-graph / `scad.var` dirty rebuild without full script re-exec
- Perfect interactive 3D preview swap
- Cold-start Service Worker optimization
- Automatic image-similarity / feature-matching APIs (no algorithmic
  reference-vs-seven-view matcher; the vision model compares in-context)

**Optional (retrieval)**

- The retrieval sidecar may inject a relevance-ordered Top-20 API-document
  slice into the CADAM parametric prompt; the core APIs are always retained.
  It uses hybrid retrieval when embeddings are available, otherwise BM25.
- It may add directly related companion APIs (for example, a sweep path) with
  local deterministic logic. `hit_ids` and `reasons` are positionally aligned;
  `related:...` denotes such a companion API. No extra LLM round is used.
- `API_RETRIEVAL_MODE=full_index` keeps CADAM's legacy full-index path.

---

## 2. Code contract (mandatory)

Every successful `build_parametric_model` `code` string MUST satisfy all of the following:

1. **Import**
   - The script starts with exactly:
   - `import simplecadapi as scad`

2. **Final variable name**
   - The final model is assigned to a top-level variable named **`result`**
   - Example: `result = scad.union_rsolid(...)`

3. **Final type**
   - `result` MUST be a `scad.Solid` or `scad.Compound`
   - After `run_code`, the returned `shapes` list MUST include `"result"`

4. **No Assembly as final result**
   - The script MUST NOT leave the export/render target as an `Assembly`
   - Intermediate `Assembly` usage is out of MVP scope; if multi-body visualization is needed, return a `Compound` as `result`

5. **Self-contained script**
   - Complete Python source, no Markdown fences
   - Rebuild the full model every revision; do not rely on variables from a previous tool call’s namespace unless the client explicitly preserves the same session and the prompt allows it  
   - MVP client policy: prefer a fresh complete script each revision; call `reset_session` (or a new `sessionId`) on new conversations

6. **No in-script export / I/O**
   - Do not call `export_step()` / `export_stl()` inside generated code
   - Do not access the network, spawn subprocesses, or write files for delivery
   - Browser harness performs `export_shape(sessionId, "result", format, path)`

7. **Units**
   - Millimeters unless the user explicitly requests another unit

---

## 3. Tool protocol (MVP)

| Item | Contract |
|------|----------|
| Tool name | Keep `build_parametric_model` and `answer_user` |
| Input fields | `title`, `version`, `code` (required). Optional `planned_changes`: 1–3 short sentences when resubmitting after a **successful** build to revise geometry (omit on the first build and on ErrorGuidance-only compile fixes). |
| Execution | `run_code(code, sessionId)` via webharness Worker |
| Success shape handle | Always `"result"` |
| Failure payload | Forward webharness `error` (`ErrorGuidance` dict) into the model context; do not collapse to a vague “Compilation failed” only |
| Visual feedback | After success, attach a seven-view inspection PNG (ISO/FRONT/BACK/LEFT/RIGHT/TOP/BOTTOM) via storage path `preview-{toolCallId}` (same as chat thumbnail / usePreview) so the model reviews geometry before revising. When user reference image(s) are in the conversation, seven-view review MUST also compare silhouette / major parts / proportions / orientation to those images. |
| Intent self-check | After seven-view review, silently check **code ↔ user text only** (named features / sizes / constraints present; no omissions or unrelated extras). Do not re-run seven-view or photo-likeness criteria in this step. `answer_user` only when both seven views (incl. reference-image match when applicable) and this check pass |
| Export | `export_shape(..., shapeName="result", format="step" \| "stl")` |

### 3.1 Client build approval & revision guidance (CADAM)

Optional per-user profile flag `agent_require_build_approval` (Settings:
“Confirm revisions after a successful build”):

| Situation | Behavior when flag is **on** |
| --------- | ---------------------------- |
| First `build_parametric_model` after a user message | Auto-run (no Continue) |
| Rebuild after a **failed** compile / contract error | Auto-run (ErrorGuidance loop; no Continue) |
| Rebuild after a **successful** compile (shape revision) | Pause for **Continue**. UI may show `planned_changes`. Optional guidance textarea. |
| Flag **off** | All builds auto-run (legacy loop) |

**Continue with empty guidance:** approve and execute the pending tool input
as-is (worker `run_code`).

**Continue with non-empty guidance:** do **not** run the pending script.
Resolve the tool call with a structured skip output (prefix
`User declined to run this revision and provided build guidance.`) that
embeds the user note, then auto-continue so the model rewrites a complete
script. Do not leave a dangling `input-available` tool part.

Chat seven-view thumbnails (`agent_show_seven_view`) are UI-only; they must
**not** disable model-side seven-view attachment via `toModelOutput`.

Constants for implementers:

```text
REQUIRED_IMPORT = "import simplecadapi as scad"
RESULT_SHAPE_NAME = "result"
ALLOWED_RESULT_TYPES = Solid | Compound
```

---

## 4. Client checks (when Worker is wired)

On each successful `run_code`:

1. `ok === true`
2. `"result" in shapes`
3. Export / render / inspect use `shapeName = "result"` only

If `ok === true` but `"result"` is missing:

- Treat as a **contract failure** (not a kernel crash)
- Return a tool error telling the model to assign the final Solid/Compound to `result` and resubmit a complete script

---

## 5. Prompt alignment

System prompt and tool descriptions MUST restate:

- `import simplecadapi as scad`
- final variable `result`
- `Solid` / `Compound` only
- no `Assembly` as final `result`
- execution is Pyodide + **OCP.wasm**, not OpenSCAD WASM
- review order: compile → seven-view review (vs text request; vs user reference
  images when present) → **intent self-check (code ↔ user text only)** → `answer_user`
- intent self-check excludes seven-view / visual / aesthetics / photo-likeness
  criteria (those belong only to the prior seven-view step)
- when reference images are present: first build uses them as visual ground
  truth together with an optional vision feature-summary system block
  (dual-channel); text sizes/constraints still win on conflict; seven-view
  review compares to the reference image(s) as the true visual target (do
  not divert review attention to the summary)
- when resubmitting after a successful build to revise geometry, include
  optional tool field `planned_changes` (1–3 short sentences); omit on the
  first build and on ErrorGuidance-only compile fixes
- CADAM may pause success→rebuild turns for Continue + optional user
  guidance per §3.1 when `agent_require_build_approval` is on

Style examples in the prompt MUST be valid SimpleCADAPI Python that ends with `result = ...`.

API reference material is optional context: either a per-turn retrieved slice
from `docs/api` (sidecar) or CADAM's bundled `simplecadapi-agent-api-index.md`
(`API_RETRIEVAL_MODE=full_index`).  
Restart the sidecar after updating its code, catalog, or embeddings.
**This contract overrides** conflicting historical docs that discuss Assembly-as-product surfaces for the MVP agent path.

---

## 6. Non-goals that must not weaken this contract

- Do not rename the tool field from `code` to `pythonCode` in MVP (avoid DB / UI churn)
- Do not require OpenSCAD Customizer comments
- Do not invent mesh-import APIs for attached STLs in MVP
- Do not use OpenSCAD WASM as a fallback executor for SimpleCADAPI code
- Do not add automatic image-matching / embedding-diff tools for reference
  images in MVP (multimodal in-context comparison only)

---

## 7. Acceptance for “contract frozen”

- [x] This file exists and states the four core rules (import / `result` / Solid|Compound / no Assembly result)
- [x] CADAM parametric system prompt matches this file (`CADAM/src/server/aiChat.ts`)
- [x] CADAM `build_parametric_model` tool description matches this file (`CADAM/shared/chatAi.ts`)
- [x] When `run_code` is wired: client rejects success without `result` (`CADAM/src/components/chat/ChatSession.tsx` + `simpleCadToolWorker.ts`)
- [x] When export is wired: download always targets `result` (STEP on demand + STL after success)
- [x] User reference images: upload + per-turn rehydration + dual-channel
  vision feature summary (Gemini) + prompt/tool rules to compare seven
  views to reference images when present (`TextAreaChat` / `aiChat.ts` /
  `visionFeatureSummary.ts` / `chatAi.ts` / `ChatSession.tsx`)
- [x] Optional build approval: success→rebuild Continue + optional guidance;
  `planned_changes` on revision builds; first/fail builds auto-run
  (CADAM `SettingsView` / `ChatSession` / `MessageBubble` / `chatAi.ts`)

Mirror copy for the CADAM tree: `CADAM/docs/MVP_AGENT_CONTRACT.md` (keep in sync).
