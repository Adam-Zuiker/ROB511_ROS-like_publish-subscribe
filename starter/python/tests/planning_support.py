"""Shared helpers for the planning tests. Not a test file itself (name does not start with test_).

Everything here is deliberately independent of src/planner.py, so a bug in the
planner cannot also corrupt the reference answers the tests compare against.
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

Cell = Tuple[int, int]

FREE_CHARS = {".": 0, "S": 0, "G": 0}
BLOCKED_CHARS = {"#": 100, "?": -1}


def make_info(width: int, height: int, resolution: float = 1.0,
              origin_x: float = 0.0, origin_y: float = 0.0) -> Dict[str, Any]:
    return {
        "resolution": resolution,
        "width": width,
        "height": height,
        "origin": {
            "position": {"x": origin_x, "y": origin_y, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
    }


def grid_from_rows(rows: Sequence[str], resolution: float = 1.0,
                   origin_x: float = 0.0, origin_y: float = 0.0) -> Dict[str, Any]:
    """rows[y][x] is cell (x, y). '.', 'S', 'G' are free; '#' is 100; '?' is -1 (unknown)."""
    codes = {**FREE_CHARS, **BLOCKED_CHARS}
    width = len(rows[0])
    assert all(len(row) == width for row in rows), "grid_from_rows: ragged rows"
    data = [codes[ch] for row in rows for ch in row]
    return {"header": {"frame_id": "map"},
            "info": make_info(width, len(rows), resolution, origin_x, origin_y),
            "data": data}


def find_char(rows: Sequence[str], ch: str) -> Cell:
    for y, row in enumerate(rows):
        if ch in row:
            return row.index(ch), y
    raise ValueError(f"{ch!r} not in grid")


def oracle_free(cell: Cell, info: Dict[str, Any], data: List[int]) -> bool:
    x, y = cell
    if not (0 <= x < info["width"] and 0 <= y < info["height"]):
        return False
    return 0 <= data[y * info["width"] + x] < 50


def bfs_moves(start: Cell, goal: Cell, info: Dict[str, Any], data: List[int]) -> Optional[int]:
    """Minimum number of 4-connected moves from start to goal, or None if unreachable."""
    if not (oracle_free(start, info, data) and oracle_free(goal, info, data)):
        return None
    dist = {start: 0}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        if cell == goal:
            return dist[cell]
        x, y = cell
        for nxt in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)):
            if nxt not in dist and oracle_free(nxt, info, data):
                dist[nxt] = dist[cell] + 1
                queue.append(nxt)
    return None


def path_problems(path: Optional[List[Cell]], start: Cell, goal: Cell,
                  info: Dict[str, Any], data: List[int]) -> List[str]:
    """Every way `path` breaks the spec's path rules; an empty list means it is valid.

    Optimality (minimum moves) is checked separately against bfs_moves().
    """
    problems: List[str] = []
    if not path:
        return [f"path is empty or None: {path!r}"]
    if path[0] != start:
        problems.append(f"path starts at {path[0]}, expected start {start}")
    if path[-1] != goal:
        problems.append(f"path ends at {path[-1]}, expected goal {goal}")
    for index, cell in enumerate(path):
        if not oracle_free(cell, info, data):
            problems.append(f"path[{index}]={cell} is out of bounds or blocked")
    for index, (a, b) in enumerate(zip(path, path[1:])):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            problems.append(f"step {index}: {a} -> {b} is not a single 4-connected move")
    return problems


def pose(x: float, y: float) -> Dict[str, Any]:
    return {"header": {"frame_id": "map"},
            "pose": {"position": {"x": x, "y": y, "z": 0.0},
                     "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}


def plan_args(start_xy: Tuple[float, float], goal_xy: Tuple[float, float]) -> Dict[str, Any]:
    return {"start": pose(*start_xy), "goal": pose(*goal_xy), "tolerance": 0.0}


def world_to_cell_oracle(x: float, y: float, info: Dict[str, Any]) -> Cell:
    import math
    origin = info["origin"]["position"]
    return (math.floor((x - origin["x"]) / info["resolution"]),
            math.floor((y - origin["y"]) / info["resolution"]))


def cell_center_oracle(cell: Cell, info: Dict[str, Any]) -> Tuple[float, float]:
    origin = info["origin"]["position"]
    return (origin["x"] + (cell[0] + 0.5) * info["resolution"],
            origin["y"] + (cell[1] + 0.5) * info["resolution"])


class FakeBroker:
    """Stands in for broker.Broker: records every publish instead of routing it."""

    def __init__(self) -> None:
        self.published: List[Tuple[str, Any]] = []

    def publish(self, topic: str, msg: Any, *args: Any, **kwargs: Any) -> None:
        self.published.append((topic, msg))


def map_publication(grid: Any) -> Dict[str, Any]:
    return {"op": "publish", "topic": "/map", "msg": grid}


def is_min_heap(values: Sequence[Any]) -> bool:
    return all(values[(i - 1) // 2] <= values[i] for i in range(1, len(values)))
