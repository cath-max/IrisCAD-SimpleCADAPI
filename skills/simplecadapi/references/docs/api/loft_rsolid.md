# loft_rsolid

## API Definition

```python
def loft_rsolid(profiles: List[Wire], ruled: bool = False) -> Solid
```

*Source: operations.py*

## Import Surface

- top-level: `from simplecadapi import loft_rsolid`

## Description

Create a solid by lofting multiple profiles. Could be used for tapers and
straight conical transitions between sections when ``ruled=True``; use a
smooth loft when cross-sections should blend rather than form a ruled cone.
