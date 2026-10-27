"""End to end over TCP: publish /map, call /plan_path, receive /path. Needs `make run` in another terminal."""

import math
import time

from planning_support import bfs_moves, cell_center_oracle, grid_from_rows, path_problems, plan_args
from rosbridge_client import Rosbridge


def test_runtime_publish_map_then_plan_path_and_receive_path():
    rows = ["......",
            ".####.",
            ".#..#.",
            ".#.##.",
            "......"]
    grid = grid_from_rows(rows, resolution=0.25, origin_x=100.0, origin_y=-50.0)
    info, data = grid["info"], grid["data"]
    start, goal = (2, 2), (0, 0)
    args = plan_args(cell_center_oracle(start, info), cell_center_oracle(goal, info))

    with Rosbridge() as ros:
        ros.subscribe("/path", "nav_msgs/Path")
        ros.advertise("/map", "nav_msgs/OccupancyGrid")
        ros.publish("/map", grid)

        deadline = time.monotonic() + 5.0
        while True:
            reply = ros.call_service("/plan_path", args)
            if reply.get("result") is True or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        assert reply.get("result") is True, f"/plan_path never succeeded after publishing /map: {reply}"

        plan = reply["values"]["plan"]
        published = ros.next_message("/path", timeout=5)
        assert published == plan, f"/path publication should equal the returned plan:\n{published}\nvs\n{plan}"

    cells = []
    for stamped in plan["poses"]:
        p = stamped["pose"]["position"]
        cell = (math.floor((p["x"] - 100.0) / 0.25), math.floor((p["y"] + 50.0) / 0.25))
        cx, cy = cell_center_oracle(cell, info)
        assert math.isclose(p["x"], cx) and math.isclose(p["y"], cy), f"pose {p} is not a cell center"
        cells.append(cell)
    problems = path_problems(cells, start, goal, info, data)
    assert not problems, f"runtime plan {cells} is invalid:\n" + "\n".join(problems)
    best = bfs_moves(start, goal, info, data)
    assert len(cells) - 1 == best, f"runtime plan takes {len(cells) - 1} moves, minimum is {best}: {cells}"
