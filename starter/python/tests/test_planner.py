"""
tests/test_planner.py — Tests for src/planner.py.

Two layers, mirroring the split the rest of this test suite already uses:
  - Pure, in-process unit tests for the geometry helpers, argument
    validation, and a_star() itself (fast, no server — same style as
    tests/test_heap.py).
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
            with self.subTest(cell=cell):
                world_x, world_y = planner.cell_to_world(cell, GRID_INFO)
                self.assertEqual(
                    planner.world_to_cell(world_x, world_y, GRID_INFO), cell,
                    f"cell_to_world({cell}) -> world_to_cell(...) must round-trip back to {cell}",
                )

    def test_world_to_cell_uses_floor_not_round(self) -> None:
        # Any point in [x, x+1) must map to cell x -- e.g. 0.99 still
        # floors down to cell 0, and negative coordinates floor *away*
        # from zero (-0.01 is cell -1, not cell 0).
        self.assertEqual(
            planner.world_to_cell(0.99, 0.01, GRID_INFO), (0, 0),
            "0.99 is still inside cell 0's [0,1) span -- must not round up to cell 1",
        )
        self.assertEqual(
            planner.world_to_cell(-0.01, 0.0, GRID_INFO), (-1, 0),
            "a small negative coordinate must floor to cell -1, not truncate to cell 0",
        )

    def test_nonzero_origin_and_resolution(self) -> None:
        # The worked example from spec/PROJECT1_ASTAR.md's /map format section.
        info = {
            "resolution": 0.5, "width": 4, "height": 3,
            "origin": {"position": {"x": -1.0, "y": 2.0, "z": 0.0}},
        }
        self.assertEqual(
            planner.world_to_cell(-0.75, 2.25, info), (0, 0),
            "spec's own worked example: (-0.75, 2.25) with origin (-1, 2), resolution 0.5 must be cell (0, 0)",
        )

    def test_cell_to_world_applies_half_cell_offset(self) -> None:
        # Cell centers, not corners: cell (2, 3) at resolution 1 with a
        # zero origin must land at (2.5, 3.5), not (2.0, 3.0).
        self.assertEqual(
            planner.cell_to_world((2, 3), GRID_INFO), (2.5, 3.5),
            "cell_to_world must return the cell *center* (+0.5 * resolution), not its corner",
        )

    def test_in_bounds(self) -> None:
        self.assertTrue(planner.in_bounds((0, 0), GRID_INFO), "(0,0) is the top-left corner, must be in bounds")
        self.assertTrue(planner.in_bounds((5, 4), GRID_INFO), "(5,4) is the bottom-right corner, must be in bounds")
        self.assertFalse(planner.in_bounds((-1, 0), GRID_INFO), "negative x must be out of bounds")
        self.assertFalse(planner.in_bounds((6, 0), GRID_INFO), "x == width must be out of bounds (0-indexed)")
        self.assertFalse(planner.in_bounds((0, 5), GRID_INFO), "y == height must be out of bounds (0-indexed)")

    def test_is_free_respects_bounds(self) -> None:
        self.assertFalse(planner.is_free((6, 0), GRID_INFO, GRID_DATA), "out-of-bounds cells must never be free")
        self.assertFalse(planner.is_free((-1, 0), GRID_INFO, GRID_DATA), "negative coordinates must never be free")

    def test_is_free_occupancy_threshold_boundary(self) -> None:
        # Spec: "A cell is free exactly when 0 <= occupancy < 50."
        data = [49, 50, -1, 0]  # width=2, height=2
        info = {**GRID_INFO, "width": 2, "height": 2}
        self.assertTrue(planner.is_free((0, 0), info, data), "occupancy 49 must be free (just under the threshold)")
        self.assertFalse(planner.is_free((1, 0), info, data), "occupancy 50 must be blocked (the threshold itself)")
        self.assertFalse(planner.is_free((0, 1), info, data), "occupancy -1 (unknown) must be blocked")
        self.assertTrue(planner.is_free((1, 1), info, data), "occupancy 0 must be free")

    def test_neighbors_excludes_blocked_and_out_of_bounds(self) -> None:
        # (0,0) is a corner: only 2 of its 4 candidate neighbors even exist.
        self.assertEqual(
            set(planner.neighbors((0, 0), GRID_INFO, GRID_DATA)), {(0, 1), (1, 0)},
            "a corner cell must only report its 2 in-bounds neighbors",
        )
        # (3,0) is adjacent to the wall at (2,0); that neighbor must be excluded.
        self.assertNotIn(
            (2, 0), planner.neighbors((3, 0), GRID_INFO, GRID_DATA),
            "a blocked neighbor must never appear in neighbors()'s result",
        )

    def test_neighbors_interior_cell_reports_all_four(self) -> None:
        # (4,3) is fully interior with all 4 neighbors free -- catches a
        # mutation that drops or duplicates one of the 4 candidate offsets.
        result = planner.neighbors((4, 3), GRID_INFO, GRID_DATA)
        self.assertEqual(
            set(result), {(4, 2), (4, 4), (3, 3), (5, 3)},
            "an interior free cell must report exactly its 4 orthogonal neighbors",
        )
        self.assertEqual(len(result), 4, "neighbors() must not return duplicate entries")


class TestManhattanDistance(unittest.TestCase):
    def test_zero_for_identical_cells(self) -> None:
        self.assertEqual(planner.manhattan_distance((3, 4), (3, 4)), 0)

    def test_matches_sum_of_axis_differences(self) -> None:
        # A direct, hand-computed check independent of any heap/search
        # logic -- catches a mutation that drops abs() (breaking on
        # negative deltas) or swaps + for something else.
        self.assertEqual(
            planner.manhattan_distance((0, 0), (3, 4)), 7,
            "manhattan_distance((0,0),(3,4)) must be |3-0| + |4-0| = 7",
        )
        self.assertEqual(
            planner.manhattan_distance((5, 5), (2, 1)), 7,
            "manhattan_distance must use abs() -- must be symmetric regardless of which cell is 'ahead'",
        )


class TestPoseValidation(unittest.TestCase):
    """Direct coverage of _pose_xy's validation branches -- previously
    only exercised incidentally through wire-level /plan_path tests,
    which don't hit every branch (missing pose, missing position,
    non-finite numbers) explicitly."""

    def test_accepts_well_formed_pose(self) -> None:
        self.assertEqual(planner._pose_xy(_pose(1.5, -2.5), "start"), (1.5, -2.5))

    def test_rejects_non_object(self) -> None:
        with self.assertRaises(ValueError, msg="a non-object pose argument must be rejected"):
            planner._pose_xy("not an object", "start")

    def test_rejects_missing_pose_key(self) -> None:
        with self.assertRaises(ValueError, msg="a missing 'pose' key must be rejected"):
            planner._pose_xy({"header": {"frame_id": "map"}}, "start")

    def test_rejects_missing_position_key(self) -> None:
        with self.assertRaises(ValueError, msg="a missing 'position' key must be rejected"):
            planner._pose_xy({"pose": {}}, "start")

    def test_rejects_non_numeric_coordinate(self) -> None:
        with self.assertRaises(ValueError, msg="a string coordinate must be rejected"):
            planner._pose_xy({"pose": {"position": {"x": "nope", "y": 0.0}}}, "start")

    def test_rejects_bool_coordinate(self) -> None:
        # bool is a subclass of int -- {"x": true} must not silently pass as x=1.
        with self.assertRaises(ValueError, msg="a bool coordinate must be rejected, not treated as 0/1"):
            planner._pose_xy({"pose": {"position": {"x": True, "y": 0.0}}}, "start")

    def test_rejects_nan_and_infinity(self) -> None:
        for label, bad_value in [("NaN", float("nan")), ("+inf", float("inf")), ("-inf", float("-inf"))]:
            with self.subTest(value=label):
                with self.assertRaises(ValueError, msg=f"{label} must be rejected as a coordinate"):
                    planner._pose_xy({"pose": {"position": {"x": bad_value, "y": 0.0}}}, "start")


# --------------------------------------------------------------------------
# a_star() itself — in-process, no server needed.
# --------------------------------------------------------------------------

class TestAStarSearch(unittest.TestCase):
    def test_start_equals_goal_returns_single_cell(self) -> None:
        self.assertEqual(
            planner.a_star((1, 1), (1, 1), GRID_INFO, GRID_DATA), [(1, 1)],
            "start == goal must return a single-cell path, not None or an empty list",
        )

    def test_finds_optimal_path_around_the_wall(self) -> None:
        start, goal = (0, 0), (5, 2)
        path = planner.a_star(start, goal, GRID_INFO, GRID_DATA)
        _assert_valid_path(self, path, start, goal, GRID_INFO, GRID_DATA)
        expected = _bfs_shortest_len(start, goal, GRID_INFO, GRID_DATA)
        self.assertEqual(
            len(path), expected, f"path must be BFS-optimal length ({expected} cells), got {len(path)}"
        )
        # Sanity check this test actually exercises the detour: Manhattan
        # distance alone would suggest a much shorter straight line.
        manhattan_cells = abs(goal[0] - start[0]) + abs(goal[1] - start[1]) + 1
        self.assertGreater(
            len(path), manhattan_cells,
            "this test is supposed to force a detour around a wall -- if it's failing on this line, "
            "the test grid itself no longer has the wall blocking the direct route",
        )

    def test_sealed_pocket_is_unreachable(self) -> None:
        self.assertIsNone(
            planner.a_star((0, 0), (5, 0), GRID_INFO, GRID_DATA),
            "(5,0) is walled off from every other cell -- a_star must return None, not a path or an error",
        )

    def test_deterministic_across_repeated_calls(self) -> None:
        # Same start/goal/map, called twice -- must return the identical
        # path both times. A broken/nondeterministic tie-break (e.g. one
        # driven by set iteration order or an unstable sort) could return
        # a different, still-valid-length path each run, which none of
        # the optimality checks above would ever catch since they only
        # check *length*, not the exact route.
        start, goal = (0, 0), (5, 2)
        first = planner.a_star(start, goal, GRID_INFO, GRID_DATA)
        second = planner.a_star(start, goal, GRID_INFO, GRID_DATA)
        self.assertEqual(
            first, second, "a_star must be deterministic: identical inputs must produce the identical path"
        )

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
        self.assertFalse(response["result"], "a /plan_path call before any /map has been published must fail")


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
        self.assertTrue(response["result"], f"expected a successful plan, got: {response}")
        plan = response["values"]["plan"]
        self.assertEqual(plan["header"]["frame_id"], "map", "plan.header.frame_id must be 'map'")
        poses = plan["poses"]
        self.assertEqual(
            (poses[0]["pose"]["position"]["x"], poses[0]["pose"]["position"]["y"]), (0.5, 0.5),
            "the plan's first pose must be the start cell's center",
        )
        self.assertEqual(
            (poses[-1]["pose"]["position"]["x"], poses[-1]["pose"]["position"]["y"]), (5.5, 2.5),
            "the plan's last pose must be the goal cell's center",
        )
        for i, pose in enumerate(poses):
            self.assertEqual(pose["pose"]["position"]["z"], 0.0, f"pose[{i}]: z must be zero per spec")
            self.assertEqual(
                pose["pose"]["orientation"], {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                f"pose[{i}]: orientation must be identity per spec",
            )

        published = path_sub.read_message(timeout=2.0)
        self.assertEqual(published["op"], "publish", "a successful plan must publish on /path")
        self.assertEqual(published["topic"], "/path")
        self.assertEqual(
            published["msg"], plan, "the /path publication must be the exact same plan as the service response"
        )

    def test_tolerance_is_accepted_and_does_not_change_the_result(self) -> None:
        # Spec: "Accept tolerance; it need not alter Project 1 planning."
        client = self.make_client()
        with_tol = self._plan(client, (0.5, 0.5), (1.5, 0.5), "with-tol", tolerance=0.75)
        without_tol = self._plan(client, (0.5, 0.5), (1.5, 0.5), "without-tol")
        self.assertTrue(with_tol["result"], "a request that includes tolerance must still succeed")
        self.assertTrue(without_tol["result"])
        self.assertEqual(
            with_tol["values"]["plan"], without_tol["values"]["plan"],
            "including tolerance must not change the resulting plan at all",
        )

    def test_blocked_start_fails_without_publishing_path(self) -> None:
        client = self.make_client()
        path_sub = self.make_client()
        path_sub.send({"op": "subscribe", "topic": "/path", "type": "nav_msgs/Path"})
        path_sub.read_message()

        response = self._plan(client, (2.5, 0.5), (0.5, 0.5), "blocked-start")  # (2,0) is a wall
        self.assertFalse(response["result"], "a blocked start cell must fail the plan")
        path_sub.expect_no_message()  # raises its own descriptive AssertionError on failure

    def test_blocked_goal_fails(self) -> None:
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (2.5, 0.5), "blocked-goal")  # (2,0) is a wall
        self.assertFalse(response["result"], "a blocked goal cell must fail the plan")

    def test_out_of_bounds_goal_fails(self) -> None:
        # Distinct from "blocked": this coordinate maps to a cell entirely
        # outside the grid, not merely an occupied one inside it.
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (999.5, 999.5), "out-of-bounds")
        self.assertFalse(response["result"], "a goal far outside the map's bounds must fail cleanly, not crash")

    def test_unreachable_goal_fails(self) -> None:
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (5.5, 0.5), "unreachable")  # sealed pocket at (5,0)
        self.assertFalse(response["result"], "a free but disconnected goal must fail as unreachable")

    def test_start_equals_goal_returns_single_pose(self) -> None:
        client = self.make_client()
        response = self._plan(client, (0.5, 0.5), (0.5, 0.5), "same-cell")
        self.assertTrue(response["result"], "start == goal on a free cell must succeed")
        self.assertEqual(
            len(response["values"]["plan"]["poses"]), 1, "start == goal must produce exactly one pose"
        )

    def test_malformed_args_fail_cleanly_without_killing_the_service(self) -> None:
        client = self.make_client()
        client.send({
            "op": "call_service", "service": "/plan_path", "id": "bad-1",
            "args": {"start": "not-an-object", "goal": _pose(0.5, 0.5)},
        })
        bad = client.read_message()
        self.assertFalse(bad["result"], "a malformed 'start' argument must fail cleanly, not crash the service")

        # A bad request must not have wedged the in-process provider's
        # worker thread -- the service must still work for the next caller.
        good = self._plan(client, (0.5, 0.5), (1.5, 0.5), "good-1")
        self.assertTrue(good["result"], "a malformed prior request must not prevent a later valid one from working")


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

        self.assertLess(
            open_length, walled_length,
            f"removing the wall should shorten the plan (was {walled_length} poses, now {open_length}) "
            f"-- if unchanged, /plan_path may be planning against a stale cached map",
        )


if __name__ == "__main__":
    unittest.main()
