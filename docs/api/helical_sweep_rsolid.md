# helical_sweep_rsolid

## API Definition

```python
def helical_sweep_rsolid(profile: Wire, pitch: float, height: float, radius: float, center: Tuple[float, float, float] = (0, 0, 0), dir: Tuple[float, float, float] = (0, 0, 1)) -> Solid
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import helical_sweep_rsolid`

## Description

Create a solid by sweeping a profile along a helical path.

## Usage

Create a spring, coil, helical feature, or threaded-looking solid from a profile.

## Profile placement

Position the profile at the helix start in the current coordinate system, with its plane normal aligned to the starting tangent. For `center=(0,0,0)` and `dir=(0,0,1)`, the start is `(radius,0,0)` and the tangent is proportional to `(0, radius, pitch/(2*pi))`. The API does not translate or automatically orient the profile. For other centers or directions, use the actual helix start and tangent. This contract is identical with and without `GraphSession`.
