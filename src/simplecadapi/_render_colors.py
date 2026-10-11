"""Tag -> RGB color resolution for the render-mesh export pipeline.

A leaf module (no dependency on operations.py/_mesh.py/core.py), kept
separate from mesh_export.py so the palette-cycling/override rule for
highlight-tag colors has one clear home rather than being buried inline in
the mesh-building code.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

DEFAULT_HIGHLIGHT_PALETTE: Tuple[str, ...] = (
    "#f39c12",
    "#9b59b6",
    "#f1c40f",
    "#1abc9c",
    "#e67e22",
    "#e84393",
    "#16a085",
    "#d35400",
)

_NAMED_COLORS: Dict[str, str] = {
    "black": "#000000",
    "blue": "#0000ff",
    "cyan": "#00ffff",
    "gray": "#808080",
    "green": "#008000",
    "grey": "#808080",
    "magenta": "#ff00ff",
    "orange": "#ffa500",
    "purple": "#800080",
    "red": "#ff0000",
    "white": "#ffffff",
    "yellow": "#ffff00",
}


def _to_rgb(color: str) -> Tuple[float, float, float]:
    """Parse the small CSS-color subset used by render-mesh highlights.

    Keeping this parser local avoids pulling a plotting dependency tree into
    every uncoloured CAD preview. Alpha is accepted in
    ``#RGBA`` / ``#RRGGBBAA`` inputs but ignored, matching ``to_rgb``.
    """

    value = color.strip().lower()
    value = _NAMED_COLORS.get(value, value)
    if not value.startswith("#"):
        raise ValueError(
            f"Unsupported highlight color {color!r}; use #RGB, #RGBA, "
            "#RRGGBB, #RRGGBBAA, or a basic named color"
        )

    hex_value = value[1:]
    if len(hex_value) in (3, 4):
        hex_value = "".join(channel * 2 for channel in hex_value)
    if len(hex_value) not in (6, 8):
        raise ValueError(f"Invalid highlight color {color!r}")

    try:
        channels = (
            int(hex_value[0:2], 16) / 255.0,
            int(hex_value[2:4], 16) / 255.0,
            int(hex_value[4:6], 16) / 255.0,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid highlight color {color!r}") from exc
    return channels


def resolve_tag_colors(
    highlight_tags: Sequence[str],
    highlight_colors: Optional[Dict[str, str]] = None,
    palette: Sequence[str] = DEFAULT_HIGHLIGHT_PALETTE,
) -> Dict[str, Tuple[float, float, float]]:
    """Assign each tag an RGB color in [0, 1].

    A tag with an explicit entry in `highlight_colors` uses that color;
    otherwise tags cycle through `palette` in the order given (tag at index
    i gets `palette[i % len(palette)]`).
    """
    overrides = highlight_colors or {}
    result: Dict[str, Tuple[float, float, float]] = {}
    for idx, tag in enumerate(highlight_tags):
        if tag in overrides:
            result[tag] = _to_rgb(overrides[tag])
        else:
            result[tag] = _to_rgb(palette[idx % len(palette)])
    return result
