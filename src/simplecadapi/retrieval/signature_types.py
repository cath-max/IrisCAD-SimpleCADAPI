"""Extract supported geometry input/output types from API signatures."""

from __future__ import annotations

import ast
from collections.abc import Iterable

GEOMETRY_TYPES = frozenset(
    {
        "Vertex",
        "Edge",
        "Wire",
        "Face",
        "Solid",
        "Compound",
        "ShapeSelector",
    }
)
_EXPANDABLE_CONTAINERS = frozenset({"Union", "Optional", "List", "Sequence"})


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _slice_items(node: ast.expr) -> Iterable[ast.expr]:
    if isinstance(node, ast.Tuple):
        return node.elts
    return (node,)


def _unique_geometry_types(types: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(type_name for type_name in types if type_name in GEOMETRY_TYPES)
    )


def geometry_types_from_annotation(annotation: ast.expr | None) -> tuple[str, ...]:
    """Return supported geometry types present in one Python annotation."""
    if annotation is None:
        return ()
    if isinstance(annotation, ast.Name):
        return (annotation.id,) if annotation.id in GEOMETRY_TYPES else ()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            return geometry_types_from_annotation(
                ast.parse(annotation.value, mode="eval").body
            )
        except SyntaxError:
            return ()
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _unique_geometry_types(
            (*geometry_types_from_annotation(annotation.left), *geometry_types_from_annotation(annotation.right))
        )
    if not isinstance(annotation, ast.Subscript):
        return ()

    container = _name(annotation.value)
    if container not in _EXPANDABLE_CONTAINERS:
        return ()
    return _unique_geometry_types(
        geometry_type
        for item in _slice_items(annotation.slice)
        for geometry_type in geometry_types_from_annotation(item)
    )


def parse_signature_types(signature: str | None) -> tuple[dict[str, list[str]], list[str]]:
    """Parse one documented function signature into JSON-ready geometry metadata.

    Unsupported, malformed, and class signatures deliberately return empty metadata:
    catalog generation must remain resilient to documentation that is not a function.
    """
    if not signature:
        return {}, []

    source = signature.strip()
    if not source.startswith("def "):
        return {}, []
    if not source.endswith(":"):
        source += ":"
    source += "\n    pass\n"
    try:
        node = ast.parse(source).body[0]
    except SyntaxError:
        return {}, []
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {}, []

    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg)

    input_types: dict[str, list[str]] = {}
    for argument in arguments:
        geometry_types = geometry_types_from_annotation(argument.annotation)
        if geometry_types:
            input_types[argument.arg] = list(geometry_types)
    return input_types, list(geometry_types_from_annotation(node.returns))


__all__ = ["GEOMETRY_TYPES", "geometry_types_from_annotation", "parse_signature_types"]
