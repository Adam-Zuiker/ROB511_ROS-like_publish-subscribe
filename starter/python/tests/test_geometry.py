"""Direct tests of the grid geometry helpers in src/planner.py. No runtime needed."""

import math

from planning_support import make_info

import planner

SPEC_INFO = make_info(4, 3, resolution=0.5, origin_x=-1.0, origin_y=2.0)


def test_world_to_cell_floors_with_offset_origin_and_half_meter_cells():
    cases = [
        ((-0.75, 2.25), (0, 0)),
        ((-1.0, 2.0), (0, 0)),
        ((-0.5, 2.5), (1, 1)),
        ((-0.51, 2.49), (0, 0)),
        ((0.99, 3.49), (3, 2)),
        ((0.25, 3.25), (2, 2)),
        ((-1.01, 1.99), (-1, -1)),
        ((1.0, 3.5), (4, 3)),
    ]
    for (x, y), expected in cases:
        got = planner.world_to_cell(x, y, SPEC_INFO)
        assert got == expected, f"world_to_cell({x}, {y}) with origin (-1, 2), res 0.5: got {got}, expected {expected}"

    info = make_info(5, 5, resolution=2.0, origin_x=3.0, origin_y=-4.0)
    got = planner.world_to_cell(8.9, -3.9, info)
    assert got == (2, 0), f"world_to_cell(8.9, -3.9) with origin (3, -4), res 2: got {got}, expected (2, 0)"


def test_cell_to_world_returns_center_of_cell():
    cases = [((0, 0), (-0.75, 2.25)), ((3, 2), (0.75, 3.25)), ((2, 1), (0.25, 2.75))]
    for cell, (ex, ey) in cases:
        wx, wy = planner.cell_to_world(cell, SPEC_INFO)
        assert math.isclose(wx, ex) and math.isclose(wy, ey), (
            f"cell_to_world({cell}) with origin (-1, 2), res 0.5: got ({wx}, {wy}), expected ({ex}, {ey})")
    for x in range(4):
        for y in range(3):
            back = planner.world_to_cell(*planner.cell_to_world((x, y), SPEC_INFO), SPEC_INFO)
            assert back == (x, y), f"cell ({x}, {y}) -> world -> cell gave {back}"


def test_in_bounds_rejects_negative_and_edge_indices():
    inside = [(0, 0), (3, 0), (0, 2), (3, 2), (1, 1)]
    outside = [(-1, 0), (0, -1), (4, 0), (0, 3), (4, 3), (-1, -1), (3, 3), (4, 2)]
    for cell in inside:
        assert planner.in_bounds(cell, SPEC_INFO), f"{cell} is inside a 4x3 map"
    for cell in outside:
        assert not planner.in_bounds(cell, SPEC_INFO), f"{cell} is outside a 4x3 map"


def test_is_free_threshold_and_row_major_indexing():
    info = make_info(3, 2)
    data = [0, 49, 50,
            1, 100, -1]
    expected = {(0, 0): True, (1, 0): True, (2, 0): False,
                (0, 1): True, (1, 1): False, (2, 1): False}
    for cell, free in expected.items():
        got = planner.is_free(cell, info, data)
        assert got is free, f"is_free({cell}) on data {data} (width 3): got {got}, expected {free}"
    for cell in [(3, 0), (-1, 1), (0, 2), (0, -1)]:
        assert planner.is_free(cell, info, data) is False, f"out-of-bounds {cell} must not be free"

    wide = make_info(4, 2)
    wide_data = [0, 100, 0, 0,
                 0, 0, 0, 100]
    assert planner.is_free((1, 0), wide, wide_data) is False, "cell (1,0) is data[1]=100 (row-major x + y*width)"
    assert planner.is_free((0, 1), wide, wide_data) is True, "cell (0,1) is data[4]=0 (row-major x + y*width)"
    assert planner.is_free((3, 1), wide, wide_data) is False, "cell (3,1) is data[7]=100 (row-major x + y*width)"


def test_neighbors_are_four_connected_free_and_in_bounds():
    info = make_info(3, 3)
    open_data = [0] * 9
    got = planner.neighbors((1, 1), info, open_data)
    assert sorted(got) == [(0, 1), (1, 0), (1, 2), (2, 1)], f"center of open 3x3 should have 4 neighbors, got {got}"
    got = planner.neighbors((0, 0), info, open_data)
    assert sorted(got) == [(0, 1), (1, 0)], f"corner (0,0) should have 2 neighbors, got {got}"
    got = planner.neighbors((2, 2), info, open_data)
    assert sorted(got) == [(1, 2), (2, 1)], f"corner (2,2) should have 2 neighbors, got {got}"

    walled = [0, 100, 0,
              -1, 0, 50,
              0, 0, 0]
    got = planner.neighbors((1, 1), info, walled)
    assert sorted(got) == [(1, 2)], f"(1,1) with N=100, W=-1, E=50 blocked should only reach (1,2), got {got}"
    got = planner.neighbors((0, 0), info, walled)
    assert got == [], f"(0,0) boxed in by (1,0)=100 and (0,1)=-1 should have no neighbors, got {got}"


def test_manhattan_distance_sums_absolute_axis_differences():
    cases = [(((0, 0), (0, 0)), 0), (((1, 2), (4, -2)), 7), (((4, -2), (1, 2)), 7),
             (((-3, 5), (2, 1)), 9), (((0, 0), (0, 6)), 6), (((5, 0), (0, 0)), 5)]
    for (a, b), expected in cases:
        got = planner.manhattan_distance(a, b)
        assert got == expected, f"manhattan_distance({a}, {b}) = {got}, expected {expected}"
