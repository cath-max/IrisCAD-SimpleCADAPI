# Upstream provenance

This repository is a modified distribution of **SimpleCADAPI**, originally
developed by NiJingzhe and contributors.

- Upstream repository: <https://github.com/NiJingzhe/SimpleCADAPI>
- Upstream project name: `SimpleCADAPI`
- Original author recorded in the package metadata: Ni Jingzhe
- Local import commit: `e385ab6c5495903a9b21c67a09aedc1ff33c444f`
- Local import date: 2026-07-22 15:41:37 +0800
- Closest verified upstream baseline:
  `41099b595acb57e00d50b7a738bae5c85cf0c953`
- Baseline date: 2026-07-11 01:36:56 +0800
- Baseline description: `Merge pull request #12 from NiJingzhe/dev`

## How the baseline was identified

The local repository was initially imported as a new root commit, so its Git
history does not contain an upstream parent. The baseline above must therefore
be treated as the closest verified source snapshot, not as a proven Git
ancestor.

To identify it, the complete tree of the local import commit was compared by
path and Git blob ID against every available upstream commit dated before
2026-07-23 across the fetched upstream refs. Commit `41099b5` was the best
match (two other parent/merge-side commits had the same effective tree):

- 567 files in the local import tree;
- 554 files in the upstream baseline tree;
- 537 paths with byte-identical Git blobs;
- 15 common paths modified in the local import;
- 15 paths present only in the local import;
- 2 paths present only in the upstream baseline;
- Jaccard similarity over path-plus-content matches: approximately 0.92.

This evidence indicates that the local root commit was based on, or very close
to, the upstream `41099b5` source state with additional local changes. It does
not establish that `41099b5` was the literal checkout used for the import.

## Differences already present at the local import

The following common paths differed from the closest upstream baseline:

```text
.gitignore
docs/api/README.md
pyproject.toml
skills/simplecadapi/references/docs/api/README.md
src/simplecadapi/__init__.py
src/simplecadapi/_mesh.py
src/simplecadapi/kernel/ocp_booleans.py
src/simplecadapi/kernel/ocp_cast.py
src/simplecadapi/kernel/ocp_features.py
src/simplecadapi/kernel/ocp_mesh.py
src/simplecadapi/kernel/ocp_properties.py
src/simplecadapi/kernel/ocp_topology.py
src/simplecadapi/kernel/ocp_transforms.py
src/simplecadapi/operations.py
uv.lock
```

The following paths were present in the local import but not in the closest
upstream baseline:

```text
docs/agent_api_index.md
docs/MVP_AGENT_CONTRACT.md
src/simplecadapi/_render_colors.py
src/simplecadapi/kernel/_ocp_compat.py
src/simplecadapi/mesh_export.py
src/simplecadapi/webharness.py
webharness/src/compositeGrid.mjs
webharness/src/pyodideEngine.mjs
webharness/src/threeRenderer.mjs
webharness/src/types.mjs
webharness/src/worker.mjs
webharness/test/index.html
webharness/test/playground.html
webharness/test/server.mjs
webharness/test/setup-vendor.mjs
```

The following paths were present in the closest upstream baseline but absent
from the local import:

```text
docs/api/render_screenshot_rpath.md
skills/simplecadapi/references/docs/api/render_screenshot_rpath.md
```

All commits after the local root commit are part of this fork's recorded
development history and should be consulted for later modifications.

## License timeline

The upstream project changed licenses over time:

- On 2026-07-10, upstream commit
  `c281928c34524cb6ec76998c958d73872518c458` changed the project from
  GPL-2.0 to AGPL-3.0.
- The closest upstream baseline `41099b5` used AGPL-3.0.
- The `LICENSE` file in local import commit `e385ab6` is byte-identical to the
  `LICENSE` file in upstream baseline `41099b5` (Git blob
  `2ca153723832ed64a71f540c5cf69ce430c46212`).
- On 2026-08-13, after this fork's initial import, upstream commit
  `02d4bb8e561eeca339bf3b8fca49a671be6e98c5` relicensed the upstream project
  under Apache-2.0.

This fork currently retains the AGPL-3.0 license that accompanied its closest
verified source baseline. The later upstream Apache-2.0 change has not been
automatically applied to this fork. Any future license change should be made
deliberately, with the relevant upstream notices and the provenance of local
modifications reviewed first.

## Upstream synchronization policy

IrisCAD depends on behavior added or modified in this fork. Upstream updates
must not be merged or substituted automatically.

For each future upstream sync:

1. record the exact upstream commit being evaluated;
2. review license and notice changes at that commit;
3. compare API, assembly, serialization, web-harness, worker, meshing, and
   retrieval behavior;
4. run the fork's compatibility and IrisCAD integration tests;
5. merge or cherry-pick only after compatibility is established; and
6. record the adopted upstream commit and material conflict resolutions in
   this file or the release notes.

## Attribution

SimpleCADAPI was originally created by NiJingzhe and upstream contributors.
This fork contains modifications made for the IrisCAD agent and browser CAD
runtime. The fork is independent and is not represented as an official
upstream release or as endorsed by the upstream maintainers.
