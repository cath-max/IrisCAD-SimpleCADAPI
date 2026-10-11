# revolve_rsolid

## API Definition

```python
def revolve_rsolid(profile: Union[Wire, Face], axis: Tuple[float, float, float] = (0, 0, 1), angle: ScalarLike = 360, origin: Tuple[float, float, float] = (0, 0, 0)) -> Solid
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import revolve_rsolid`

## Description

Create a solid by revolving a profile around an axis.

## Usage

Create an axisymmetric turned solid by spinning a profile around a centerline.
