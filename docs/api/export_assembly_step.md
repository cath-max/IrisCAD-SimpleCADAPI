# export_assembly_step

## API Definition

```python
def export_assembly_step(assembly: Assembly, filename: str) -> None
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import export_assembly_step`

## Description

Export a direct-Part Assembly as an XCAF STEP file while preserving its assembly
name, part names, component names, and component placements.

## Usage

Use this for a simple production-style assembly STEP, rather than flattening an
Assembly into a Compound for preview or STL export.

## Limits

The initial exporter supports only direct `Part` components. Nested
subassemblies, colors, materials, and assembly constraints are not exported.
