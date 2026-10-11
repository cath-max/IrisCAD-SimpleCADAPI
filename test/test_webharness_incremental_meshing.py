import json

import simplecadapi.webharness as harness


def _run_shared_part_assembly(session_id: str, width: float = 2.0) -> None:
    payload = json.loads(
        harness.run_code(
            "\n".join(
                [
                    "import simplecadapi as scad",
                    f"body = scad.make_box_rsolid({width}, 2, 2)",
                    "part = scad.make_part_rpart('block', body, name='Block')",
                    "result = scad.make_assembly_rassembly('fixture')",
                    "result = scad.add_component_rassembly(result, part, 'left', scad.make_placement_rplacement((-3, 0, 0)))",
                    "result = scad.add_component_rassembly(result, part, 'right', scad.make_placement_rplacement((3, 0, 0)))",
                ]
            ),
            session_id,
        )
    )
    assert payload["ok"] is True


def test_render_state_lists_unique_parts_and_keeps_placements() -> None:
    session_id = "incremental-render-state"
    _run_shared_part_assembly(session_id)

    state = json.loads(
        harness.inspect_assembly_render_state(session_id, "result")
    )

    assert state["ok"] is True
    assert len(state["parts"]) == 1
    assert state["parts"][0]["part_id"] == "block"
    assert [component["component_id"] for component in state["components"]] == [
        "left",
        "right",
    ]
    assert state["components"][0]["placement"]["origin"] == [-3.0, 0.0, 0.0]
    assert state["components"][1]["placement"]["origin"] == [3.0, 0.0, 0.0]


def test_part_meshes_are_unique_and_stay_in_local_coordinates(tmp_path) -> None:
    session_id = "incremental-part-meshes"
    _run_shared_part_assembly(session_id)

    meshes = json.loads(
        harness.render_assembly_part_meshes(
            session_id,
            "result",
            ["block", "block"],
            path_prefix=str(tmp_path / "part"),
            mesh_tolerance=0.12,
            mesh_angular_tolerance=0.1,
            shading="smooth",
        )
    )

    assert meshes["ok"] is True
    assert len(meshes["parts"]) == 1
    mesh = meshes["parts"][0]
    assert mesh["part_id"] == "block"
    assert mesh["vertexCount"] > 0
    assert mesh["bounds"]["min"][0] == -1.0
    assert mesh["bounds"]["max"][0] == 1.0
    assert (tmp_path / "part_0.bin").is_file()


def test_part_mesh_request_rejects_unknown_part_id() -> None:
    session_id = "incremental-missing-part"
    _run_shared_part_assembly(session_id)

    meshes = json.loads(
        harness.render_assembly_part_meshes(
            session_id,
            "result",
            ["missing"],
        )
    )

    assert meshes["ok"] is False
    assert meshes["parts"] == []
    assert "Unknown Assembly part_id" in meshes["error"]["what_happened"]
