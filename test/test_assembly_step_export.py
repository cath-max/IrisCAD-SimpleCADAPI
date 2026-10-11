from pathlib import Path

import simplecadapi as scad


def test_export_assembly_step_writes_two_part_xcaf_step(tmp_path: Path) -> None:
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
    assembly = scad.make_assembly_rassembly("two_part_assembly")
    assembly = scad.add_component_rassembly(
        assembly,
        base_plate,
        component_id="base_plate_instance",
        placement=scad.identity_placement_rplacement(),
        name="Base plate instance",
    )
    assembly = scad.add_component_rassembly(
        assembly,
        top_block,
        component_id="top_block_instance",
        placement=scad.make_placement_rplacement((20.0, 10.0, 6.0)),
        name="Top block instance",
    )

    output_path = tmp_path / "two_part_assembly.step"
    scad.export_assembly_step(assembly, str(output_path))

    assert output_path.stat().st_size > 0
    step_text = output_path.read_text(encoding="utf-8", errors="ignore")
    assert "Base plate" in step_text
    assert "Top block" in step_text
