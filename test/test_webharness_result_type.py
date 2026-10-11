import json

import simplecadapi.webharness as harness


def test_run_code_reports_model_result_type() -> None:
    payload = json.loads(
        harness.run_code(
            "import simplecadapi as scad\nresult = scad.make_box_rsolid(1, 1, 1)",
            "result-type-model",
        )
    )

    assert payload["ok"] is True
    assert payload["result_type"] == "Solid"
    assert "result" in payload["shapes"]


def test_run_code_reports_assembly_result_type() -> None:
    payload = json.loads(
        harness.run_code(
            "\n".join(
                [
                    "import simplecadapi as scad",
                    "body = scad.make_box_rsolid(1, 1, 1)",
                    "part = scad.make_part_rpart('block', body, name='Block')",
                    "result = scad.make_assembly_rassembly('fixture', name='Fixture')",
                    "result = scad.add_component_rassembly(",
                    "    result, part, component_id='block_1',",
                    "    placement=scad.identity_placement_rplacement(),",
                    "    name='Block instance',",
                    ")",
                ]
            ),
            "result-type-assembly",
        )
    )

    assert payload["ok"] is True
    assert payload["result_type"] == "Assembly"
    assert "result" in payload["shapes"]
    assert payload["assembly"] == {
        "assembly_id": "fixture",
        "name": "Fixture",
        "components": [
            {
                "component_id": "block_1",
                "component_name": "Block instance",
                "item_kind": "part",
                "part_id": "block",
                "part_name": "Block",
                "placement": {
                    "origin": [0.0, 0.0, 0.0],
                    "x_axis": [1.0, 0.0, 0.0],
                    "y_axis": [0.0, 1.0, 0.0],
                    "z_axis": [0.0, 0.0, 1.0],
                },
            }
        ],
        "bom": [{"part_id": "block", "part_name": "Block", "quantity": 1}],
    }


def test_run_code_reports_nested_assembly_as_a_non_part_component() -> None:
    payload = json.loads(
        harness.run_code(
            "\n".join(
                [
                    "import simplecadapi as scad",
                    "body = scad.make_box_rsolid(1, 1, 1)",
                    "part = scad.make_part_rpart('block', body)",
                    "child = scad.make_assembly_rassembly('child')",
                    "child = scad.add_component_rassembly(child, part, 'block_1', scad.identity_placement_rplacement())",
                    "result = scad.make_assembly_rassembly('root')",
                    "result = scad.add_component_rassembly(result, child, 'child_1', scad.identity_placement_rplacement())",
                ]
            ),
            "result-type-nested-assembly",
        )
    )

    assert payload["ok"] is True
    assert payload["assembly"]["components"][0]["item_kind"] == "assembly"
    assert payload["assembly"]["components"][0]["part_id"] is None


def test_assembly_component_meshes_keep_instances_separate(tmp_path) -> None:
    session_id = "assembly-component-meshes"
    payload = json.loads(
        harness.run_code(
            "\n".join(
                [
                    "import simplecadapi as scad",
                    "body = scad.make_box_rsolid(2, 2, 2)",
                    "part = scad.make_part_rpart('block', body)",
                    "result = scad.make_assembly_rassembly('fixture')",
                    "result = scad.add_component_rassembly(result, part, 'left', scad.make_placement_rplacement((-3, 0, 0)))",
                    "result = scad.add_component_rassembly(result, part, 'right', scad.make_placement_rplacement((3, 0, 0)))",
                ]
            ),
            session_id,
        )
    )
    assert payload["ok"] is True

    meshes = json.loads(
        harness.render_assembly_component_meshes(
            session_id,
            "result",
            path_prefix=str(tmp_path / "component"),
        )
    )

    assert meshes["ok"] is True
    assert [entry["component_id"] for entry in meshes["components"]] == ["left", "right"]
    assert all(entry["vertexCount"] > 0 for entry in meshes["components"])
    assert all((tmp_path / f"component_{index}.bin").is_file() for index in range(2))
    bounds_by_id = {entry["component_id"]: entry["bounds"] for entry in meshes["components"]}
    assert bounds_by_id["left"]["max"][0] < bounds_by_id["right"]["min"][0]
