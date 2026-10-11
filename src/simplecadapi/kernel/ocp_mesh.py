"""OCP-native mesh/shell construction and tessellation helpers."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Poly import Poly_Triangulation
from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Face, TopoDS_Shell
from OCP.gp import gp_Pnt

from ._ocp_compat import TopoDS_Shell_s
from .ocp_properties import bounding_box
from .ocp_topology import faces_of


def make_triangle_face(points: Sequence[Sequence[float]]) -> TopoDS_Face:
    if len(points) != 3:
        raise ValueError("Triangle face requires exactly three points")
    polygon = BRepBuilderAPI_MakePolygon()
    for p in points:
        polygon.Add(gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
    polygon.Close()
    if not polygon.IsDone():
        raise ValueError("OCP polygon builder failed")
    face = BRepBuilderAPI_MakeFace(polygon.Wire(), True)
    if not face.IsDone():
        raise ValueError("OCP triangle face builder failed")
    return face.Face()


def shell_metric(shell) -> tuple[int, float]:
    bb = bounding_box(shell)
    volume = bb.xlen * bb.ylen * bb.zlen
    return (len(faces_of(shell)), float(volume))


def shell_is_closed(shell) -> bool:
    return bool(TopoDS_Shell_s(shell).Closed())


def solid_from_shell(shell):
    maker = BRepBuilderAPI_MakeSolid(TopoDS_Shell_s(shell))
    if not maker.IsDone():
        raise ValueError("OCP solid-from-shell builder failed")
    return maker.Solid()


def tessellate_face(face: TopoDS_Face, tolerance: float = 0.35, angular_tolerance: float = 0.22):
    """Tessellate a face, returning (vertices, triangles, node_normals).

    ``node_normals`` holds one analytic surface normal per vertex, evaluated
    directly from the underlying surface at that vertex's UV parameter
    (rather than derived from the triangle's own 3D point geometry). This
    matters because the triangulation can contain near-degenerate sliver
    triangles (e.g. fanning out from a hole or fillet boundary), for which a
    cross-product-of-3D-points normal is numerically unstable; the analytic
    surface normal is well-defined regardless of triangle shape. Empty when
    the triangulation has no UV data - callers should fall back to
    geometric per-triangle normals in that case.
    """
    mesh = BRepMesh_IncrementalMesh(face, float(tolerance), False, float(angular_tolerance), True)
    mesh.Perform()
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is None:
        return [], [], []
    trsf = loc.Transformation()
    vertices = []
    for idx in range(1, tri.NbNodes() + 1):
        p = tri.Node(idx).Transformed(trsf)
        vertices.append((float(p.X()), float(p.Y()), float(p.Z())))
    reversed_face = face.Orientation() == TopAbs_REVERSED
    triangles = []
    for idx in range(1, tri.NbTriangles() + 1):
        a, b, c = tri.Triangle(idx).Get()
        if reversed_face:
            triangles.append((a - 1, c - 1, b - 1))
        else:
            triangles.append((a - 1, b - 1, c - 1))
    node_normals = _node_normals(face, tri, reversed_face)
    return vertices, triangles, node_normals


def _node_normals(
    face: TopoDS_Face, tri: Poly_Triangulation, reversed_face: bool
) -> List[Tuple[float, float, float]]:
    if not tri.HasUVNodes():
        return []
    try:
        adaptor = BRepAdaptor_Surface(face, True)
    except Exception:
        return []
    normals: List[Tuple[float, float, float]] = []
    for idx in range(1, tri.NbNodes() + 1):
        uv = tri.UVNode(idx)
        try:
            props = BRepLProp_SLProps(adaptor, float(uv.X()), float(uv.Y()), 1, 1e-7)
            if not props.IsNormalDefined():
                normals.append((0.0, 0.0, 0.0))
                continue
            n = props.Normal()
            if reversed_face:
                n.Reverse()
            normals.append((float(n.X()), float(n.Y()), float(n.Z())))
        except Exception:
            normals.append((0.0, 0.0, 0.0))
    return normals
