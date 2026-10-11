import numpy as np

import simplecadapi as scad
from simplecadapi._render_colors import (
    DEFAULT_HIGHLIGHT_PALETTE,
    resolve_tag_colors,
)
from simplecadapi.mesh_export import DEFAULT_BASE_COLOR, build_render_mesh


def test_empty_highlights_need_no_optional_color_package() -> None:
    assert resolve_tag_colors([]) == {}


def test_default_palette_is_parsed_without_matplotlib() -> None:
    colors = resolve_tag_colors(["first", "second"])

    assert colors["first"] == (0xF3 / 255.0, 0x9C / 255.0, 0x12 / 255.0)
    assert colors["second"] == (0x9B / 255.0, 0x59 / 255.0, 0xB6 / 255.0)
    assert DEFAULT_HIGHLIGHT_PALETTE[0] == "#f39c12"


def test_hex_and_basic_named_overrides_are_supported() -> None:
    colors = resolve_tag_colors(
        ["short_hex", "with_alpha", "named"],
        {
            "short_hex": "#0af",
            "with_alpha": "#33669980",
            "named": "red",
        },
    )

    assert colors["short_hex"] == (0.0, 0xAA / 255.0, 1.0)
    assert colors["with_alpha"] == (0x33 / 255.0, 0x66 / 255.0, 0x99 / 255.0)
    assert colors["named"] == (1.0, 0.0, 0.0)


def test_uncoloured_model_mesh_keeps_the_default_gray() -> None:
    solid = scad.make_box_rsolid(10.0, 12.0, 14.0)

    mesh = build_render_mesh(solid)

    assert mesh.triangle_count > 0
    assert mesh.positions.shape == mesh.normals.shape == mesh.colors.shape
    assert np.allclose(mesh.colors, np.asarray(DEFAULT_BASE_COLOR))
