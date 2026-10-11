# SimpleCADAPI for IrisCAD

> [!IMPORTANT]
> This repository is an unofficial, modified distribution of
> [SimpleCADAPI](https://github.com/NiJingzhe/SimpleCADAPI) maintained for the
> IrisCAD browser CAD runtime. It is not an official upstream release and is
> not endorsed by the upstream maintainers.

SimpleCADAPI is an OCP-native Python SDK for building parametric CAD parts and
assemblies. This fork preserves the upstream modeling API while adding the
browser execution, mesh, assembly, and API-retrieval behavior required by
IrisCAD.

Current fork package version: `2.0.1b7`.

## Relationship to upstream

SimpleCADAPI was originally developed by NiJingzhe and contributors as part
of the research project
[CADDesigner: Conceptual CAD Model Generation with a General-Purpose Agent](https://562590763.github.io/CADDesigner/).

- Upstream repository: <https://github.com/NiJingzhe/SimpleCADAPI>
- Closest verified source baseline: `41099b595acb57e00d50b7a738bae5c85cf0c953`
- Fork provenance, import comparison, and license history: [`UPSTREAM.md`](UPSTREAM.md)

The original authors retain copyright in the upstream work. Contributors to
this fork retain copyright in their respective modifications. Do not describe
this fork as the original SimpleCADAPI project or as an official upstream
release.

## Why this fork exists

IrisCAD depends on behavior that is not interchangeable with an arbitrary
upstream SimpleCADAPI checkout:

- Pyodide and OCP/WASM execution in a Web Worker;
- browser-oriented mesh generation and color-aware rendering data;
- assembly execution and rendering hooks used by IrisCAD's incremental update
  pipeline;
- a versioned API catalog and BM25&vector retrieval sidecar for CAD-agent
  prompts; and
- compatibility fixes and examples exercised by the IrisCAD integration.

Upstream changes are reviewed and adopted deliberately. They are not merged or
substituted automatically. See [`UPSTREAM.md`](UPSTREAM.md) for the sync policy.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/simplecadapi/` | Python SDK and retrieval library |
| `webharness/` | Pyodide, OCP/WASM, Worker, and Three.js browser harness |
| `retrieval/` | Versioned API catalog, metadata, and document embeddings |
| `scripts/` | Retrieval build, evaluation, and sidecar commands |
| `docs/` | API and implementation documentation |
| `examples/` | Modeling, assembly, export, and verification examples |

## Local setup

Prerequisites:

- Python 3.10 or newer;
- [`uv`](https://docs.astral.sh/uv/); and
- Node.js when building the browser wheels or running the web harness.

Install the development environment from this checkout:

```bash
uv sync --group dev
```

Use this checkout directly for fork development. `pip install simplecadapi`
may install the upstream package and must not be assumed to contain the
IrisCAD-specific changes in this repository.

## Run the API retrieval sidecar

IrisCAD uses the sidecar to select a focused slice of the SimpleCADAPI
documentation for each CAD request.

```bash
uv run python scripts/serve_api_retrieval.py --host 127.0.0.1 --port 8765
```

Check that it is running:

```bash
curl http://127.0.0.1:8765/health
```

The committed catalog supports BM25 retrieval without an external embedding
service. To enable hybrid vector + BM25 retrieval, configure an
OpenAI-compatible embedding endpoint and key before starting the sidecar:

```bash
export EMBEDDING_API_KEY="<Your API key>"
export EMBEDDING_BASE_URL="https://your-provider.example/v1"
export EMBEDDING_MODEL="your-embedding-model"
```

Without a compatible key, the sidecar continues in BM25-only mode.

See [`retrieval/README.md`](retrieval/README.md) for index generation,
evaluation, and Cloud Run deployment details.

## Use with IrisCAD

Keep this repository next to the IrisCAD checkout, or pass its path explicitly:

```text
workspace/
├── IrisCAD/
└── iriscad-simplecadapi/
```

From the IrisCAD repository, start the sidecar with:

```bash
npm run sidecar -- --simplecadapi-root=../iriscad-simplecadapi
```

IrisCAD contains pinned prebuilt browser wheels for its normal local runtime.
Rebuild and copy the wheels only when developing this fork or the OCP/WASM
runtime:

```bash
npm run setup:local -- --simplecadapi-root=../iriscad-simplecadapi
```

## Build browser wheels

After `uv sync --group dev`, build the wheels consumed by the browser harness:

```bash
node webharness/test/setup-vendor.mjs
```

The generated SimpleCADAPI and OCP/WASM wheels are written under
`webharness/test/vendor/`. The IrisCAD setup command validates and copies the
matching wheel pair into its public vendor directory.

## Modeling example

```python
from pathlib import Path

import simplecadapi as scad

output = Path("out")
output.mkdir(exist_ok=True)

base = scad.make_box_rsolid(
    60.0,
    36.0,
    8.0,
    bottom_face_center=(0.0, 0.0, 0.0),
)
hole = scad.make_cylinder_rsolid(
    5.0,
    14.0,
    bottom_face_center=(0.0, 0.0, -3.0),
)
part = scad.cut_rsolid(base, hole)

scad.export_step(part, str(output / "bracket.step"))
scad.export_stl(part, str(output / "bracket.stl"))
```

More complete part, assembly, replay, and export examples are listed in
[`examples/README.md`](examples/README.md).

## Documentation

- Public API reference: [`docs/api/`](docs/api/)
- Core modeling notes: [`docs/core/`](docs/core/)
- Serialization and replay: [`docs/core/serialization/README.md`](docs/core/serialization/README.md)
- Operation graph JSON specification: [`docs/core/operation_graph_json_spec.md`](docs/core/operation_graph_json_spec.md)

## Development and verification

Run the Python test suites:

```bash
uv run python -m pytest test tests
```

Check that the package compiles:

```bash
uv run python -m compileall src/simplecadapi
```

Run an offline retrieval smoke test:

```bash
uv run python scripts/smoke_api_retrieval_offline.py
```

## License

This modified distribution retains the GNU Affero General Public License v3.0
that accompanied its closest verified upstream baseline. See [`LICENSE`](LICENSE).

The upstream project later changed its license to Apache-2.0. That later change
does not automatically relicense this fork or the modifications made here. The
license timeline and baseline evidence are recorded in [`UPSTREAM.md`](UPSTREAM.md).

When distributing a build from this repository or operating a modified version
for users over a network, review the AGPL-3.0 source-availability and notice
requirements for the exact version being distributed or deployed.
