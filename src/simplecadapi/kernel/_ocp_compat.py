"""Compatibility shim for OCP.TopoDS static shape-cast methods.

Desktop cadquery-ocp exposes both the ``_s``-suffixed and plain names for
these TopoDS static casts (pybind11 overload aliases). The OCP.wasm build
(yeicor/OCP.wasm, used for the browser/Pyodide target) only exposes the
plain name. Resolve once at import time so callers don't pay a per-call
attribute-lookup fallback.

Note: this only applies to TopoDS. Other classes used elsewhere in kernel/
(BRep_Tool, BRepGProp, BRepTools, BRepLib, BRepBndLib) only expose the
``_s``-suffixed name on both desktop and wasm builds and must not be
touched here.
"""

from __future__ import annotations

from OCP.TopoDS import TopoDS


def _resolve(name: str):
    return getattr(TopoDS, f"{name}_s", None) or getattr(TopoDS, name)


TopoDS_Vertex_s = _resolve("Vertex")
TopoDS_Edge_s = _resolve("Edge")
TopoDS_Wire_s = _resolve("Wire")
TopoDS_Face_s = _resolve("Face")
TopoDS_Shell_s = _resolve("Shell")
TopoDS_Solid_s = _resolve("Solid")
TopoDS_Compound_s = _resolve("Compound")
