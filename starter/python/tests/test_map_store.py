"""Direct tests of src/map_store.py: validate_map() and MapStore. No runtime needed."""

import copy

from planning_support import grid_from_rows, map_publication

import map_store

SPEC_MAP = {"header": {"frame_id": "map"},
            "info": {"resolution": 0.5, "width": 4, "height": 3,
                     "origin": {"position": {"x": -1.0, "y": 2.0, "z": 0.0},
                                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}},
            "data": [0, 0, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0]}


def broken(change):
    grid = copy.deepcopy(SPEC_MAP)
    change(grid)
    return grid


def test_validate_map_accepts_spec_example_and_edge_values():
    grid = copy.deepcopy(SPEC_MAP)
    assert map_store.validate_map(grid) is grid, "validate_map should return the same map object it was given"

    edge = grid_from_rows(["?#.", "..."], resolution=1, origin_x=-5, origin_y=-7.5)
    edge["data"][2] = 127
    assert map_store.validate_map(edge) is edge, "int resolution, negative origin, and -1/100/127 occupancies are valid"

    single = grid_from_rows(["."], resolution=0.01)
    assert map_store.validate_map(single) is single, "a 1x1 map with resolution 0.01 is valid"


def test_validate_map_rejects_each_malformed_field():
    cases = {
        "msg not an object": [1, 2, 3],
        "msg is None": None,
        "missing header": broken(lambda g: g.pop("header")),
        "header not an object": broken(lambda g: g.update(header="map")),
        "missing info": broken(lambda g: g.pop("info")),
        "resolution zero": broken(lambda g: g["info"].update(resolution=0)),
        "resolution negative": broken(lambda g: g["info"].update(resolution=-0.5)),
        "resolution string": broken(lambda g: g["info"].update(resolution="0.5")),
        "resolution bool": broken(lambda g: g["info"].update(resolution=True)),
        "resolution infinite": broken(lambda g: g["info"].update(resolution=float("inf"))),
        "resolution nan": broken(lambda g: g["info"].update(resolution=float("nan"))),
        "width zero": broken(lambda g: g["info"].update(width=0)),
        "width zero with matching empty data": broken(lambda g: (g["info"].update(width=0), g.update(data=[]))),
        "height zero with matching empty data": broken(lambda g: (g["info"].update(height=0), g.update(data=[]))),
        "width float": broken(lambda g: g["info"].update(width=4.0)),
        "width bool": broken(lambda g: g["info"].update(width=True)),
        "height negative": broken(lambda g: g["info"].update(height=-3)),
        "height missing": broken(lambda g: g["info"].pop("height")),
        "origin missing": broken(lambda g: g["info"].pop("origin")),
        "origin.position missing": broken(lambda g: g["info"]["origin"].pop("position")),
        "origin.position.x string": broken(lambda g: g["info"]["origin"]["position"].update(x="-1")),
        "origin.position.y missing": broken(lambda g: g["info"]["origin"]["position"].pop("y")),
        "data missing": broken(lambda g: g.pop("data")),
        "data not a list": broken(lambda g: g.update(data="000")),
        "data too short": broken(lambda g: g["data"].pop()),
        "data too long": broken(lambda g: g["data"].append(0)),
        "data has a float": broken(lambda g: g["data"].__setitem__(5, 0.5)),
        "data has a bool": broken(lambda g: g["data"].__setitem__(11, False)),
        "data has a string": broken(lambda g: g["data"].__setitem__(0, "0")),
        "data has None": broken(lambda g: g["data"].__setitem__(3, None)),
    }
    for reason, grid in cases.items():
        try:
            map_store.validate_map(grid)
        except ValueError:
            continue
        except Exception as exc:
            raise AssertionError(f"validate_map with {reason} raised {type(exc).__name__} instead of ValueError: {exc}")
        raise AssertionError(f"validate_map accepted a map with {reason}: {grid}")


def test_map_store_keeps_latest_valid_map_and_ignores_bad_or_unrelated_messages():
    store = map_store.MapStore()
    assert store.get() is None, "a new MapStore must have no map"

    first = copy.deepcopy(SPEC_MAP)
    store.send(map_publication(first))
    assert store.get() == first, f"a valid /map publication should be stored, got {store.get()}"

    store.send(map_publication(broken(lambda g: g["info"].update(width=0))))
    assert store.get() == first, "an invalid /map must not replace the stored map"
    store.send({"op": "publish", "topic": "/map"})
    assert store.get() == first, "a /map publish with no msg must not replace the stored map"

    other = grid_from_rows(["..", ".."])
    store.send({"op": "publish", "topic": "/not_map", "msg": other})
    assert store.get() == first, "a publication on another topic must be ignored"
    store.send({"op": "status", "topic": "/map", "msg": other})
    assert store.get() == first, "a non-publish op must be ignored"

    second = grid_from_rows(["...", "#.."], resolution=0.25, origin_x=3.0)
    store.send(map_publication(second))
    assert store.get() == second, f"a later valid /map must replace the earlier one, got {store.get()}"
