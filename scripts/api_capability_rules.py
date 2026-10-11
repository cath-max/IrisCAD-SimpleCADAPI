"""Capability tags + agent_priority rules for API catalog records.

Used by scripts/build_api_catalog.py (step 2 of retrieval index prep).
Tags are derived from README doc_category + symbol heuristics — not from
exhaustive user-utterance synonym lists.
"""

from __future__ import annotations

import re
from typing import Iterable

# Minimal industrial core toolbox: always include these for agent solid modeling.
# Match on catalog `id` (filename stem) or `symbol` (import name).
CORE_AGENT_IDS: frozenset[str] = frozenset(
    {
        "make_box_rsolid",
        "make_cylinder_rsolid",
        "union_rsolid",
        "cut_rsolid",
        "extrude_rsolid",
        "revolve_rsolid",
    }
)

# Public helper `var(...)` remains a normal ranked candidate even though its
# broader Expressions and Parameters category is low-priority. The `Var` class
# itself stays low-priority to avoid spending two result slots on one concept.
NORMAL_AGENT_IDS: frozenset[str] = frozenset({"var_function", "var"})
LOW_AGENT_IDS: frozenset[str] = frozenset({"Var"})

# README sections that are usually off the solid-part agent happy path.
_LOW_CATEGORIES: frozenset[str] = frozenset(
    {
        "FreeCAD Translation",
        "Modeling Graph and Replay",
        "Math Helpers",
    }
)

_SYMBOL_TAG_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"make_cone|cone_rsolid", re.I), ("cone", "primitive", "solid")),
    (re.compile(r"box|cylinder|sphere", re.I), ("primitive", "solid")),
    (re.compile(r"cut_rsolid|intersect_rsolid|union_rsolid", re.I), ("boolean",)),
    (re.compile(r"^cut_|_cut_|boolean", re.I), ("boolean",)),
    (re.compile(r"revolve", re.I), ("revolve", "profile_solid")),
    (re.compile(r"extrude", re.I), ("extrude", "profile_solid")),
    (re.compile(r"loft", re.I), ("loft", "profile_solid")),
    (re.compile(r"sweep|helical_sweep", re.I), ("sweep", "profile_solid")),
    (re.compile(r"fillet", re.I), ("fillet", "detailing")),
    (re.compile(r"chamfer", re.I), ("chamfer", "detailing")),
    (re.compile(r"shell_rsolid", re.I), ("shell", "detailing")),
    (re.compile(r"linear_pattern|radial_pattern", re.I), ("pattern", "hole_pattern")),
    (re.compile(r"flange", re.I), ("flange", "hole_pattern")),
    (re.compile(r"threaded|thread", re.I), ("fastener", "thread")),
    (re.compile(r"naca|blade|propeller", re.I), ("blade",)),
    (re.compile(r"export_step|export_stl", re.I), ("export",)),
    (re.compile(r"mirror_shape|rotate_shape|translate_shape", re.I), ("transform",)),
    (re.compile(r"tag|select_faces|select_edges|apply_tag|list_tags", re.I), ("tagging",)),
    (re.compile(r"^Var$|^var$|ExpressionGraph|^Expr$|^Const$|^const$", re.I), ("parameters",)),
    (re.compile(r"Assembly|Component|Connector|Constraint|ground_component|place_component", re.I), ("assembly",)),
    (re.compile(r"sketch|Sketch", re.I), ("sketch",)),
    (re.compile(r"FreeCAD|translate_model|translator", re.I), ("toolchain",)),
    (re.compile(r"GraphSession|replay_|export_.*json|import_.*json", re.I), ("graph_replay",)),
)

_CATEGORY_TAG_RULES: dict[str, tuple[str, ...]] = {
    "Basic Creation": ("primitive", "solid"),
    "Boolean Operations": ("boolean", "solid"),
    "3D Operations": ("profile_solid", "solid"),
    "Advanced Features": ("detailing", "solid"),
    "Transforms": ("transform",),
    "Tagging and Selection": ("tagging",),
    "Export": ("export",),
    "Evolve": ("evolve", "solid"),
    "Expressions and Parameters": ("parameters",),
    "FreeCAD Translation": ("toolchain",),
    "Modeling Graph and Replay": ("graph_replay",),
    "Math Helpers": ("math",),
    "Types and Errors": ("types",),
}


def _unique(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def derive_capability_tags(
    *,
    symbol: str,
    doc_category: str,
    import_surface: str | None = None,
) -> list[str]:
    tags: list[str] = []

    cat_tags = _CATEGORY_TAG_RULES.get(doc_category)
    if cat_tags:
        tags.extend(cat_tags)

    for pattern, extra in _SYMBOL_TAG_RULES:
        if pattern.search(symbol):
            tags.extend(extra)

    surface = (import_surface or "").lower()
    if "translator" in surface:
        tags.append("toolchain")
    if surface.startswith("submodule") or "ql" in surface:
        tags.append("ql")

    # Solid-part default when still empty (e.g. sparse "Other" entries).
    if not tags:
        tags.append("other")

    return _unique(tags)


def derive_agent_priority(
    *,
    record_id: str,
    symbol: str,
    doc_category: str,
    import_surface: str | None,
    capability_tags: list[str] | None = None,
) -> str:
    """Return 'core' | 'normal' | 'low'."""
    if record_id in CORE_AGENT_IDS or symbol in CORE_AGENT_IDS:
        return "core"
    if record_id in LOW_AGENT_IDS or symbol in LOW_AGENT_IDS:
        return "low"
    if record_id in NORMAL_AGENT_IDS or symbol in NORMAL_AGENT_IDS:
        return "normal"

    tags = set(capability_tags or [])
    surface = (import_surface or "").lower()

    if doc_category in _LOW_CATEGORIES:
        return "low"
    if "translator" in surface:
        return "low"
    if surface.startswith("submodule") or "ql" in surface:
        return "low"
    if tags & {"assembly", "sketch", "toolchain", "graph_replay", "ql"}:
        return "low"
    # Product-structure types living under README "Other"
    if re.search(
        r"^(Assembly|Component|Connector|Constraint|Part|Placement|Material)\b",
        symbol,
    ):
        return "low"
    if re.search(r"sketch|Sketch", symbol):
        return "low"

    return "normal"


def industrial_cues_for_tags(tags: list[str]) -> str:
    """Short phrases appended to embedding_text (not a user-synonym mega-list)."""
    cue_map = {
        # Keep broad stock words; cone synonyms live on the dedicated "cone" tag.
        "primitive": "box cylinder sphere solid stock",
        "cone": (
            "cone conical frustum taper bevel truncated blank pitch-cone"
        ),
        "boolean": "cut hole pocket union join subtract boolean",
        "revolve": (
            "revolve lathe turned body mug cup of revolution "
            "dome canopy axisymmetric taper"
        ),
        "extrude": "extrude pull profile prism",
        "loft": (
            "loft blend profiles taper transition ruled sections "
            "conical frustum multi-section"
        ),
        "fillet": "fillet round edge blend",
        # Keep "bevel" for spoken chamfer; cone/loft also include bevel.
        "chamfer": "chamfer bevel edge",
        "flange": "flange plate bolt circle mounting holes",
        "hole_pattern": "bolt pattern hole array pitch circle",
        "fastener": "threaded rod screw bolt",
        "pattern": "linear pattern radial pattern array",
        "export": "STEP STL export download",
        "parameters": "parametric variable dimension slider",
        "assembly": "assembly constraint mate component",
        "sketch": "2d sketch constraint profile",
    }
    parts: list[str] = []
    for tag in tags:
        if tag in cue_map:
            parts.append(cue_map[tag])
    return "; ".join(parts)
