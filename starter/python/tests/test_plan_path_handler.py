"""The /plan_path handler called in-process with a fake broker. No runtime needed."""

import math

from planning_support import (FakeBroker, bfs_moves, cell_center_oracle, grid_from_rows, map_publication,
                              path_problems, plan_args, world_to_cell_oracle)

import map_store
import planner

SPEC_ROWS = ["..#.",
             "....",
             "...."]


def make_handler(rows=None, **grid_kwargs):
    broker, store = FakeBroker(), map_store.MapStore()
    grid = None
    if rows is not None:
        grid = grid_from_rows(rows, **grid_kwargs)
        store.send(map_publication(grid))
        assert store.get() is not None, "test setup: MapStore rejected a valid map"
    return planner.make_plan_path_handler(broker, store), broker, grid


def test_plan_path_handler_returns_cell_centers_and_publishes_same_path():
    handler, broker, grid = make_handler(SPEC_ROWS, resolution=0.5, origin_x=-1.0, origin_y=2.0)
    info, data = grid["info"], grid["data"]
    args = plan_args((-0.99, 2.01), (0.49, 3.49))
    values, ok, text = handler(args)
    assert ok is True, f"plan from cell (0,0) to (2,2) on the spec map should succeed: {text!r} {values}"

    plan = values["plan"]
    assert plan["header"]["frame_id"] == "map", f"plan header.frame_id must be 'map': {plan['header']}"
    cells = []
    for index, stamped in enumerate(plan["poses"]):
        position = stamped["pose"]["position"]
        orientation = stamped["pose"]["orientation"]
        cell = world_to_cell_oracle(position["x"], position["y"], info)
        cx, cy = cell_center_oracle(cell, info)
        assert math.isclose(position["x"], cx) and math.isclose(position["y"], cy), (
            f"pose {index} at ({position['x']}, {position['y']}) is not the center of cell {cell} ({cx}, {cy})")
        assert position.get("z") == 0.0, f"pose {index} must have z = 0: {position}"
        assert orientation == {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}, f"pose {index} orientation: {orientation}"
        cells.append(cell)

    problems = path_problems(cells, (0, 0), (2, 2), info, data)
    assert not problems, f"plan cells {cells} are not a valid path:\n" + "\n".join(problems)
    assert len(cells) - 1 == bfs_moves((0, 0), (2, 2), info, data) == 4, f"plan should take 4 moves: {cells}"

    assert broker.published == [("/path", plan)], f"exactly one /path publication equal to the plan: {broker.published}"

    values_again, ok_again, _ = handler(plan_args((-0.99, 2.01), (0.49, 3.49)))
    assert ok_again is True and values_again == values, "planning the same request twice must give the same plan"
    assert len(broker.published) == 2, f"each successful plan publishes /path once: {len(broker.published)}"

    values, ok, _ = handler(plan_args((-0.75, 2.25), (-0.75, 2.25)))
    assert ok is True and len(values["plan"]["poses"]) == 1, f"start == goal should give one pose: {values}"


def test_plan_path_handler_fails_cleanly_without_publishing():
    handler, broker, _ = make_handler()
    _, ok, _ = handler(plan_args((0.5, 0.5), (1.5, 0.5)))
    assert ok is False, "/plan_path must fail before any map arrives"

    rows = ["S.#..",
            "..#?.",
            "..###",
            "...#G"]
    handler, broker, _ = make_handler(rows, resolution=2.0, origin_x=10.0, origin_y=-4.0)
    center = lambda x, y: (10.0 + (x + 0.5) * 2.0, -4.0 + (y + 0.5) * 2.0)
    failures = {
        "start on a 100 cell": plan_args(center(2, 0), center(0, 0)),
        "goal on a 100 cell": plan_args(center(0, 0), center(2, 1)),
        "goal on a -1 (unknown) cell": plan_args(center(0, 0), center(3, 1)),
        "goal left of the map": plan_args(center(0, 0), (9.99, -3.0)),
        "goal above the map": plan_args(center(0, 0), (11.0, 4.0)),
        "start below the map": plan_args((11.0, -4.01), center(0, 0)),
        "unreachable goal": plan_args(center(0, 0), center(4, 3)),
        "args not an object": [1, 2],
        "args missing start": {"goal": plan_args(center(0, 0), center(1, 0))["goal"]},
        "start.pose missing": {"start": {"header": {}}, "goal": plan_args(center(0, 0), center(1, 0))["goal"]},
        "goal x is a string": {**plan_args(center(0, 0), center(1, 0)),
                               "goal": {"pose": {"position": {"x": "11", "y": -3.0}}}},
        "goal y is a bool": {**plan_args(center(0, 0), center(1, 0)),
                             "goal": {"pose": {"position": {"x": 11.0, "y": True}}}},
        "start x is NaN": {**plan_args(center(0, 0), center(1, 0)),
                           "start": {"pose": {"position": {"x": float("nan"), "y": -3.0}}}},
    }
    for reason, args in failures.items():
        try:
            values, ok, text = handler(args)
        except Exception as exc:
            raise AssertionError(f"/plan_path with {reason} raised {type(exc).__name__}: {exc}")
        assert ok is False, f"/plan_path with {reason} should fail, got {values}"
    assert broker.published == [], f"failed plans must never publish /path: {broker.published}"

    _, ok, text = handler(plan_args(center(0, 0), center(1, 2)))
    assert ok is True, f"after failures, a valid plan on the same map should still succeed: {text!r}"
