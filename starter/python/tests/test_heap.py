"""
tests/test_heap.py — Unit tests for the hand-rolled binary min-heap in
src/heap.py, run entirely in-process (no sockets, no gateway).

Run with:  python3 -m unittest discover -s tests   (from starter/python/)
"""

from __future__ import annotations

import random
import sys
import unittest
from collections import Counter
from pathlib import Path

# main.py is run as `python3 src/main.py`, which puts starter/python/src on
# sys.path[0] automatically. Test files aren't run that way, so we add the
# same directory explicitly here, letting tests import `heap` exactly the
# way the rest of the runtime does.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import heap  # noqa: E402 - import after sys.path setup, see above


def assert_is_min_heap(testcase: unittest.TestCase, values: list) -> None:
    """Check the defining property of a binary min-heap directly against
    its array layout: every node is <= both of its (present) children.
    This is the same check the project spec describes for /heapify's
    output, applied generically to any array under test.
    """
    n = len(values)
    for i in range(n):
        left, right = 2 * i + 1, 2 * i + 2
        if left < n:
            testcase.assertLessEqual(
                values[i], values[left], f"heap property violated at index {i} (left child)"
            )
        if right < n:
            testcase.assertLessEqual(
                values[i], values[right], f"heap property violated at index {i} (right child)"
            )


# A range of input shapes the spec explicitly calls out: empty, duplicates,
# negative values, fractional values, and one larger randomized case.
CASES = [
    [],
    [1.0],
    [3.0, 1.0, 2.0],
    [5.0, 5.0, 5.0],
    [2.0, 2.0, 1.0, 1.0, 3.0],
    [-4.0, 0.0, -1.5, 3.25, -3.25],
    [random.uniform(-100, 100) for _ in range(200)],
]


class TestSiftPrimitives(unittest.TestCase):
    def test_sift_up_moves_new_minimum_to_root(self) -> None:
        # A valid 3-element heap, then a new minimum appended at the end
        # (as heap_push would do) — sift_up must walk it all the way up.
        values = [2.0, 5.0, 3.0, -1.0]
        heap.sift_up(values, 3)
        assert_is_min_heap(self, values)
        self.assertEqual(values[0], -1.0)

    def test_sift_down_restores_property_after_root_replaced(self) -> None:
        # Simulate what heap_pop does by hand: drop an arbitrary value into
        # the root of an otherwise-valid heap, then let sift_down fix it.
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        values[0] = 9.0
        heap.sift_down(values, 0)
        assert_is_min_heap(self, values)
        self.assertEqual(Counter(values), Counter([9.0, 2.0, 3.0, 4.0, 5.0]))


class TestHeapify(unittest.TestCase):
    def test_heap_property_holds_for_all_cases(self) -> None:
        for case in CASES:
            with self.subTest(case=case[:5]):
                result = heap.heapify(case)
                assert_is_min_heap(self, result)

    def test_multiset_preserved(self) -> None:
        for case in CASES:
            with self.subTest(case=case[:5]):
                result = heap.heapify(case)
                self.assertEqual(Counter(result), Counter(case))

    def test_root_is_minimum(self) -> None:
        for case in CASES:
            if not case:
                continue
            result = heap.heapify(case)
            self.assertEqual(result[0], min(case))


class TestHeapPushPop(unittest.TestCase):
    def test_push_then_pop_all_yields_ascending_order(self) -> None:
        values = [random.uniform(-50, 50) for _ in range(100)]
        built: list = []
        for v in values:
            heap.heap_push(built, v)
            assert_is_min_heap(self, built)
        popped = []
        while built:
            popped.append(heap.heap_pop(built))
            assert_is_min_heap(self, built)
        self.assertEqual(popped, sorted(values))

    def test_pop_from_empty_raises(self) -> None:
        with self.assertRaises(IndexError):
            heap.heap_pop([])


class TestHeapSort(unittest.TestCase):
    def test_ascending_order_and_multiset_preserved(self) -> None:
        for case in CASES:
            with self.subTest(case=case[:5]):
                result = heap.heap_sort(case)
                self.assertEqual(result, sorted(case))
                self.assertEqual(Counter(result), Counter(case))

    def test_does_not_mutate_input(self) -> None:
        original = [3.0, 1.0, 2.0]
        snapshot = list(original)
        heap.heap_sort(original)
        self.assertEqual(original, snapshot)


if __name__ == "__main__":
    unittest.main()
