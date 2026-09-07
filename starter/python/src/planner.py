"""
planner.py — The `/plan_path` service: converts a world-frame start/goal
into grid cells, runs A* search over the current `/map`, and converts the
resulting cell path back into world-frame poses.

Registered the same way /heapify and /heap_sort are (see
services/heap_service.py and services/provider.py): a plain
`(args) -> (values, result, status_text)` function wrapped as an
InProcessProvider. The one difference is this handler needs more than just
`args` — it needs the broker (to publish the result on /path) and the
current map (from map_store.MapStore). Both are captured by closure in
make_plan_path_handler() below, rather than changing the Handler type
everywhere else in the codebase just for this one service.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import heap
from broker import Broker
from map_store import MapStore

Cell = Tuple[int, int]

# --------------------------------------------------------------------------
# Geometry — straight out of spec/PROJECT1_ASTAR.md's "Geometry, movement,
# and optimality" section. No design decisions here, just the formulas.
# --------------------------------------------------------------------------


def world_to_cell(x: float, y: float, info: Dict[str, Any]) -> Cell:
    origin = info["origin"]["position"]
    resolution = info["resolution"]
    cell_x = math.floor((x - origin["x"]) / resolution)
    cell_y = math.floor((y - origin["y"]) / resolution)
    return int(cell_x), int(cell_y)


def cell_to_world(cell: Cell, info: Dict[str, Any]) -> Tuple[float, float]:
    origin = info["origin"]["position"]
    resolution = info["resolution"]
    cell_x, cell_y = cell
    world_x = origin["x"] + (cell_x + 0.5) * resolution
    world_y = origin["y"] + (cell_y + 0.5) * resolution
    return world_x, world_y


def in_bounds(cell: Cell, info: Dict[str, Any]) -> bool:
    cell_x, cell_y = cell
    return 0 <= cell_x < info["width"] and 0 <= cell_y < info["height"]


def is_free(cell: Cell, info: Dict[str, Any], data: List[int]) -> bool:
    if not in_bounds(cell, info):
        return False
    cell_x, cell_y = cell
    occupancy = data[cell_y * info["width"] + cell_x]
    return 0 <= occupancy < 50


def neighbors(cell: Cell, info: Dict[str, Any], data: List[int]) -> List[Cell]:
    """The 4-connected, in-bounds, free neighbors of `cell` — north, south,
    west, east, in that fixed order (order doesn't affect correctness, but
    a fixed order keeps search behavior reproducible)."""
    x, y = cell
    candidates = [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]
    return [c for c in candidates if is_free(c, info, data)]


# --------------------------------------------------------------------------
# TODO(human): implement A* search.
#
#     def a_star(start: Cell, goal: Cell, info, data) -> Optional[List[Cell]]
#
# Return an ordered list of cells from `start` to `goal` inclusive (the
# spec: "a successful path is nonempty; includes free start and goal
# cells; ... contains one cell for a free start == goal; and has the
# minimum number of moves"), or None if no path exists. Both `start` and
# `goal` are already confirmed free and in-bounds by the caller below —
# you don't need to re-check that here.
#
# Use `neighbors(cell, info, data)` above to generate valid 4-connected
# moves (each costs 1, per spec — no diagonals).
#
# The frontier-ordering requirement (spec: "the planner must call
# [/heap_sort] to order frontier priorities before choosing work to
# expand"): don't maintain an incremental push/pop heap here. Instead,
# each time you need to pick the next node to expand, call
# heap.heap_sort(...) on the frontier's current priority values (f = g +
# heuristic is the conventional A* choice — Manhattan distance,
# abs(dx) + abs(dy), is the natural admissible heuristic for 4-connected
# grid movement with unit cost) to get them in ascending order, and take
# heap_sort's returned minimum. If more than one frontier entry currently
# shares that minimum priority, the spec allows (and expects) you to apply
# your own deterministic tie-break to choose exactly one — anything
# reproducible works (e.g. insertion order, or comparing cell coordinates).
#
# You'll also need, alongside the frontier: a way to look up each
# discovered cell's best-known g-score (cost from start) so you can tell
# whether a newly-found route to an already-seen cell is actually better,
# and a way to reconstruct the final path once you reach `goal` (the
# classic approach: a dict mapping each cell to the cell you reached it
# from, walked backward from goal to start once the search succeeds, then
# reversed).
# --------------------------------------------------------------------------

class VisitedCell:
    def __init__(self, cell: Cell, manhattan_distance: int, previous_cell: VisitedCell, g_score: int):
        self.cell = cell
        self.manhattan_distance = manhattan_distance
        self.previous_cell = previous_cell
        self.g_score = g_score

def a_star(
    start: Cell, goal: Cell, info: Dict[str, Any], data: List[int]
) -> Optional[List[Cell]]:
    if start == goal:
            return [start]
    
    frontier = [(manhattan_distance(start, goal), start)]
    visited = {start: VisitedCell(start, manhattan_distance(start, goal), None, 0)}
    
    while len(frontier):
        sorted_frontier = heap.heap_sort(frontier)
        winner = sorted_frontier[0]
        winner_visited_cell = visited[winner[1]]
        if winner_visited_cell.cell == goal:
            return calculate_path(winner_visited_cell)
        frontier.remove(winner)
        visited_neighbors = [
            VisitedCell(neighbor, manhattan_distance(neighbor, goal), winner_visited_cell, winner_visited_cell.g_score + 1)
            for neighbor in neighbors(winner_visited_cell.cell, info, data)
        ]
        for neighbor in visited_neighbors:
            if neighbor.cell in visited:
                if neighbor.g_score < visited[neighbor.cell].g_score: 
                    visited[neighbor.cell] = neighbor
                    frontier.append((neighbor.manhattan_distance + neighbor.g_score, neighbor.cell))
            else:
                visited[neighbor.cell] = neighbor
                frontier.append((neighbor.manhattan_distance + neighbor.g_score, neighbor.cell))
    
    return None

def calculate_path(goal: VisitedCell) -> List[Cell]:
    path = []
    curr_cell = goal
    while curr_cell.g_score:
        path.append(curr_cell.cell)
        curr_cell = curr_cell.previous_cell
    path.append(curr_cell.cell)
    path.reverse()
    return path

def manhattan_distance(cell_1: Cell, cell_2: Cell):
    return abs(cell_1[0] - cell_2[0]) + abs(cell_1[1] - cell_2[1])

    


    
    


# --------------------------------------------------------------------------
# Argument parsing and the service handler itself — same shape as
# services/heap_service.py: pull typed values out of JSON `args`, raising
# ValueError with a specific message on anything malformed.
# --------------------------------------------------------------------------


def _pose_xy(value: Any, label: str) -> Tuple[float, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    pose = value.get("pose")
    if not isinstance(pose, dict):
        raise ValueError(f"{label}.pose must be an object")
    position = pose.get("position")
    if not isinstance(position, dict):
        raise ValueError(f"{label}.pose.position must be an object")
    coords = []
    for axis in ("x", "y"):
        value_ = position.get(axis)
        if isinstance(value_, bool) or not isinstance(value_, (int, float)):
            raise ValueError(f"{label}.pose.position.{axis} must be numeric")
        coords.append(float(value_))
    return coords[0], coords[1]


def _cell_pose(cell: Cell, info: Dict[str, Any]) -> Dict[str, Any]:
    world_x, world_y = cell_to_world(cell, info)
    return {
        "header": {"frame_id": "map"},
        "pose": {
            "position": {"x": world_x, "y": world_y, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
    }


def make_plan_path_handler(broker: Broker, store: MapStore):
    """Build the /plan_path handler. A closure (rather than a free
    function like heap_service.py's handlers) because this one needs
    `broker` (to publish on /path after success) and `store` (to read the
    current map) — neither of which fits the plain `(args) -> (values,
    result, status_text)` Handler shape services/provider.py expects.
    """

    def handler(args: Any) -> Tuple[Any, bool, str]:
        grid = store.get()
        if grid is None:
            return {}, False, "no map available yet"

        if not isinstance(args, dict):
            return {}, False, "args must be an object"
        try:
            start_x, start_y = _pose_xy(args.get("start"), "start")
            goal_x, goal_y = _pose_xy(args.get("goal"), "goal")
        except ValueError as exc:
            return {}, False, str(exc)

        info = grid["info"]
        data = grid["data"]
        start_cell = world_to_cell(start_x, start_y, info)
        goal_cell = world_to_cell(goal_x, goal_y, info)

        if not is_free(start_cell, info, data):
            return {}, False, "start is outside the map or blocked"
        if not is_free(goal_cell, info, data):
            return {}, False, "goal is outside the map or blocked"

        path_cells = a_star(start_cell, goal_cell, info, data)
        if not path_cells:
            return {}, False, "no path found"

        plan = {
            "header": {"frame_id": "map"},
            "poses": [_cell_pose(cell, info) for cell in path_cells],
        }
        # Per spec: publish the same path on /path, but only on success.
        broker.publish("/path", plan)
        return {"plan": plan}, True, ""

    return handler
