"""
tests/test_map_store.py — Unit tests for src/map_store.py: validate_map()
and MapStore, run entirely in-process (no sockets, no gateway) — same
style as tests/test_heap.py.

Run with:  python3 -m unittest discover -s tests   (from starter/python/)
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


class TestValidateMap(unittest.TestCase):
    def test_valid_map_returns_unchanged(self) -> None:
        self.assertEqual(map_store.validate_map(VALID_MAP), VALID_MAP)

    def test_rejects_non_object_payload(self) -> None:
        with self.assertRaises(ValueError):
            map_store.validate_map("not an object")

    def test_rejects_missing_data(self) -> None:
        bad = {k: v for k, v in VALID_MAP.items() if k != "data"}
        with self.assertRaises(ValueError):
            map_store.validate_map(bad)

    def test_rejects_wrong_data_length(self) -> None:
        bad = {**VALID_MAP, "data": [0, 0, 0]}
        with self.assertRaises(ValueError):
            map_store.validate_map(bad)

    def test_rejects_non_positive_resolution(self) -> None:
        bad = {**VALID_MAP, "info": {**VALID_MAP["info"], "resolution": -1.0}}
        with self.assertRaises(ValueError):
            map_store.validate_map(bad)

    def test_rejects_bool_width(self) -> None:
        # bool is a subclass of int in Python -- {"width": true} must not
        # silently pass as width=1.
        bad = {**VALID_MAP, "info": {**VALID_MAP["info"], "width": True}}
        with self.assertRaises(ValueError):
            map_store.validate_map(bad)

    def test_rejects_non_integer_cell(self) -> None:
        bad = {**VALID_MAP, "data": [0.5, 0, 0, 0]}
        with self.assertRaises(ValueError):
            map_store.validate_map(bad)

    def test_rejects_non_finite_resolution(self) -> None:
        bad = {**VALID_MAP, "info": {**VALID_MAP["info"], "resolution": float("inf")}}
        with self.assertRaises(ValueError):
            map_store.validate_map(bad)


class TestMapStore(unittest.TestCase):
    def _publish(self, store: "map_store.MapStore", msg) -> None:
        store.send({"op": "publish", "topic": "/map", "msg": msg})

    def test_valid_publish_is_stored(self) -> None:
        store = map_store.MapStore()
        self.assertIsNone(store.get())
        self._publish(store, VALID_MAP)
        self.assertEqual(store.get(), VALID_MAP)

    def test_invalid_publish_does_not_clobber_last_good_map(self) -> None:
        store = map_store.MapStore()
        self._publish(store, VALID_MAP)
        bad = {**VALID_MAP, "info": {**VALID_MAP["info"], "resolution": -1.0}}
        self._publish(store, bad)
        self.assertEqual(store.get(), VALID_MAP, "an invalid publish must not replace the last valid map")

    def test_later_valid_map_replaces_earlier_one(self) -> None:
        store = map_store.MapStore()
        self._publish(store, VALID_MAP)
        second = {**VALID_MAP, "data": [100, 100, 0, 0]}
        self._publish(store, second)
        self.assertEqual(store.get(), second)

    def test_ignores_messages_for_other_topics(self) -> None:
        store = map_store.MapStore()
        store.send({"op": "publish", "topic": "/not_map", "msg": VALID_MAP})
        self.assertIsNone(store.get())

    def test_ignores_non_publish_messages(self) -> None:
        store = map_store.MapStore()
        store.send({"op": "status", "level": "info", "msg": "subscribed to /map"})
        self.assertIsNone(store.get())


if __name__ == "__main__":
    unittest.main()
