"""Version parsing and comparison utilities."""

import re
from typing import List, Tuple


def parse_version(v: str) -> Tuple[Tuple[int, ...], int]:
    """
    Convert a tool version string to a sortable tuple.

    Returns a 2-tuple (base_tuple, galaxy_n) for comparison.
      '2.1.0+galaxy1'    -> ((2, 1, 0), 1)
      '0.7.17.5+galaxy3' -> ((0, 7, 17, 5), 3)
      '1.9.1'            -> ((1, 9, 1), 0)
    """
    if "+" in v:
        base, galaxy_part = v.split("+", 1)
        m = re.match(r"galaxy(\d+)$", galaxy_part)
        galaxy_n = int(m.group(1)) if m else 0
    else:
        base = v
        galaxy_n = 0

    parts = []
    for seg in base.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)

    return (tuple(parts), galaxy_n)


def mismatch_direction(wanted: str, available: List[str]) -> str:
    """
    Determine direction of version gap between wanted and available versions.

    Returns: "installed older" | "installed newer" | "mixed" | "unknown"
    """
    wt = parse_version(wanted)
    older = [v for v in available if parse_version(v) < wt]
    newer = [v for v in available if parse_version(v) > wt]
    equal = [v for v in available if parse_version(v) == wt]

    if equal:
        return "unknown"
    if older and not newer:
        return "installed older"
    if newer and not older:
        return "installed newer"
    return "mixed"
