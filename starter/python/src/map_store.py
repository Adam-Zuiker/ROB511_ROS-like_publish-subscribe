"""
map_store.py — Internal `/map` subscriber: keeps the runtime's current
OccupancyGrid-like map in memory so a later service (the A* planner) can
read it.

This plays the same role for *topics* that services/provider.py plays for
*services*: `MapStore` implements the `MessageSink` interface (`id` +
`send(message)`) broker.py already knows how to talk to, so
`broker.subscribe(store, "/map")` makes this object indistinguishable from
a real external TCP subscriber. Nothing in broker.py, connection.py, or
server.py needs to change to support it — the same uniformity
services/provider.py's docstring describes for services applies here to
topics.

Per the spec: "A later valid map replaces an earlier map, including your
own map." So this module's job is narrow: watch every /map publication,
validate it, and — only if it's valid — replace whatever was stored
before. An invalid publication is logged and otherwise ignored; it must
never crash the subscriber or corrupt the previously-stored map.
"""

from __future__ import annotations

import logging
import threading
import math
from typing import Any, Optional

from broker import Broker

log = logging.getLogger("map_store")


class MapStore:
    """A `MessageSink` that watches `/map` publications and keeps the most
    recently *valid* OccupancyGrid-like payload in memory.
    """

    id = "map_store"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: Optional[dict] = None

    # -- MessageSink interface -------------------------------------------

    def send(self, message: dict) -> None:
        """Called by the broker for every message delivered to this
        subscriber. The only thing we ever subscribe to is /map, so the
        only interesting message here is a publish envelope for it — the
        one `broker.subscribe()` itself sends back to confirm the
        subscription (a `status` message) is expected and simply ignored.
        """
        if message.get("op") != "publish" or message.get("topic") != "/map":
            return
        try:
            grid = validate_map(message.get("msg"))
        except ValueError as exc:
            log.warning("ignoring invalid /map publication: %s", exc)
            return
        with self._lock:
            self._current = grid
        info = grid["info"]
        log.info(
            "stored new /map: %dx%d @ resolution %s",
            info["width"], info["height"], info["resolution"],
        )

    # -- Reader interface, for the future planner -------------------------

    def get(self) -> Optional[dict]:
        """Return the current map, or None if /map has never published a
        valid one yet. Safe to call from any thread."""
        with self._lock:
            return self._current

def fail(message: str) -> None:
    raise ValueError(message)


def integer(value: Any, label: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{label} must be an integer")
    if positive and value <= 0:
        fail(f"{label} must be positive")


def number(value: Any, label: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be numeric")
    if not math.isfinite(value):
        fail(f"{label} must be finite")
    if positive and value <= 0:
        fail(f"{label} must be positive")


def object_field(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


# --------------------------------------------------------------------------
# TODO(human): implement validate_map(msg) below.
#
# Check it against the "/map format" rules in spec/PROJECT1_ASTAR.md:
#   - msg must be an object with header, info, and data.
#   - info must have resolution (positive number), width and height
#     (positive integers), and origin (an object with a position.x and
#     position.y — at minimum; feel free to check position.z/orientation
#     too if you want to be thorough).
#   - data must be a list with exactly width * height entries, and every
#     entry must be an integer (bool excluded — same trap as
#     services/heap_service.py's _extract_numbers, see its comment).
#
# Raise ValueError with a short, specific message for the first problem
# you find (mirror _extract_numbers's style in heap_service.py). On
# success, return the validated map object unchanged so send() above can
# store it directly.
#
# Deliberately out of scope here: checking that the map has "at least two
# 4-connected free cells." That's a planning-time concern (the A* planner
# will simply fail to find a route on a map with no usable free cells,
# which is correct /plan_path failure behavior) — not something this
# storage layer needs to reject on receipt, since it doesn't run the
# search itself.
# --------------------------------------------------------------------------


def validate_map(msg: Any) -> dict:
    map_message = object_field(msg, "msg")
    object_field(map_message.get("header"), "header")
    info = object_field(map_message.get("info"), "info")
    number(info.get("resolution"), "info.resolution", positive=True)
    integer(info.get("width"), "info.width", positive=True)
    integer(info.get("height"), "info.height", positive=True)
    origin = object_field(info.get("origin"), "info.origin")
    position = object_field(origin.get("position"), "info.origin.position")
    number(position.get("x"), "info.origin.position.x")
    number(position.get("y"), "info.origin.position.y")

    data = map_message.get("data")
    if not isinstance(data, list):
        fail("data must be an array")
    expected = info["width"] * info["height"]
    if len(data) != expected:
        fail(f"data must contain width * height entries ({expected})")
    for index, occupancy in enumerate(data):
        integer(occupancy, f"data[{index}]")
    return map_message


def register(broker: Broker) -> MapStore:
    """Create a MapStore and subscribe it to /map on `broker`.

    Called once from main.py at startup, the same way
    register_builtin_services() wires up /heapify and /heap_sort — see
    that function in services/__init__.py for the parallel.
    """
    store = MapStore()
    broker.subscribe(store, "/map")
    return store
