import json

import simplecadapi.webharness as harness


def _source(*sections: str) -> str:
    return "import simplecadapi as scad\n\n" + "\n\n".join(sections)


def _section(kind: str, body: str, identifier: str | None = None) -> str:
    return f"# cadam:{kind}{f' {identifier}' if identifier else ''}\n{body}"


def _analysis(source: str) -> dict:
    return json.loads(harness.analyze_assembly_sections(source))


def _base_sections() -> list[str]:
    return [
        _section("parameters", "radius = 2\ncount = 3"),
        _section("assembly_setup", "assembly = None"),
        _section("component", "result_component = assembly", "main"),
        _section("assembly_result", "result = assembly"),
    ]


def test_analyzes_direct_parameters_helpers_functions_locals_loops_and_comprehensions() -> None:
    source = _source(
        _section("parameters", "radius = 2\ncount = 3\nshared = 8"),
        _section(
            "helper",
            "def make(value):\n    return value + shared\n\ndef shadow(shared):\n    return shared\n\npoints = [index for index in range(count)]",
            "helpers",
        ),
        _section("part", "for index in range(count):\n    diameter = make(radius)\npart = diameter", "wheel_part"),
        _section("assembly_setup", "assembly = part"),
        _section("component", "result_component = assembly", "main"),
        _section("assembly_result", "result = assembly"),
    )
    result = _analysis(source)
    assert result["ok"] is True
    sections = {item["section"]["kind"] + "/" + item["section"]["id"]: item for item in result["sections"]}
    helper = sections["helper/helpers"]
    assert helper["writes"] == ["make", "points", "shadow"]
    assert helper["reads"] == ["count", "range", "shared"]
    assert helper["unsafe_syntax"] == []
    part = sections["part/wheel_part"]
    assert part["writes"] == ["diameter", "index", "part"]
    assert part["reads"] == ["count", "make", "radius", "range"]
    assert _analysis(source) == result


def test_marks_dynamic_python_as_unsafe_without_executing_source() -> None:
    source = _source(
        _section("parameters", "radius = 2"),
        _section("helper", "eval('raise RuntimeError()')\nmodule = __import__('math')", "helpers"),
        _section("part", "part = radius", "wheel_part"),
        *_base_sections()[1:],
    )
    result = _analysis(source)
    assert result["ok"] is True
    helper = next(item for item in result["sections"] if item["section"] == {"kind": "helper", "id": "helpers"})
    assert helper["unsafe_syntax"] == ["dynamic_import", "eval"]


def test_rejects_invalid_layout_and_syntax_without_execution() -> None:
    invalid_layout = _analysis("import simplecadapi as scad\nvalue = 1")
    assert invalid_layout == {"ok": False, "sections": [], "error": {"reason": "layout_invalid", "detail": "Line 2: executable code must be inside a CADAM Assembly section."}}
    invalid_syntax = _analysis(_source(
        _section("parameters", "radius ="),
        _section("part", "part = 1", "wheel_part"),
        *_base_sections()[1:],
    ))
    assert invalid_syntax["ok"] is False
    assert invalid_syntax["error"]["reason"] == "unsupported_python"


def test_keeps_assembly_reads_when_components_rewrite_assembly() -> None:
    source = _source(
        _section("parameters", "radius = 2"),
        _section("part", "part = radius", "wheel_part"),
        _section("assembly_setup", "assembly = make_assembly()"),
        _section("component", "assembly = add_component(assembly, part)", "wheel"),
        _section("assembly_result", "result = assembly"),
    )
    result = _analysis(source)
    assert result["ok"] is True
    component = next(item for item in result["sections"] if item["section"] == {"kind": "component", "id": "wheel"})
    assert component["reads"] == ["add_component", "assembly", "part"]
    assert component["writes"] == ["assembly"]


def test_section_runner_reconstructs_only_ordered_sections_and_full_tail(monkeypatch) -> None:
    source = _source(
        _section("parameters", "radius = 2"),
        _section("helper", "diameter = radius * 2", "helpers"),
        _section("part", "wheel = diameter", "wheel_part"),
        _section("assembly_setup", "assembly = wheel"),
        _section("component", "assembly = assembly", "wheel"),
        _section("assembly_result", "result = assembly"),
    )
    captured: dict[str, str] = {}

    def fake_run(code: str, session_id: str) -> str:
        captured["code"] = code
        captured["session"] = session_id
        return json.dumps({"ok": True})

    monkeypatch.setattr(harness, "run_code", fake_run)
    result = json.loads(harness.run_assembly_sections(source, "session-1", json.dumps([
        {"kind": "parameters", "id": "parameters"},
        {"kind": "helper", "id": "helpers"},
        {"kind": "part", "id": "wheel_part"},
        {"kind": "assembly_setup", "id": "assembly_setup"},
        {"kind": "component", "id": "wheel"},
        {"kind": "assembly_result", "id": "assembly_result"},
    ])))
    assert result == {"ok": True}
    assert captured["session"] == "session-1"
    assert [line for line in captured["code"].splitlines() if line.strip()] == [
        "import simplecadapi as scad", "radius = 2", "diameter = radius * 2",
        "wheel = diameter", "assembly = wheel", "assembly = assembly", "result = assembly",
    ]


def test_section_runner_rejects_arbitrary_or_incomplete_tail() -> None:
    source = _source(
        _section("parameters", "radius = 2"),
        _section("part", "wheel = radius", "wheel_part"),
        _section("assembly_setup", "assembly = wheel"),
        _section("component", "assembly = assembly", "wheel"),
        _section("assembly_result", "result = assembly"),
    )
    result = json.loads(harness.run_assembly_sections(source, "session-1", json.dumps([
        {"kind": "parameters", "id": "parameters"},
        {"kind": "assembly_setup", "id": "assembly_setup"},
    ])))
    assert result["ok"] is False
    assert "complete Assembly tail" in result["error"]["what_happened"]
