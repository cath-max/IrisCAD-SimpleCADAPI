"""Minimal XCAF STEP assembly export spike: two independently named parts."""

from pathlib import Path

import simplecadapi as scad


OUT_PATH = Path("examples/out/two_part_assembly.step")


def build_two_part_assembly() -> scad.Assembly:
    base_plate = scad.make_part_rpart(
        "base_plate",
        scad.make_box_rsolid(60.0, 40.0, 6.0),
        name="Base plate",
    )
    top_block = scad.make_part_rpart(
        "top_block",
        scad.make_box_rsolid(20.0, 20.0, 18.0),
        name="Top block",
    )

    assembly = scad.make_assembly_rassembly(
        "two_part_assembly",
        name="Two-part XCAF assembly",
    )
    assembly = scad.add_component_rassembly(
        assembly,
        base_plate,
        component_id="base_plate_instance",
        placement=scad.identity_placement_rplacement(),
        name="Base plate instance",
    )
    return scad.add_component_rassembly(
        assembly,
        top_block,
        component_id="top_block_instance",
        placement=scad.make_placement_rplacement((20.0, 10.0, 6.0)),
        name="Top block instance",
    )


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    assembly = build_two_part_assembly()
    scad.export_assembly_step(assembly, str(OUT_PATH))

    # The existing browser preview pipeline still renders this flattened proxy.
    preview = scad.make_compound_from_assembly_rcompound(assembly)
    print("assembly", assembly.assembly_id)
    print("components", assembly.component_ids())
    print("preview_solids", len(preview.get_solids()))
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    main()
