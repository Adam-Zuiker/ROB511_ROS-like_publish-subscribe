"""
tests/test_heap_service.py — Unit tests for services/heap_service.py: the
JSON-argument validation layer between the wire protocol and heap.py's
pure algorithms, run entirely in-process (no sockets, no gateway).

test_gateway.py's TestHeapServicesOverTheWire covers the end-to-end wiring
(broker routing, InProcessProvider) with a couple of representative
inputs; this file exists to hit every validation branch of
_extract_numbers directly, the way test_map_store.py does for
validate_map -- including checking *which* reason a rejection gives, not
just that some ValueError happened.

Run with:  python3 -m unittest discover -s tests   (from starter/python/)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services import heap_service  # noqa: E402

# (label, args, key, substring the ValueError message must contain)
INVALID_CASES = [
    ("args not an object (list)", [1, 2, 3], "values", "args must be an object"),
    ("args not an object (string)", "values", "values", "args must be an object"),
    ("args not an object (None)", None, "values", "args must be an object"),
    ("missing key", {}, "values", "args.values is required"),
    ("wrong key present", {"numbers": [1, 2]}, "values", "args.values is required"),
    ("value not a list (string)", {"values": "1,2,3"}, "values", "args.values must be an array"),
    ("value not a list (number)", {"values": 5}, "values", "args.values must be an array"),
    ("list contains a bool", {"values": [1, True, 2]}, "values", "args.values must contain only numbers"),
    ("list contains a string", {"values": [1, "2", 3]}, "values", "args.values must contain only numbers"),
    ("list contains None", {"values": [1, None, 3]}, "values", "args.values must contain only numbers"),
]


class TestExtractNumbers(unittest.TestCase):
    def test_accepts_well_formed_input(self) -> None:
        result = heap_service._extract_numbers({"values": [3.0, 1.0, 2.0]}, "values")
        self.assertEqual(result, [3.0, 1.0, 2.0])

    def test_accepts_empty_list(self) -> None:
        # Spec: "Empty input succeeds" for both /heapify and /heap_sort.
        self.assertEqual(heap_service._extract_numbers({"values": []}, "values"), [])

    def test_accepts_mixed_int_and_float(self) -> None:
        self.assertEqual(heap_service._extract_numbers({"values": [1, 2.5, -3]}, "values"), [1, 2.5, -3])

    def test_returns_a_copy_not_the_original_list(self) -> None:
        # Guards against a mutation of `return list(values)` -> `return
        # values`, which would alias the caller's own list -- mutating the
        # result would then corrupt the original args dict.
        original = [1.0, 2.0, 3.0]
        result = heap_service._extract_numbers({"values": original}, "values")
        result.append(999.0)
        self.assertEqual(original, [1.0, 2.0, 3.0], "mutating the returned list must not affect the original input")

    def test_rejects_invalid_input_for_the_specific_stated_reason(self) -> None:
        for label, args, key, expected_substring in INVALID_CASES:
            with self.subTest(label=label):
                with self.assertRaises(ValueError, msg=f"{label}: expected a ValueError, none was raised") as cm:
                    heap_service._extract_numbers(args, key)
                self.assertIn(
                    expected_substring,
                    str(cm.exception),
                    f"{label}: error message {str(cm.exception)!r} doesn't mention {expected_substring!r}",
                )


class TestHeapifyHandler(unittest.TestCase):
    def test_success_shape(self) -> None:
        values, result, status = heap_service._heapify_handler({"values": [3.0, 1.0, 2.0]})
        self.assertTrue(result, f"expected success, got status: {status!r}")
        self.assertEqual(status, "", "a successful handler must return an empty status string")
        self.assertIn("heap", values, "a successful /heapify response must have a 'heap' key")
        self.assertEqual(sorted(values["heap"]), [1.0, 2.0, 3.0])

    def test_failure_shape_never_raises(self) -> None:
        # The handler must catch _extract_numbers's ValueError itself and
        # return a clean (values, False, message) tuple -- never let the
        # exception escape (that's InProcessProvider's job as a last
        # resort, not this handler's expected path).
        values, result, status = heap_service._heapify_handler({"values": "not-a-list"})
        self.assertEqual(values, {}, "a failed handler must return an empty values dict")
        self.assertFalse(result)
        self.assertIn("args.values", status, f"failure status should name the broken field, got: {status!r}")

    def test_uses_the_values_key_not_numbers(self) -> None:
        # Catches a mutation that swapped which key /heapify reads --
        # e.g. accidentally using "numbers" (heap_sort's key) instead.
        values, result, status = heap_service._heapify_handler({"numbers": [3.0, 1.0, 2.0]})
        self.assertFalse(result, "/heapify must require the 'values' key specifically, not 'numbers'")
        self.assertIn("args.values", status)


class TestHeapSortHandler(unittest.TestCase):
    def test_success_shape(self) -> None:
        values, result, status = heap_service._heap_sort_handler({"numbers": [3.0, 1.0, 2.0]})
        self.assertTrue(result, f"expected success, got status: {status!r}")
        self.assertEqual(status, "")
        self.assertIn("sorted", values, "a successful /heap_sort response must have a 'sorted' key")
        self.assertEqual(values["sorted"], [1.0, 2.0, 3.0])

    def test_failure_shape_never_raises(self) -> None:
        values, result, status = heap_service._heap_sort_handler({"numbers": "not-a-list"})
        self.assertEqual(values, {})
        self.assertFalse(result)
        self.assertIn("args.numbers", status)

    def test_uses_the_numbers_key_not_values(self) -> None:
        # The mirror image of the /heapify check above -- these two tests
        # together would catch the keys being swapped in *either*
        # direction, which a single test on its own couldn't distinguish.
        values, result, status = heap_service._heap_sort_handler({"values": [3.0, 1.0, 2.0]})
        self.assertFalse(result, "/heap_sort must require the 'numbers' key specifically, not 'values'")
        self.assertIn("args.numbers", status)


if __name__ == "__main__":
    unittest.main()
