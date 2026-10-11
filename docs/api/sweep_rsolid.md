# sweep_rsolid

## API Definition

```python
def sweep_rsolid(profile: Face, path: Wire, is_frenet: bool = False) -> Solid
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import sweep_rsolid`

## Description

Create a solid by sweeping a profile along a path.

## Usage

Create a solid tube, pipe, duct, rail, or curved blade by carrying a profile along a guide path.
