# extrude_rsolid

## API Definition

```python
def extrude_rsolid(profile: Union[Wire, Face], direction: Tuple[float, float, float], distance: ScalarLike) -> Solid
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import extrude_rsolid`

## Description

Create a solid by extruding a profile.

## Usage

Turn a flat profile into a straight solid such as a block, plate, spacer, or prism.
