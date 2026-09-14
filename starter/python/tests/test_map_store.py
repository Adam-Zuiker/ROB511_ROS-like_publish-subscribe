"""
tests/test_map_store.py — Unit tests for src/map_store.py: validate_map()
and MapStore, run entirely in-process (no sockets, no gateway) — same
style as tests/test_heap.py.

Run with:  python3 -m unittest discover -s tests   (from starter/python/)

INVALID_CASES checks not just that validate_map *rejects* a bad map, but
that it rejects it *for the right reason* -- a mutation that made every
malformed input fail with the same wrong message (or the wrong field
entirely) would still pass a bare `assertRaises(ValueError)`, so each
case also asserts the exception text names the specific broken field.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import map_store  # noqa: E402

VALID_MAP = {
    "header": {"frame_id": "map"},
    "info": {
        "resolution": 1.0,
        "width": 2,
        "height": 2,
        "origin": {"position": {"x": 0.0, "y": 0.0, "z": 0.0}},
    },
    "data": [0, 0, 0, 0],
}


def _without(d: dict, key: str) -> dict:
    return {k: v for k, v in d.items() if k != key}


def _with_info(**overrides) -> dict:
    return {**VALID_MAP, "info": {**VALID_MAP["info"], **overrides}}


# (label, malformed map, substring the ValueError message must contain)
INVALID_CASES = [
    ("payload not an object", "not an object", "must be an object"),
    ("missing header", _without(VALID_MAP, "header"), "header"),
    ("non-object header", {**VALID_MAP, "header": "nope"}, "header"),
    ("missing info", _without(VALID_MAP, "info"), "info"),
    ("non-object info", {**VALID_MAP, "info": "nope"}, "info"),
    ("non-positive resolution", _with_info(resolution=-1.0), "info.resolution"),
    ("non-numeric resolution", _with_info(resolution="1.0"), "info.resolution"),
    ("non-finite resolution", _with_info(resolution=float("inf")), "info.resolution"),
    ("bool width", _with_info(width=True), "info.width"),
    ("non-integer width", _with_info(width=2.5), "info.width"),
    ("non-positive width", _with_info(width=0), "info.width"),
    ("bool height", _with_info(height=True), "info.height"),
    ("non-positive height", _with_info(height=-2), "info.height"),
    ("missing origin", {**VALID_MAP, "info": _without(VALID_MAP["info"], "origin")}, "info.origin"),
    ("non-object origin", _with_info(origin="nope"), "info.origin"),
    ("missing position", _with_info(origin={}), "info.origin.position"),
    ("non-object position", _with_info(origin={"position": "nope"}), "info.origin.position"),
    (
        "non-numeric position.x",
        _with_info(origin={"position": {"x": "nope", "y": 0.0}}),
        "info.origin.position.x",
    ),
    (
        "non-numeric position.y",
        _with_info(origin={"position": {"x": 0.0, "y": "nope"}}),
        "info.origin.position.y",
    ),
    ("missing data", _without(VALID_MAP, "data"), "data"),
    ("non-list data", {**VALID_MAP, "data": "nope"}, "data"),
    ("wrong data length", {**VALID_MAP, "data": [0, 0, 0]}, "data"),
    ("non-integer cell", {**VALID_MAP, "data": [0.5, 0, 0, 0]}, "data[0]"),
    ("bool cell", {**VALID_MAP, "data": [True, 0, 0, 0]}, "data[0]"),
]


class TestValidateMap(unittest.TestCase):
    def test_valid_map_returns_unchanged(self) -> None:
        self.assertEqual(map_store.validate_map(VALID_MAP), VALID_MAP, "a valid map must pass through unmodified")

    def test_rejects_invalid_maps_for_the_specific_stated_reason(self) -> None:
        for label, bad_map, expected_substring in INVALID_CASES:
            with self.subTest(label=label):
                with self.assertRaises(ValueError, msg=f"{label}: expected a ValueError, none was raised"):
                    map_store.validate_map(bad_map)

    def test_rejection_messages_name_the_specific_broken_field(self) -> None:
        # Separate from the test above so a *missing* exception (failure
        # above) and a *wrong-reason* exception (failure here) are
        # reported as distinguishable failures rather than one blended one.
        for label, bad_map, expected_substring in INVALID_CASES:
            with self.subTest(label=label):
                try:
                    map_store.validate_map(bad_map)
                except ValueError as exc:
                    self.assertIn(
                        expected_substring,
                        str(exc),
                        f"{label}: error message {str(exc)!r} doesn't mention {expected_substring!r} "
                        f"-- check may be firing for the wrong field, or with the wrong message",
                    )
                else:
                    self.fail(f"{label}: validate_map accepted an invalid map instead of raising")


class TestMapStore(unittest.TestCase):
    def _publish(self, store: "map_store.MapStore", msg) -> None:
        store.send({"op": "publish", "topic": "/map", "msg": msg})

    def test_valid_publish_is_stored(self) -> None:
        store = map_store.MapStore()
        self.assertIsNone(store.get(), "a fresh MapStore must start with no map")
        self._publish(store, VALID_MAP)
        self.assertEqual(store.get(), VALID_MAP, "a valid publish must be stored verbatim")

    def test_invalid_publish_does_not_clobber_last_good_map(self) -> None:
        store = map_store.MapStore()
        self._publish(store, VALID_MAP)
        bad = {**VALID_MAP, "info": {**VALID_MAP["info"], "resolution": -1.0}}
        self._publish(store, bad)
        self.assertEqual(store.get(), VALID_MAP, "an invalid publish must not replace the last valid map")

    def test_missing_msg_field_does_not_crash(self) -> None:
        # No "msg" key at all -- message.get("msg") is None, which must be
        # cleanly rejected by validate_map, not raise something uncaught.
        store = map_store.MapStore()
        store.send({"op": "publish", "topic": "/map"})
        self.assertIsNone(store.get(), "a publish with no msg field must be ignored, not crash or half-store")

    def test_later_valid_map_replaces_earlier_one(self) -> None:
        store = map_store.MapStore()
        self._publish(store, VALID_MAP)
        second = {**VALID_MAP, "data": [100, 100, 0, 0]}
        self._publish(store, second)
        self.assertEqual(store.get(), second, "a later valid publish must replace the earlier stored map")

    def test_ignores_messages_for_other_topics(self) -> None:
        store = map_store.MapStore()
        store.send({"op": "publish", "topic": "/not_map", "msg": VALID_MAP})
        self.assertIsNone(store.get(), "a publish on a different topic must not be stored as the map")

    def test_ignores_non_publish_messages(self) -> None:
        store = map_store.MapStore()
        store.send({"op": "status", "level": "info", "msg": "subscribed to /map"})
        self.assertIsNone(store.get(), "a non-publish message must never be treated as a map")


if __name__ == "__main__":
    unittest.main()
