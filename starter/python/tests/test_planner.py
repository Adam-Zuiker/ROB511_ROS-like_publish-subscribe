"""
tests/test_planner.py — Tests for src/planner.py.

Two layers, mirroring the split the rest of this test suite already uses:
  - Pure, in-process unit tests for the geometry helpers and a_star()
    itself (fast, no server — same style as tests/test_heap.py).
  - Black-box /plan_path and /path coverage over the real TCP/JSON
    protocol, reusing GatewayTestCase/RawClient from test_gateway.py
    rather than duplicating that harness (same style as that file's
    TestHeapServicesOverTheWire).

Run with:  python3 -m unittest discover -s tests   (from starter/python/)
"""

from __future__ import annotations

import random
import sys
import time
import unittest
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import planner  # noqa: E402
from test_gateway import GatewayTestCase, RawClient  # noqa: E402


def _pose(x: float, y: float) -> Dict[str, Any]:
    """A minimal PoseStamped-like /plan_path argument at world (x, y)."""
    return {
        "header": {"frame_id": "map"},
        "pose": {
            "position": {"x": x, "y": y, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        },
    }


def _bfs_shortest_len(start, goal, info, data) -> Optional[int]:
    """Reference shortest-path length, independent of a_star/heap_sort —
    used only to check a_star's *optimality*, never to check itself.
    """
    if start == goal:
        return 1
    seen = {start}
    frontier = deque([(start, 1)])
    while frontier:
        cell, dist = frontier.popleft()
        for n in planner.neighbors(cell, info, data):
            if n == goal:
                return dist + 1
            if n not in seen:
                seen.add(n)
                frontier.append((n, dist + 1))
    return None


def _assert_valid_path(testcase: unittest.TestCase, path, start, goal, info, data) -> None:
    testcase.assertTrue(path, "path must be nonempty")
    testcase.assertEqual(path[0], start, "path must start at start")
    testcase.assertEqual(path[-1], goal, "path must end at goal")
    for cell in path:
        testcase.assertTrue(planner.is_free(cell, info, data), f"{cell} is not free/in-bounds")
    for a, b in zip(path, path[1:]):
        step = (abs(a[0] - b[0]), abs(a[1] - b[1]))
        testcase.assertIn(step, ((1, 0), (0, 1)), f"invalid step {a} -> {b} (not one 4-connected move)")


# A small fixed grid, reused by every test below instead of a fresh
# hand-rolled grid per test, and deliberately independent of the real
# maps/student_map.json (which is free to change without breaking these):
#
#   x: 0 1 2 3 4 5
# y=0: . . # . # .
# y=1: . . # . . #
# y=2: . . # . . .
# y=3: . . # . . .
# y=4: . . . . . .
#
# Column x=2 is walled for y=0..3 (free only at y=4), so crossing it
# requires detouring through the bottom row. (5,0) is walled off on both
# of its in-bounds neighbors — (4,0) and (5,1) — so it's free but
# unreachable from anywhere else on the grid.
GRID_WIDTH, GRID_HEIGHT = 6, 5
GRID_INFO: Dict[str, Any] = {
    "resolution": 1.0,
    "width": GRID_WIDTH,
    "height": GRID_HEIGHT,
    "origin": {"position": {"x": 0.0, "y": 0.0, "z": 0.0}},
}
GRID_DATA: List[int] = [
    0, 0, 100, 0, 100, 0,
    0, 0, 100, 0, 0, 100,
    0, 0, 100, 0, 0, 0,
    0, 0, 100, 0, 0, 0,
    0, 0, 0, 0, 0, 0,
]


# --------------------------------------------------------------------------
# Geometry helpers — pure functions, no server needed.
# --------------------------------------------------------------------------

class TestGeometry(unittest.TestCase):
    def test_world_to_cell_and_back_round_trips_to_cell_center(self) -> None:
        for cell in [(0, 0), (3, 2), (5, 4)]:
            world_x, world_y = planner.cell_to_world(cell, GRID_INFO)
            self.assertEqual(planner.world_to_cell(world_x, world_y, GRID_INFO), cell)

    def test_world_to_cell_uses_floor_not_round(self) -> None:
        # Any point in [x, x+1) must map to cell x -- e.g. 0.99 still
        # floors down to cell 0, and negative coordinates floor *away*
        # from zero (-0.01 is cell -1, not cell 0).
        self.assertEqual(planner.world_to_cell(0.99, 0.01, GRID_INFO), (0, 0))
        self.assertEqual(planner.world_to_cell(-0.01, 0.0, GRID_INFO), (-1, 0))

    def test_nonzero_origin_and_resolution(self) -> None:
        # The worked example from spec/PROJECT1_ASTAR.md's /map format section.
        info = {
            "resolution": 0.5, "width": 4, "height": 3,
            "origin": {"position": {"x": -1.0, "y": 2.0, "z": 0.0}},
        }
        self.assertEqual(planner.world_to_cell(-0.75, 2.25, info), (0, 0))

    def test_in_bounds(self) -> None:
        self.assertTrue(planner.in_bounds((0, 0), GRID_INFO))
        self.assertTrue(planner.in_bounds((5, 4), GRID_INFO))
        self.assertFalse(planner.in_bounds((-1, 0), GRID_INFO))
        self.assertFalse(planner.in_bounds((6, 0), GRID_INFO))
        self.assertFalse(planner.in_bounds((0, 5), GRID_INFO))

    def test_is_free_respects_occupancy_threshold_and_bounds(self) -> None:
        self.assertTrue(planner.is_free((0, 0), GRID_INFO, GRID_DATA))
        self.assertFalse(planner.is_free((2, 0), GRID_INFO, GRID_DATA))  # wall
        self.assertFalse(planner.is_free((6, 0), GRID_INFO, GRID_DATA))  # out of bounds

    def test_neighbors_excludes_blocked_and_out_of_bounds(self) -> None:
        # (0,0) is a corner: only 2 of its 4 candidate neighbors even exist.
        self.assertEqual(set(planner.neighbors((0, 0), GRID_INFO, GRID_DATA)), {(0, 1), (1, 0)})
        # (3,0) is adjacent to the wall at (2,0); that neighbor must be excluded.
        self.assertNotIn((2, 0), planner.neighbors((3, 0), GRID_INFO, GRID_DATA))


# --------------------------------------------------------------------------
# a_star() itself — in-process, no server needed.
# --------------------------------------------------------------------------

class TestAStarSearch(unittest.TestCase):
    def test_start_equals_goal_returns_single_cell(self) -> None:
        self.assertEqual(planner.a_star((1, 1), (1, 1), GRID_INFO, GRID_DATA), [(1, 1)])

    def test_finds_optimal_path_around_the_wall(self) -> None:
        start, goal = (0, 0), (5, 2)
        path = planner.a_star(start, goal, GRID_INFO, GRID_DATA)
        _assert_valid_path(self, path, start, goal, GRID_INFO, GRID_DATA)
        expected = _bfs_shortest_len(start, goal, GRID_INFO, GRID_DATA)
        self.assertEqual(len(path), expected)
        # Sanity check this test actually exercises the detour: Manhattan
        # distance alone would suggest a much shorter straight line.
        manhattan_cells = abs(goal[0] - start[0]) + abs(goal[1] - start[1]) + 1
        self.assertGreater(len(path), manhattan_cells)

    def test_sealed_pocket_is_unreachable(self) -> None:
        self.assertIsNone(planner.a_star((0, 0), (5, 0), GRID_INFO, GRID_DATA))

    def test_optimality_against_bfs_on_random_obstacle_courses(self) -> None:
        # A smaller, seeded version of the randomized search used to catch
        # the original greedy-best-first bug during development, kept
        # here as a permanent regression guard (sized down to keep the
        # suite fast: ~60 trials on 8x8 grids instead of 400 on 12x12).
        rng = random.Random(1)
        info = {
            "resolution": 1.0, "width": 8, "height": 8,
            "origin": {"position": {"x": 0.0, "y": 0.0}},
        }
        checked = 0
        for _ in range(60):
            data = [100 if rng.random() < 0.3 else 0 for _ in range(64)]
            free = [(x, y) for y in range(8) for x in range(8) if planner.is_free((x, y), info, data)]
            if len(free) < 2:
                continue
            start, goal = rng.sample(free, 2)
            expected = _bfs_shortest_len(start, goal, info, data)
            if expected is None:
                continue
            path = planner.a_star(start, goal, info, data)
            self.assertIsNotNone(path, f"expected a path for start={start} goal={goal}")
            self.assertEqual(
                len(path), expected,
                f"non-optimal path for start={start} goal={goal}: "
                f"got {len(path)} cells, bfs-optimal is {expected}",
            )
            checked += 1
        self.assertGreater(checked, 20, "too few reachable random cases to be a meaningful check")


# --------------------------------------------------------------------------
# /plan_path and /path over the real TCP/JSON protocol.
# --------------------------------------------------------------------------

class TestPlanPathBeforeAnyMap(GatewayTestCase):
    """Its own runtime subprocess — GatewayTestCase.setUpClass is per
    subclass, not shared — so /map is guaranteed never to have been
    published here, exercising the spec's "before a map arrives" case."""

    def test_fails_cleanly_with_no_map(self) -> None:
        client = self.make_client()
        client.send({
            "op": "call_service", "service": "/plan_path", "id": "no-map",
            "args": {"start": _pose(0.5, 0.5), "goal": _pose(1.5, 1.5)},
        })
        response = client.read_message()
        self.assertFalse(response["result"])


class TestPlanPathOverTheWire(GatewayTestCase):
    """One shared runtime + one map, published once for the whole class —
    same sharing pattern test_gateway.py's TestHeapServicesOverTheWire
    uses for its runtime."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        publisher = RawClient()
        publisher.send({"op": "advertise", "topic": "/map", "type": "nav_msgs/OccupancyGrid"})
        publisher.send({
            "op": "publish", "topic": "/map",
            "msg": {"header": {"frame_id": "map"}, "info": GRID_INFO, "data": GRID_DATA},
        })
        time.sleep(0.2)  # let map_store process it before any test calls /plan_path
        publisher.close()

    def _plan(self, client: RawClient, start, goal, call_id: str, tolerance: float | None = None) -> Dict[str, Any]:
        args: Dict[str, Any] = {"start": _pose(*start), "goal": _pose(*goal)}
        if tolerance is not None:
            args["tolerance"] = tolerance
        client.send({"op": "call_service", "service": "/plan_path", "id": call_id, "args": args})
        return client.read_message(timeout=3.0)

    def test_successful_plan_matches_a_star_and_publishes_path(self) -> None:
        client = self.make_client()
        path_sub = self.make_client()
        path_sub.send({"op": "subscribe", "topic": "/path", "type": "nav_msgs/Path"})
        path_sub.read_message()  # subscribe ack

        response = self._plan(client, (0.5, 0.5), (5.5, 2.5), "plan-1")
        self.assertTrue(response["result"])
        plan = response["values"]["plan"]
        self.assertEqual(plan["header"]["frame_id"], "map")
        poses = plan["poses"]
        self.assertEqual((poses[0]["pose"]["position"]["x"], poses[0]["pose"]["position"]["y"]), (0.5, 0.5))
        self.assertEqual((poses[-1]["pose"]["position"]["x"], poses[-1]["pose"]["position"]["y"]), (5.5, 2.5))
        for pose in poses:
            self.assertEqual(pose["pose"]["position"]["z"], 0.0)
            self.assertEqual(pose["pose"]["orientation"], {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0})

        published = path_sub.read_message(timeout=2.0)
        self.assertEqual(published["op"], "publish")
        self.assertEqual(published["topic"], "/path")
        self.assertEqual(published["msg"], plan)

    def test_tolerance_is_accepted_and_does_not_change_the_result(self) -> None:
        # Spec: "Accept tolerance; it need not alter Project 1 planning."
        client = self.make_client()
        with_tol = self._plan(client, (0.5, 0.5), (1.5, 0.5), "with-tol", tolerance=0.75)
        without_tol = self._plan(client, (0.5, 0.5), (1.5, 0.5), "without-tol")
        self.assertTrue(with_tol["result"])
        self.assertTrue(without_tol["result"])
        self.assertEqual(with_tol["values"]["plan"], without_tol["values"]["plan"])

    def test_blocked_start_fails_without_publishing_path(self) -> None:
        client = self.make_client()
        path_sub = self.make_client()
        path_sub.send({"op": "subscribe", "topic": "/path", "type": "nav_msgs/Path"})
        path_sub.read_message()

        response = self._plan(client, (2.5, 0.5), (0.5, 0.5), "blocked-start")  # (2,0) is a wall
        self.assertFalse(response["result"])
        path_sub.expect_no_message()

    def test_blocked_goal_fails(self) -> None:
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (2.5, 0.5), "blocked-goal")  # (2,0) is a wall
        self.assertFalse(response["result"])

    def test_unreachable_goal_fails(self) -> None:
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (5.5, 0.5), "unreachable")  # sealed pocket at (5,0)
        self.assertFalse(response["result"])

    def test_start_equals_goal_returns_single_pose(self) -> None:
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (0.5, 0.5), "same-cell")
        self.assertTrue(response["result"])
        self.assertEqual(len(response["values"]["plan"]["poses"]), 1)

    def test_malformed_args_fail_cleanly_without_killing_the_service(self) -> None:
        client = self.make_client()
        client.send({
            "op": "call_service", "service": "/plan_path", "id": "bad-1",
            "args": {"start": "not-an-object", "goal": _pose(0.5, 0.5)},
        })
        bad = client.read_message()
        self.assertFalse(bad["result"])

        # A bad request must not have wedged the in-process provider's
        # worker thread -- the service must still work for the next caller.
        good = self._plan(client, (0.5, 0.5), (1.5, 0.5), "good-1")
        self.assertTrue(good["result"])


class TestPlanPathMapReplacement(GatewayTestCase):
    """Its own runtime + its own initial map, isolated from
    TestPlanPathOverTheWire so publishing a *second* map here can't affect
    that class's assumptions about the walled grid (and vice versa)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._publish_map(GRID_DATA)

    @classmethod
    def _publish_map(cls, data: List[int]) -> None:
        publisher = RawClient()
        publisher.send({"op": "advertise", "topic": "/map", "type": "nav_msgs/OccupancyGrid"})
        publisher.send({
            "op": "publish", "topic": "/map",
            "msg": {"header": {"frame_id": "map"}, "info": GRID_INFO, "data": data},
        })
        time.sleep(0.2)
        publisher.close()

    def test_later_map_replaces_earlier_one(self) -> None:
        client = self.make_client()
        start, goal = (0.5, 0.5), (5.5, 2.5)

        def plan(call_id: str) -> Dict[str, Any]:
            client.send({
                "op": "call_service", "service": "/plan_path", "id": call_id,
                "args": {"start": _pose(*start), "goal": _pose(*goal)},
            })
            return client.read_message(timeout=3.0)

        before = plan("before-replace")
        self.assertTrue(before["result"])
        walled_length = len(before["values"]["plan"]["poses"])

        self._publish_map([0] * (GRID_WIDTH * GRID_HEIGHT))  # fully open now

        after = plan("after-replace")
        self.assertTrue(after["result"])
        open_length = len(after["values"]["plan"]["poses"])

        self.assertLess(open_length, walled_length, "removing the wall should shorten the plan")


if __name__ == "__main__":
    unittest.main()
