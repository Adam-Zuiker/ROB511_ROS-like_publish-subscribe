"""Direct tests of planner.a_star(). No runtime needed."""

import random

from planning_support import bfs_moves, find_char, grid_from_rows, oracle_free, path_problems

import planner


def plan(rows, start=None, goal=None):
    grid = grid_from_rows(rows)
    start = start if start is not None else find_char(rows, "S")
    goal = goal if goal is not None else find_char(rows, "G")
    return planner.a_star(start, goal, grid["info"], grid["data"]), start, goal, grid


def assert_optimal(rows, start=None, goal=None):
    path, start, goal, grid = plan(rows, start, goal)
    shown = "\n".join(rows)
    problems = path_problems(path, start, goal, grid["info"], grid["data"])
    assert not problems, f"invalid path {path} from {start} to {goal} on\n{shown}\n" + "\n".join(problems)
    best = bfs_moves(start, goal, grid["info"], grid["data"])
    assert len(path) - 1 == best, f"path has {len(path) - 1} moves, minimum is {best}: {path} on\n{shown}"
    return path


def test_a_star_start_equals_goal_and_adjacent_goal():
    rows = ["...", "...", "..."]
    path, *_ = plan(rows, (1, 1), (1, 1))
    assert path == [(1, 1)], f"start == goal must return exactly one cell, got {path}"
    path, *_ = plan(rows, (0, 0), (1, 0))
    assert path == [(0, 0), (1, 0)], f"adjacent goal must return [start, goal], got {path}"
    path, *_ = plan(rows, (2, 2), (2, 1))
    assert path == [(2, 2), (2, 1)], f"adjacent goal (north) must return [start, goal], got {path}"


def test_a_star_detours_around_wall_with_minimum_moves():
    rows = ["S....",
            "####.",
            "G...."]
    path = assert_optimal(rows)
    expected = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (4, 1), (4, 2), (3, 2), (2, 2), (1, 2), (0, 2)]
    assert path == expected, f"the only shortest route goes through the gap at (4,1): got {path}"


def test_a_star_escapes_cup_where_heuristic_points_the_wrong_way():
    rows = ["...G...",
            ".#####.",
            ".#...#.",
            ".#.S.#.",
            ".#...#.",
            ".##.##.",
            "......."]
    path = assert_optimal(rows)
    assert len(path) - 1 == 15, f"escaping the cup through (3,5) takes 15 moves, got {len(path) - 1}: {path}"


def test_a_star_returns_none_when_goal_is_sealed_off_by_walls_or_unknown():
    walled = [".....",
              ".###.",
              ".#G#.",
              ".###.",
              "S...."]
    path, *_ = plan(walled)
    assert path is None, f"goal enclosed by 100s must be unreachable, got {path}"

    unknown = ["S.???",
               "..?G?",
               "..???"]
    path, *_ = plan(unknown)
    assert path is None, f"goal enclosed by -1 (unknown) cells must be unreachable, got {path}"

    path, *_ = plan(walled, start=(2, 2), goal=(0, 0))
    assert path is None, f"start enclosed by walls must not reach the goal, got {path}"


def test_a_star_matches_bfs_on_random_maps():
    rng = random.Random(511)
    for trial in range(300):
        width, height = rng.randint(2, 12), rng.randint(2, 12)
        density = rng.choice([0.0, 0.1, 0.25, 0.35, 0.45])
        rows = ["".join("#" if rng.random() < density else "." for _ in range(width)) for _ in range(height)]
        grid = grid_from_rows(rows)
        free = [(x, y) for y in range(height) for x in range(width) if oracle_free((x, y), grid["info"], grid["data"])]
        if not free:
            continue
        start, goal = rng.choice(free), rng.choice(free)
        best = bfs_moves(start, goal, grid["info"], grid["data"])
        path = planner.a_star(start, goal, grid["info"], grid["data"])
        shown = "\n".join(rows)
        if best is None:
            assert path is None, f"trial {trial}: {start}->{goal} is unreachable but a_star returned {path} on\n{shown}"
            continue
        problems = path_problems(path, start, goal, grid["info"], grid["data"])
        assert not problems, f"trial {trial}: invalid path {path} from {start} to {goal} on\n{shown}\n" + "\n".join(problems)
        assert len(path) - 1 == best, f"trial {trial}: {len(path) - 1} moves, minimum is {best}, {start}->{goal} on\n{shown}"
