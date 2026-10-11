# make_spline_rwire

## API Definition

```python
def make_spline_rwire(*, control_points: Sequence[Sequence[ScalarLike]], degree: int = 3, knots: Optional[Sequence[ScalarLike]] = None, multiplicities: Optional[Sequence[int]] = None, weights: Optional[Sequence[ScalarLike]] = None, periodic: bool = False) -> Wire
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import make_spline_rwire`

## Description

Create a wire containing one exact B-spline edge.

## Usage

Create a ready-to-use smooth spline path for sweeping, lofting, or routing.
