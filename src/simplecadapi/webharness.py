"""JS <-> Pyodide execution harness for the browser agent.

Executes LLM-generated SimpleCADAPI code against a persistent namespace
inside a single Pyodide worker, capturing stdout/stderr and normalizing
failures into the same ErrorGuidance shape SimpleCADError already exposes
(see errors.py), so the JS side can hand structured repair guidance back to
the LLM instead of a raw traceback.

Kept separate from kernel/ (which only isolates raw OCP calls) because this
is an application-layer concern: the exec sandbox and the JSON wire format,
not OCP compatibility.

Called from JS as, e.g.:
    pyodide.pyimport("simplecadapi.webharness").run_code(code, session_id)
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import time
import traceback
from typing import Any, Dict, Optional, Sequence

import simplecadapi as scad

from . import mesh_export
from .errors import SimpleCADError
from .kernel.ocp_properties import bounding_box
from .kernel.ocp_transforms import place_shape_ocp
_SHAPE_TYPES = (
    scad.Vertex,
    scad.Edge,
    scad.Wire,
    scad.Face,
    scad.Solid,
    scad.Compound,
    scad.Assembly,
)

_sessions: Dict[str, Dict[str, Any]] = {}

_SECTION_KINDS = (
    "parameters",
    "helper",
    "part",
    "assembly_setup",
    "component",
    "assembly_result",
)
_SECTION_RANK = {kind: index for index, kind in enumerate(_SECTION_KINDS)}


def _section_analysis_error(reason: str, detail: str) -> str:
    return json.dumps({"ok": False, "sections": [], "error": {"reason": reason, "detail": detail}}, ensure_ascii=False)


def _parse_assembly_sections(code: str) -> tuple[Optional[list[Dict[str, Any]]], Optional[str]]:
    """Parse CADAM's single-marker layout without executing any source."""
    lines = code.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "import simplecadapi as scad":
        return None, "Assembly source must start with `import simplecadapi as scad`."
    sections: list[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    last_rank = -1
    marker = re.compile(r"^#\s*cadam:([a-z_]+)(?:\s+([a-z][a-z0-9_]*))?\s*$")
    for index, line in enumerate(lines):
        match = marker.match(line)
        if match:
            if current is not None:
                current["source"] = "\n".join(current.pop("body"))
                sections.append(current)
            kind, explicit_id = match.groups()
            if kind not in _SECTION_RANK:
                return None, f"Line {index + 1}: unsupported Assembly section kind `{kind}`."
            implicit_id = kind if kind in {"parameters", "assembly_setup", "assembly_result"} else None
            if (implicit_id and explicit_id) or (not implicit_id and not explicit_id):
                return None, f"Line {index + 1}: invalid ID for {kind}."
            if _SECTION_RANK[kind] < last_rank:
                return None, f"Line {index + 1}: {kind} sections must appear after earlier section kinds."
            last_rank = _SECTION_RANK[kind]
            current = {"kind": kind, "id": explicit_id or implicit_id, "body": []}
            continue
        if current is not None:
            current["body"].append(line)
        elif index > 0 and line.strip() and not line.strip().startswith("#"):
            return None, f"Line {index + 1}: executable code must be inside a CADAM Assembly section."
    if current is not None:
        current["source"] = "\n".join(current.pop("body"))
        sections.append(current)
    required = {"parameters": 1, "assembly_setup": 1, "assembly_result": 1}
    for kind, count in required.items():
        if sum(section["kind"] == kind for section in sections) != count:
            return None, f"Assembly source requires exactly one {kind} section."
    if not any(section["kind"] == "part" for section in sections):
        return None, "Assembly source requires at least one part section."
    if not any(section["kind"] == "component" for section in sections):
        return None, "Assembly source requires at least one component section."
    seen = set()
    for section in sections:
        key = (section["kind"], section["id"])
        if key in seen:
            return None, f"Duplicate Assembly section `{key[0]}/{key[1]}`."
        seen.add(key)
    return sections, None


class _SectionNameAnalyzer(ast.NodeVisitor):
    """Conservative name collector for one top-level CADAM section."""

    def __init__(self) -> None:
        self.reads: set[str] = set()
        self.writes: set[str] = set()
        self.unsafe: set[str] = set()
        self._local_scopes: list[set[str]] = []

    def _store_names(self, node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, (ast.Tuple, ast.List)):
            return set().union(*(self._store_names(item) for item in node.elts))
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            self.unsafe.add("ambiguous_in_place_mutation")
        return set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            if (
                (not self._local_scopes and node.id not in self.writes)
                or (self._local_scopes and node.id not in self._local_scopes[-1])
            ):
                self.reads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            if self._local_scopes:
                self._local_scopes[-1].add(node.id)
            else:
                self.writes.add(node.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            names = self._store_names(target)
            if self._local_scopes:
                self._local_scopes[-1].update(names)
            else:
                self.writes.update(names)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        names = self._store_names(node.target)
        if self._local_scopes:
            self._local_scopes[-1].update(names)
        else:
            self.writes.update(names)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        names = self._store_names(node.target)
        if names:
            self.reads.update(names)
            if self._local_scopes:
                self._local_scopes[-1].update(names)
            else:
                self.writes.update(names)

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        names = self._store_names(node.target)
        if self._local_scopes:
            self._local_scopes[-1].update(names)
        else:
            self.writes.update(names)
        for item in node.body + node.orelse:
            self.visit(item)

    def _visit_comprehension(self, node: ast.AST, generators: Sequence[ast.comprehension], values: Sequence[ast.AST]) -> None:
        locals_ = set().union(*(self._store_names(generator.target) for generator in generators))
        self._local_scopes.append(locals_)
        for generator in generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self._local_scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, node.generators, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, node.generators, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, node.generators, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, node.generators, [node.key, node.value])

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.writes.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.writes.add(alias.asname or alias.name)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "globals", "locals", "__import__"}:
            self.unsafe.add(
                "globals_or_locals"
                if node.func.id in {"globals", "locals"}
                else "dynamic_import"
                if node.func.id == "__import__"
                else node.func.id
            )
        if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            self.unsafe.add("dynamic_import")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.writes.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        locals_ = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
        if node.args.vararg:
            locals_.add(node.args.vararg.arg)
        if node.args.kwarg:
            locals_.add(node.args.kwarg.arg)
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.For)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    locals_.update(self._store_names(target))
        self._local_scopes.append(locals_)
        for item in node.body:
            self.visit(item)
        self._local_scopes.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.unsafe.add("unknown_dynamic_reference")
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_Global(self, node: ast.Global) -> None:
        self.unsafe.add("unknown_dynamic_reference")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.unsafe.add("unknown_dynamic_reference")


def analyze_assembly_sections(code: str) -> str:
    """Analyze Assembly section dependencies without executing Python source."""
    sections, layout_error = _parse_assembly_sections(code)
    if layout_error:
        return _section_analysis_error("layout_invalid", layout_error)
    assert sections is not None
    analyzed = []
    try:
        for section in sections:
            tree = ast.parse(section["source"], mode="exec")
            analyzer = _SectionNameAnalyzer()
            analyzer.visit(tree)
            analyzed.append({
                "section": {"kind": section["kind"], "id": section["id"]},
                "reads": sorted(analyzer.reads),
                "writes": sorted(analyzer.writes),
                "unsafe_syntax": sorted(analyzer.unsafe),
            })
    except SyntaxError as exc:
        return _section_analysis_error("unsupported_python", f"SyntaxError: {exc.msg}")
    return json.dumps({"ok": True, "sections": analyzed, "error": None}, ensure_ascii=False)


def _assembly_section_snippet(code: str, sections_json: str) -> str:
    """Build an executable snippet only from validated CADAM section identities."""
    sections, layout_error = _parse_assembly_sections(code)
    if layout_error:
        raise ValueError(layout_error)
    assert sections is not None
    try:
        requested = json.loads(sections_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("sections must be a JSON array of section identities") from exc
    if not isinstance(requested, list) or not requested:
        raise ValueError("sections must be a non-empty JSON array")
    keys = []
    for item in requested:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or not isinstance(item.get("id"), str):
            raise ValueError("each requested section must contain string kind and id")
        keys.append((item["kind"], item["id"]))
    if len(set(keys)) != len(keys):
        raise ValueError("requested sections must not contain duplicates")
    layout_keys = [(section["kind"], section["id"]) for section in sections]
    if any(key not in layout_keys for key in keys):
        raise ValueError("requested section is not present in the Assembly source")
    if keys[0] != ("parameters", "parameters"):
        raise ValueError("partial execution must begin with parameters/parameters")
    tail_start = next(index for index, section in enumerate(sections) if section["kind"] == "assembly_setup")
    tail_keys = layout_keys[tail_start:]
    requested_tail = [key for key in keys if key in tail_keys]
    if requested_tail and requested_tail != tail_keys:
        raise ValueError("partial execution must include the complete Assembly tail")
    expected = [layout_keys[0]]
    expected.extend(key for key in layout_keys[1:tail_start] if key in keys)
    if requested_tail:
        expected.extend(tail_keys)
    if keys != expected:
        raise ValueError("requested sections must follow source order and contain only helpers, Parts, and an optional full Assembly tail")
    by_key = {key: section for key, section in zip(layout_keys, sections)}
    return "import simplecadapi as scad\n" + "\n\n".join(by_key[key]["source"] for key in keys)


def run_assembly_sections(code: str, session_id: str, sections_json: str) -> str:
    """Execute a validated Assembly section subset; never accept raw snippets."""
    try:
        snippet = _assembly_section_snippet(code, sections_json)
    except BaseException as exc:  # noqa: BLE001 - browser harness boundary
        return json.dumps({
            "ok": False, "stdout": "", "stderr": "", "error": _error_payload(exc),
            "shapes": [], "result_type": None, "assembly": None,
        }, ensure_ascii=False)
    return run_code(snippet, session_id)


def _optional_float(value: Any) -> Optional[float]:
    """Coerce an optional float; treat JS null/undefined proxies as None.

    Pyodide maps JS ``null`` to a JsNull proxy that is *not* Python ``None``,
    so ``is not None`` checks are not enough before ``float(...)``.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_shading(value: Any) -> str:
    """Normalize shading mode; unknown / JsNull → ``flat``."""
    if value is None:
        return "flat"
    try:
        mode = str(value).strip().lower()
    except (TypeError, ValueError):
        return "flat"
    if mode in ("flat", "smooth"):
        return mode
    return "flat"


def _namespace(session_id: str) -> Dict[str, Any]:
    ns = _sessions.get(session_id)
    if ns is None:
        ns = {"scad": scad}
        _sessions[session_id] = ns
    return ns


def reset_session(session_id: str) -> None:
    """Drop a session's namespace, e.g. when the user starts a new model."""
    _sessions.pop(session_id, None)


def _error_payload(exc: BaseException) -> Dict[str, Any]:
    if isinstance(exc, SimpleCADError):
        return exc.to_dict()
    return {
        "operation": None,
        "what_happened": f"{type(exc).__name__}: {exc}",
        "possible_causes": [],
        "how_to_fix": [],
        "technical_details": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )[-4000:],
        "signature": None,
        "documentation_hint": None,
    }


def _result_type(value: Any) -> Optional[str]:
    """Return the CADAM contract type for a top-level result value."""
    if isinstance(value, scad.Solid):
        return "Solid"
    if isinstance(value, scad.Compound):
        return "Compound"
    if isinstance(value, scad.Assembly):
        return "Assembly"
    return None


def _assembly_structure(value: Any) -> Optional[Dict[str, Any]]:
    """Return a JSON-safe, read-only Assembly structure snapshot for CADAM."""
    if not isinstance(value, scad.Assembly):
        return None
    components = []
    bom_by_part_id: Dict[str, Dict[str, Any]] = {}
    for component in value.components:
        item = component.item
        is_part = isinstance(item, scad.Part)
        components.append(
            {
                "component_id": component.component_id,
                "component_name": component.name,
                "item_kind": "part" if is_part else "assembly",
                "part_id": item.part_id if is_part else None,
                "part_name": item.name if is_part else None,
                "placement": component.placement.to_dict(),
            }
        )
        if is_part:
            line = bom_by_part_id.setdefault(
                item.part_id,
                {"part_id": item.part_id, "part_name": item.name, "quantity": 0},
            )
            line["quantity"] += 1
    return {
        "assembly_id": value.assembly_id,
        "name": value.name,
        "components": components,
        "bom": list(bom_by_part_id.values()),
    }


def _direct_assembly_parts(assembly: scad.Assembly) -> Dict[str, scad.Part]:
    """Return unique direct Parts and reject ambiguous runtime mappings."""
    parts: Dict[str, scad.Part] = {}
    for component in assembly.components:
        if not isinstance(component.item, scad.Part):
            raise TypeError("Assembly incremental preview requires direct Part components")
        part = component.item
        existing = parts.get(part.part_id)
        if existing is not None and existing is not part:
            raise ValueError(
                f"part_id {part.part_id!r} maps to multiple Part objects"
            )
        parts.setdefault(part.part_id, part)
    return parts


def inspect_assembly_render_state(
    session_id: str,
    shape_name: str,
) -> str:
    """Return unique Part IDs and independent Component Placements."""
    ns = _namespace(session_id)
    result: Dict[str, Any] = {
        "ok": True,
        "parts": [],
        "components": [],
        "error": None,
    }
    try:
        if shape_name not in ns:
            raise KeyError(f"No shape named {shape_name!r} in session {session_id!r}")
        assembly = ns[shape_name]
        if not isinstance(assembly, scad.Assembly):
            raise TypeError(f"{shape_name!r} is not an Assembly")

        parts = _direct_assembly_parts(assembly)
        result["parts"] = [
            {"part_id": part.part_id, "part_name": part.name}
            for part in parts.values()
        ]
        result["components"] = [
            {
                "component_id": component.component_id,
                "part_id": component.item.part_id,
                "placement": component.placement.to_dict(),
            }
            for component in assembly.components
        ]
    except BaseException as exc:  # noqa: BLE001 - browser harness boundary
        result["ok"] = False
        result["parts"] = []
        result["components"] = []
        result["error"] = _error_payload(exc)
    return json.dumps(result, ensure_ascii=False)


def run_code(code: str, session_id: str = "default") -> str:
    """Execute code against session_id's persistent namespace.

    Returns a JSON string shaped like:
        {
          "ok": bool,
          "stdout": str,
          "stderr": str,
          "error": <ErrorGuidance dict, see errors.SimpleCADError.to_dict()> | None,
          "shapes": [names of Vertex/Edge/Wire/Face/Solid/Compound/Assembly variables],
          "result_type": "Solid" | "Compound" | "Assembly" | null,
          "assembly": {Assembly structure snapshot} | null,
        }

    The namespace persists across calls (keyed by session_id) so multi-turn
    agent iterations don't re-pay import/setup cost, and later calls can
    reference shapes an earlier call created by variable name.
    """
    ns = _namespace(session_id)
    stdout = io.StringIO()
    stderr = io.StringIO()
    result: Dict[str, Any] = {
        "ok": True,
        "stdout": "",
        "stderr": "",
        "error": None,
        "shapes": [],
        "result_type": None,
        "assembly": None,
    }

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(code, "<agent>", "exec"), ns)
    except BaseException as exc:  # noqa: BLE001 - must surface to the LLM, never crash the worker
        result["ok"] = False
        result["error"] = _error_payload(exc)
    finally:
        result["stdout"] = stdout.getvalue()
        result["stderr"] = stderr.getvalue()

    result["shapes"] = [
        name
        for name, value in ns.items()
        if not name.startswith("_") and isinstance(value, _SHAPE_TYPES)
    ]
    result["result_type"] = _result_type(ns.get("result"))
    result["assembly"] = _assembly_structure(ns.get("result"))
    return json.dumps(result, ensure_ascii=False)


def export_shape(session_id: str, shape_name: str, fmt: str, path: str) -> str:
    """Export a named shape from session_id's namespace to path on the
    Pyodide virtual FS (JS then reads the bytes back via pyodide.FS.readFile).

    fmt is "step" or "stl". Returns a JSON string:
        {"ok": bool, "path": str, "size": int, "error": {...} | None}
    """
    ns = _namespace(session_id)
    result: Dict[str, Any] = {"ok": True, "path": path, "size": 0, "error": None}
    try:
        if shape_name not in ns:
            raise KeyError(f"No shape named {shape_name!r} in session {session_id!r}")
        shape = ns[shape_name]
        if isinstance(shape, scad.Assembly):
            if fmt != "step":
                raise ValueError("Assembly export supports STEP only; STL cannot preserve component structure")
            scad.export_assembly_step(shape, path)
        elif fmt == "step":
            scad.export_step(shape, path)
        elif fmt == "stl":
            scad.export_stl(shape, path)
        else:
            raise ValueError(f"Unsupported export format: {fmt!r}")
        result["size"] = os.path.getsize(path)
    except BaseException as exc:  # noqa: BLE001 - same rationale as run_code
        result["ok"] = False
        result["error"] = _error_payload(exc)
    return json.dumps(result, ensure_ascii=False)


def render_mesh(
    session_id: str,
    shape_name: str,
    highlight_tags: Optional[Sequence[str]] = None,
    highlight_colors: Optional[Dict[str, str]] = None,
    tag_labels: Optional[Dict[str, str]] = None,
    path_prefix: str = "/tmp/preview_mesh",
    mesh_tolerance: Optional[float] = None,
    mesh_angular_tolerance: Optional[float] = None,
    shading: Optional[str] = None,
) -> str:
    """Build one render mesh for shape_name, for the Three.js (WebGL)
    renderer on the JS side to render from any camera angles it wants, as
    tessellating a shape doesn't depend on which angle it's viewed from,
    so it happens exactly once here.

    ``shading`` is ``\"flat\"`` (default) or ``\"smooth\"``. Seven-view
    inspection should omit it (flat). Interactive preview should pass
    ``\"smooth\"``.

    positions/normals/colors (each float32, 3 components per row, one
    row per triangle corner - no shared/indexed vertices, see
    mesh_export.RenderMesh) are packed into a single binary blob written to
    {path_prefix}.bin on the Pyodide virtual FS, back-to-back in that
    order. The JS side reads the whole blob once via pyodide.FS.readFile
    and slices out zero-copy typed-array views using bufferViews' byte
    offsets.

    Returns a JSON string:
        {
          "ok": bool,
          "path": str,
          "byteLength": int,
          "vertexCount": int,
          "triangleCount": int,
          "bufferViews": {
            "positions": {"byteOffset": int, "byteLength": int, "dtype": "float32", "itemSize": 3},
            "normals":   {"byteOffset": int, "byteLength": int, "dtype": "float32", "itemSize": 3},
            "colors":    {"byteOffset": int, "byteLength": int, "dtype": "float32", "itemSize": 3}
          },
          "bounds": {"min": [x,y,z], "max": [x,y,z]},
          "legend": [{"tag": str, "label": str, "color": [r,g,b]}, ...],
          "error": {...} | None
        }
    """
    ns = _namespace(session_id)
    path = f"{path_prefix}.bin"
    result: Dict[str, Any] = {
        "ok": True,
        "path": path,
        "byteLength": 0,
        "vertexCount": 0,
        "triangleCount": 0,
        "bufferViews": {},
        "bounds": None,
        "legend": [],
        "error": None,
    }
    try:
        if shape_name not in ns:
            raise KeyError(f"No shape named {shape_name!r} in session {session_id!r}")
        shape = ns[shape_name]
        if isinstance(shape, scad.Assembly):
            shape = scad.make_compound_from_assembly_rcompound(shape)
        mesh_kwargs: Dict[str, Any] = {
            "highlight_tags": highlight_tags,
            "highlight_colors": highlight_colors,
            "tag_labels": tag_labels,
            "shading": _optional_shading(shading),
        }
        tol = _optional_float(mesh_tolerance)
        ang = _optional_float(mesh_angular_tolerance)
        if tol is not None:
            mesh_kwargs["mesh_tolerance"] = tol
        if ang is not None:
            mesh_kwargs["mesh_angular_tolerance"] = ang
        mesh = mesh_export.build_render_mesh(shape, **mesh_kwargs)

        positions_bytes = mesh.positions.tobytes()
        normals_bytes = mesh.normals.tobytes()
        colors_bytes = mesh.colors.tobytes()
        with open(path, "wb") as f:
            f.write(positions_bytes)
            f.write(normals_bytes)
            f.write(colors_bytes)

        positions_len = len(positions_bytes)
        normals_len = len(normals_bytes)
        colors_len = len(colors_bytes)
        result["byteLength"] = positions_len + normals_len + colors_len
        result["vertexCount"] = int(mesh.positions.shape[0])
        result["triangleCount"] = mesh.triangle_count
        result["bufferViews"] = {
            "positions": {"byteOffset": 0, "byteLength": positions_len, "dtype": "float32", "itemSize": 3},
            "normals": {"byteOffset": positions_len, "byteLength": normals_len, "dtype": "float32", "itemSize": 3},
            "colors": {
                "byteOffset": positions_len + normals_len,
                "byteLength": colors_len,
                "dtype": "float32",
                "itemSize": 3,
            },
        }
        result["bounds"] = {"min": list(mesh.bounds_min), "max": list(mesh.bounds_max)}
        result["legend"] = [dict(entry) for entry in mesh.legend]
    except BaseException as exc:  # noqa: BLE001 - same rationale as run_code
        result["ok"] = False
        result["error"] = _error_payload(exc)
    return json.dumps(result, ensure_ascii=False)


def render_assembly_component_meshes(
    session_id: str,
    shape_name: str,
    path_prefix: str = "/tmp/assembly_component_mesh",
    mesh_tolerance: Optional[float] = None,
    mesh_angular_tolerance: Optional[float] = None,
    shading: Optional[str] = None,
) -> str:
    """Tessellate each direct Assembly Part instance into its own mesh file.

    This browser-preview helper preserves ``component_id`` boundaries. It is
    intentionally separate from ``render_mesh``: the latter still projects an
    Assembly to a Compound for one-piece and seven-view rendering.
    """
    ns = _namespace(session_id)
    result: Dict[str, Any] = {"ok": True, "components": [], "error": None}
    try:
        if shape_name not in ns:
            raise KeyError(f"No shape named {shape_name!r} in session {session_id!r}")
        assembly = ns[shape_name]
        if not isinstance(assembly, scad.Assembly):
            raise TypeError(f"{shape_name!r} is not an Assembly")

        mesh_kwargs: Dict[str, Any] = {"shading": _optional_shading(shading)}
        tol = _optional_float(mesh_tolerance)
        ang = _optional_float(mesh_angular_tolerance)
        if tol is not None:
            mesh_kwargs["mesh_tolerance"] = tol
        if ang is not None:
            mesh_kwargs["mesh_angular_tolerance"] = ang

        for index, component in enumerate(assembly.components):
            if not isinstance(component.item, scad.Part):
                raise TypeError("Assembly component preview requires direct Part components")
            placed = place_shape_ocp(
                component.item.body,
                component.placement.origin,
                component.placement.x_axis,
                component.placement.y_axis,
                component.placement.z_axis,
            )
            mesh = mesh_export.build_render_mesh(placed, **mesh_kwargs)
            path = f"{path_prefix}_{index}.bin"
            positions_bytes = mesh.positions.tobytes()
            normals_bytes = mesh.normals.tobytes()
            colors_bytes = mesh.colors.tobytes()
            with open(path, "wb") as f:
                f.write(positions_bytes)
                f.write(normals_bytes)
                f.write(colors_bytes)
            positions_len = len(positions_bytes)
            normals_len = len(normals_bytes)
            colors_len = len(colors_bytes)
            result["components"].append(
                {
                    "component_id": component.component_id,
                    "ok": True,
                    "error": None,
                    "path": path,
                    "byteLength": positions_len + normals_len + colors_len,
                    "vertexCount": int(mesh.positions.shape[0]),
                    "triangleCount": mesh.triangle_count,
                    "bufferViews": {
                        "positions": {"byteOffset": 0, "byteLength": positions_len, "dtype": "float32", "itemSize": 3},
                        "normals": {"byteOffset": positions_len, "byteLength": normals_len, "dtype": "float32", "itemSize": 3},
                        "colors": {"byteOffset": positions_len + normals_len, "byteLength": colors_len, "dtype": "float32", "itemSize": 3},
                    },
                    "bounds": {"min": list(mesh.bounds_min), "max": list(mesh.bounds_max)},
                }
            )
    except BaseException as exc:  # noqa: BLE001 - browser harness boundary
        result["ok"] = False
        result["components"] = []
        result["error"] = _error_payload(exc)
    return json.dumps(result, ensure_ascii=False)


def render_assembly_part_meshes(
    session_id: str,
    shape_name: str,
    requested_part_ids: Sequence[str],
    path_prefix: str = "/tmp/assembly_part_mesh",
    mesh_tolerance: Optional[float] = None,
    mesh_angular_tolerance: Optional[float] = None,
    shading: Optional[str] = None,
) -> str:
    """Tessellate requested unique Parts in local coordinates exactly once."""
    ns = _namespace(session_id)
    result: Dict[str, Any] = {"ok": True, "parts": [], "error": None}
    try:
        if shape_name not in ns:
            raise KeyError(f"No shape named {shape_name!r} in session {session_id!r}")
        assembly = ns[shape_name]
        if not isinstance(assembly, scad.Assembly):
            raise TypeError(f"{shape_name!r} is not an Assembly")
        if isinstance(requested_part_ids, (str, bytes)):
            raise TypeError("requested_part_ids must be a sequence of part_id values")

        parts = _direct_assembly_parts(assembly)
        requested: list[str] = []
        for value in requested_part_ids:
            part_id = str(value).strip()
            if not part_id:
                raise ValueError("requested_part_ids must not contain empty values")
            if part_id not in requested:
                requested.append(part_id)
        missing = [part_id for part_id in requested if part_id not in parts]
        if missing:
            raise KeyError("Unknown Assembly part_id values: " + ", ".join(missing))

        mesh_kwargs: Dict[str, Any] = {"shading": _optional_shading(shading)}
        tol = _optional_float(mesh_tolerance)
        ang = _optional_float(mesh_angular_tolerance)
        if tol is not None:
            mesh_kwargs["mesh_tolerance"] = tol
        if ang is not None:
            mesh_kwargs["mesh_angular_tolerance"] = ang

        for index, part_id in enumerate(requested):
            part = parts[part_id]
            mesh = mesh_export.build_render_mesh(part.body, **mesh_kwargs)
            path = f"{path_prefix}_{index}.bin"
            positions_bytes = mesh.positions.tobytes()
            normals_bytes = mesh.normals.tobytes()
            colors_bytes = mesh.colors.tobytes()
            with open(path, "wb") as stream:
                stream.write(positions_bytes)
                stream.write(normals_bytes)
                stream.write(colors_bytes)
            positions_len = len(positions_bytes)
            normals_len = len(normals_bytes)
            colors_len = len(colors_bytes)
            result["parts"].append(
                {
                    "part_id": part_id,
                    "ok": True,
                    "error": None,
                    "path": path,
                    "byteLength": positions_len + normals_len + colors_len,
                    "vertexCount": int(mesh.positions.shape[0]),
                    "triangleCount": mesh.triangle_count,
                    "bufferViews": {
                        "positions": {"byteOffset": 0, "byteLength": positions_len, "dtype": "float32", "itemSize": 3},
                        "normals": {"byteOffset": positions_len, "byteLength": normals_len, "dtype": "float32", "itemSize": 3},
                        "colors": {"byteOffset": positions_len + normals_len, "byteLength": colors_len, "dtype": "float32", "itemSize": 3},
                    },
                    "bounds": {
                        "min": list(mesh.bounds_min),
                        "max": list(mesh.bounds_max),
                    },
                }
            )
    except BaseException as exc:  # noqa: BLE001 - browser harness boundary
        result["ok"] = False
        result["parts"] = []
        result["error"] = _error_payload(exc)
    return json.dumps(result, ensure_ascii=False)


def inspect_geometry(session_id: str, shape_name: str)-> str:
    """
    Use shape.get_volume() and bounding_box function to get the essential
    geometric data of the generated shape
    """
    result:Dict[str,Any] = {
        "ok" : False,
        "error": None,
        "volume" : None,
        "bbox" : None,
        "constraint_report": None

    }

    ns = _namespace(session_id)
    try:
        if shape_name not in ns:
            raise KeyError(f"No shape named {shape_name!r} in session {session_id!r}")
        shape = ns[shape_name]
        if isinstance(shape, (scad.Solid,scad.Compound)):
            result["volume"] = float(shape.get_volume())
            bb = bounding_box(shape.wrapped)
            result["bbox"] = {
                "min": (float(bb.xmin), float(bb.ymin), float(bb.zmin)),
                "max": (float(bb.xmax), float(bb.ymax), float(bb.zmax)),
            }
            result["ok"] = True
        elif isinstance(shape,scad.Assembly):
            result["constraint_report"] = scad.inspect_assembly_constraints_rconstraintreport(shape).to_dict()
            result["ok"] = True
        else:
            raise TypeError(f"{shape_name!r} is a {type(shape).__name__}, expected Solid, Compound, or Assembly")
    except BaseException as exc:  
        result["ok"] = False
        result["error"] = _error_payload(exc)
        
    return json.dumps(result, ensure_ascii=False)
