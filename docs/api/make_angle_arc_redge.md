# make_angle_arc_redge

## API Definition

```python
def make_angle_arc_redge(center: Tuple[float, float, float], radius: ScalarLike, start_angle: ScalarLike, end_angle: ScalarLike, normal: Tuple[float, float, float] = (0, 0, 1)) -> Edge
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import make_angle_arc_redge`

## Description

Create an arc edge from a center, radius, and angle range.

## Usage

Create a circular arc from center, radius, and angle for curved routes and rounded outlines.
