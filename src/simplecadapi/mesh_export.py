"""Render-mesh export for the browser Three.js renderer.

`build_render_mesh` tessellates a shape once and hands back plain numpy
buffers (position/normal/color per triangle corner) that a JS/Three.js
renderer can feed straight into a `THREE.BufferGeometry`. The camera/view
loop lives entirely on the JS side, since the geometry itself does not
depend on which angle it's viewed from.

Buffers are non-indexed: each triangle gets its own 3 corner entries
rather than sharing vertices with its neighbors. With ``shading="flat"``
(the default), each triangle gets one averaged normal so tag highlight
boundaries and real face creases stay crisp. With ``shading="smooth"``,
each corner keeps the analytic surface normal from OCCT so interactive
previews can look rounded without changing the flat seven-view path.

Kept out of `operations.py` (already 6000+ lines) and out of `_mesh.py`
(which is intentionally scoped to the private, deduplicated-vertex mesh
cache the collision verifier uses - a different concern with a different
buffer shape).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Sequence, Tuple, Union

import numpy as np

from .core import Compound, Solid
from ._render_colors import resolve_tag_colors
from .kernel.ocp_mesh import tessellate_face
from .kernel.ocp_properties import bounding_box

AnyRenderShape = Union[Solid, Compound, Sequence[Union[Solid, Compound]]]
RenderShading = Literal["flat", "smooth"]

DEFAULT_MESH_TOLERANCE = 0.35
DEFAULT_MESH_ANGULAR_TOLERANCE = 0.22
DEFAULT_BASE_COLOR: Tuple[float, float, float] = (0.42, 0.48, 0.58)


@dataclass(frozen=True)
class RenderMesh:
    """Flat (non-indexed) triangle mesh ready for a `THREE.BufferGeometry`.

    `positions`/`normals`/`colors` all have shape (3 * triangle_count, 3),
    float32, one row per triangle corner - row `3*i + k` is corner `k` of
    triangle `i`. There is no index buffer: corners are never shared.
    """

    positions: np.ndarray
    normals: np.ndarray
    colors: np.ndarray
    bounds_min: Tuple[float, float, float]
    bounds_max: Tuple[float, float, float]
    legend: Tuple[Dict[str, Any], ...]

    @property
    def triangle_count(self) -> int:
        return int(self.positions.shape[0] // 3)


def _normalize_solids(shapes: AnyRenderShape) -> list[Solid]:
    """Flatten Solid/Compound (or a sequence of them) into a list of Solids."""

    if isinstance(shapes, Solid):
        items = [shapes]
    elif isinstance(shapes, Compound):
        items = [shapes]
    elif isinstance(shapes, Sequence) and not isinstance(shapes, (str, bytes)):
        items = list(shapes)
    else:
        raise ValueError("build_render_mesh 仅支持 Solid、Compound 或它们的序列")

    solids: list[Solid] = []
    for item in items:
        if isinstance(item, Solid):
            solids.append(item)
        elif isinstance(item, Compound):
            solids.extend(item.get_solids())
        else:
            raise ValueError("build_render_mesh 仅支持 Solid、Compound 或它们的序列")
    if not solids:
        raise ValueError("build_render_mesh 至少需要一个 Solid")
    return solids


def _geometric_normals(tri_pts: np.ndarray) -> np.ndarray:
    geo = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
    geo_norms = np.linalg.norm(geo, axis=1)
    return np.divide(
        geo,
        geo_norms[:, None],
        out=np.zeros_like(geo),
        where=geo_norms[:, None] != 0,
    )


def build_render_mesh(
    shapes: AnyRenderShape,
    *,
    highlight_tags: Optional[Sequence[str]] = None,
    highlight_colors: Optional[Dict[str, str]] = None,
    tag_labels: Optional[Dict[str, str]] = None,
    base_color: Tuple[float, float, float] = DEFAULT_BASE_COLOR,
    mesh_tolerance: float = DEFAULT_MESH_TOLERANCE,
    mesh_angular_tolerance: float = DEFAULT_MESH_ANGULAR_TOLERANCE,
    shading: RenderShading = "flat",
) -> RenderMesh:
    """Tessellate `shapes` once into a render mesh.

    Per-face tessellation and tag-color resolution are computed exactly once
    per render request (not once per camera view), returning buffers rather
    than painting a picture directly.

    ``shading="flat"`` (default): one normal per triangle (averaged node
    normals or geometric fallback), repeated on all three corners — crisp
    creases for seven-view inspection.

    ``shading="smooth"``: per-corner analytic ``node_normals`` when UV data
    exists; falls back to flat geometric normals when it does not.
    """

    solids = _normalize_solids(shapes)
    highlight_list = list(highlight_tags or [])
    labels = tag_labels or {}
    color_map = resolve_tag_colors(highlight_list, highlight_colors)
    base_rgb = np.array(base_color, dtype=float)
    use_smooth = shading == "smooth"

    position_chunks: list[np.ndarray] = []
    normal_chunks: list[np.ndarray] = []
    color_chunks: list[np.ndarray] = []
    bbox_min = np.array([np.inf, np.inf, np.inf])
    bbox_max = np.array([-np.inf, -np.inf, -np.inf])

    for solid in solids:
        bb = bounding_box(solid.wrapped)
        bbox_min = np.minimum(bbox_min, np.array([bb.xmin, bb.ymin, bb.zmin]))
        bbox_max = np.maximum(bbox_max, np.array([bb.xmax, bb.ymax, bb.zmax]))

        solid_tag = next((tag for tag in highlight_list if solid._has_tag(tag)), None)

        for face in solid.get_faces():
            face_tag = next((tag for tag in highlight_list if face._has_tag(tag)), None)
            face_highlight_tag = face_tag or solid_tag

            verts, tri_indices, node_normals = tessellate_face(
                face.wrapped, mesh_tolerance, mesh_angular_tolerance
            )
            if not tri_indices:
                continue

            vertices = np.array(verts, dtype=float)
            tris = np.array(tri_indices, dtype=int)
            tri_pts = vertices[tris]
            triangle_count = tri_pts.shape[0]
            geo_normals = _geometric_normals(tri_pts)

            if node_normals and use_smooth:
                node_normals_arr = np.array(node_normals, dtype=float)
                corner_normals = node_normals_arr[tris].reshape(-1, 3)
                norms = np.linalg.norm(corner_normals, axis=1)
                corner_normals = np.divide(
                    corner_normals,
                    norms[:, None],
                    out=np.zeros_like(corner_normals),
                    where=norms[:, None] != 0,
                )
                degenerate = norms <= 1e-9
                if np.any(degenerate):
                    fallback_corners = np.repeat(geo_normals, 3, axis=0)
                    corner_normals[degenerate] = fallback_corners[degenerate]
                face_normals = corner_normals
            elif node_normals:
                node_normals_arr = np.array(node_normals, dtype=float)
                normals = node_normals_arr[tris].mean(axis=1)
                norms = np.linalg.norm(normals, axis=1)
                normals = np.divide(
                    normals,
                    norms[:, None],
                    out=np.zeros_like(normals),
                    where=norms[:, None] != 0,
                )
                degenerate = norms <= 1e-9
                if np.any(degenerate):
                    normals[degenerate] = geo_normals[degenerate]
                face_normals = np.repeat(normals, 3, axis=0)
            else:
                face_normals = np.repeat(geo_normals, 3, axis=0)

            color = color_map.get(face_highlight_tag, tuple(base_rgb)) if face_highlight_tag else tuple(base_rgb)
            face_color = np.asarray(color, dtype=float)

            position_chunks.append(tri_pts.reshape(-1, 3))
            normal_chunks.append(face_normals)
            color_chunks.append(np.tile(face_color, (triangle_count * 3, 1)))

    if not position_chunks:
        raise ValueError("未生成任何可渲染三角面")

    legend = tuple(
        {"tag": tag, "label": labels.get(tag, tag), "color": list(color_map[tag])}
        for tag in highlight_list
    )

    return RenderMesh(
        positions=np.concatenate(position_chunks, axis=0).astype(np.float32),
        normals=np.concatenate(normal_chunks, axis=0).astype(np.float32),
        colors=np.concatenate(color_chunks, axis=0).astype(np.float32),
        bounds_min=tuple(float(v) for v in bbox_min),
        bounds_max=tuple(float(v) for v in bbox_max),
        legend=legend,
    )
