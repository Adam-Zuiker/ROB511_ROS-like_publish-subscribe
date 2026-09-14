"""
tests/test_heap.py — Unit tests for the hand-rolled binary min-heap in
src/heap.py, run entirely in-process (no sockets, no gateway).

Run with:  python3 -m unittest discover -s tests   (from starter/python/)

Every assertion below carries a message describing the *invariant*, not
just the values being compared — the goal is that a failure's message
alone should point at which property broke, without needing to re-derive
it from a bare diff. This matters most for a mutation-testing exercise:
when someone else's edit silently breaks a `<` into a `<=` somewhere,
"index 6.5 != 5" (or a 100-element list diff) tells you nothing about
*where* to look, but "heap property violated at index 3 (right child)"
does.
"""

from __future__ import annotations

import random
import sys
import unittest
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import heap  # noqa: E402 - import after sys.path setup, see above


def assert_is_min_heap(testcase: unittest.TestCase, values: list, size: int | None = None) -> None:
    """Check the defining property of a binary min-heap directly against
    its array layout: every node is <= both of its (present) children.

    `size` restricts the check to `values[:size]` — for confirming
    sift_down honored a shrunken "live" region and left the tail alone.
    """
    n = len(values) if size is None else size
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


def assert_first_mismatch(testcase: unittest.TestCase, actual: list, expected: list, label: str) -> None:
    """Like assertEqual, but on failure names the *first differing index*
    instead of dumping two whole lists — much faster to act on when the
    lists are long (e.g. a 100-element randomized push/pop sequence)."""
    testcase.assertEqual(len(actual), len(expected), f"{label}: length {len(actual)} != {len(expected)}")
    for i, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            testcase.fail(f"{label}: first mismatch at index {i}: got {a!r}, expected {e!r}")


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


class TestArithmeticPrimitives(unittest.TestCase):
    """Direct checks on _parent/_left/_right's raw formulas, independent
    of any heap behavior. If one of these is mutated, these tests point
    straight at the broken formula instead of failing indirectly via a
    corrupted heap somewhere else."""

    def test_parent_of_root_has_no_valid_parent(self) -> None:
        # (0-1)//2 == -1, a value that must never be treated as a real
        # index (see sift_up's root guard) -- checked here so a change to
        # the formula itself, not just the guard, gets caught directly.
        self.assertEqual(heap._parent(0), -1, "_parent(0) must be -1 (no real parent exists)")

    def test_parent_left_right_are_consistent_inverses(self) -> None:
        for i in range(1, 50):
            with self.subTest(index=i):
                self.assertEqual(
                    heap._parent(heap._left(i)), i, f"_parent(_left({i})) must round-trip back to {i}"
                )
                self.assertEqual(
                    heap._parent(heap._right(i)), i, f"_parent(_right({i})) must round-trip back to {i}"
                )

    def test_left_and_right_are_adjacent_and_ordered(self) -> None:
        for i in range(20):
            with self.subTest(index=i):
                self.assertEqual(
                    heap._right(i), heap._left(i) + 1, f"_right({i}) must be exactly _left({i}) + 1"
                )


class TestSiftPrimitives(unittest.TestCase):
    def test_sift_up_moves_new_minimum_to_root(self) -> None:
        values = [2.0, 5.0, 3.0, -1.0]
        heap.sift_up(values, 3)
        assert_is_min_heap(self, values)
        self.assertEqual(values[0], -1.0, "sift_up must walk a new global minimum all the way to the root")

    def test_sift_up_stops_as_soon_as_parent_is_not_smaller(self) -> None:
        # The element at index 3 (4.0) is already >= its parent (2.0), so
        # sift_up must leave the array completely untouched -- a mutation
        # that sifts unconditionally (or off by one) would move something.
        values = [1.0, 2.0, 3.0, 4.0]
        snapshot = list(values)
        heap.sift_up(values, 3)
        self.assertEqual(values, snapshot, "sift_up must not move an element that's already >= its parent")

    def test_sift_down_restores_property_after_root_replaced(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        values[0] = 9.0
        heap.sift_down(values, 0)
        assert_is_min_heap(self, values)
        self.assertEqual(
            Counter(values),
            Counter([9.0, 2.0, 3.0, 4.0, 5.0]),
            "sift_down must only reorder elements, never drop or duplicate one",
        )

    def test_sift_down_honors_a_shrunken_size(self) -> None:
        # heap[:3] is a valid mini-heap on its own; heap[3:] is deliberately
        # left invalid. Restricting sift_down to size=3 must fix only the
        # live region and leave the tail completely untouched -- this is
        # the one code path no other test in this file exercises.
        values = [9.0, 2.0, 3.0, -100.0, -200.0]
        heap.sift_down(values, 0, size=3)
        assert_is_min_heap(self, values, size=3)
        self.assertEqual(
            values[3:], [-100.0, -200.0], "sift_down must not touch anything at or beyond index `size`"
        )


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
                self.assertEqual(
                    Counter(result), Counter(case), "heapify must preserve the exact input multiset"
                )

    def test_root_is_minimum(self) -> None:
        for case in CASES:
            if not case:
                continue
            with self.subTest(case=case[:5]):
                result = heap.heapify(case)
                self.assertEqual(result[0], min(case), "heapify's root (index 0) must be the global minimum")


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
        assert_first_mismatch(self, popped, sorted(values), "heap_push/heap_pop round trip")

    def test_pop_from_empty_raises(self) -> None:
        with self.assertRaises(IndexError, msg="heap_pop on an empty list must raise IndexError"):
            heap.heap_pop([])

    def test_push_appends_then_sifts_not_inserts_at_front(self) -> None:
        # A push that grows the array any way other than append-then-fix
        # would still often look like a valid heap by luck; this checks
        # the multiset AND size grew by exactly one real append.
        values = [5.0, 6.0, 7.0]
        heap.heap_push(values, 1.0)
        self.assertEqual(len(values), 4, "heap_push must grow the list by exactly one element")
        self.assertEqual(
            Counter(values), Counter([5.0, 6.0, 7.0, 1.0]), "heap_push must not lose or duplicate a value"
        )


class TestHeapSort(unittest.TestCase):
    def test_ascending_order_and_multiset_preserved(self) -> None:
        for case in CASES:
            with self.subTest(case=case[:5]):
                result = heap.heap_sort(case)
                assert_first_mismatch(self, result, sorted(case), "heap_sort ascending order")
                self.assertEqual(
                    Counter(result), Counter(case), "heap_sort must preserve the exact input multiset"
                )

    def test_does_not_mutate_input(self) -> None:
        original = [3.0, 1.0, 2.0]
        snapshot = list(original)
        heap.heap_sort(original)
        self.assertEqual(original, snapshot, "heap_sort must not mutate the list it was given")


if __name__ == "__main__":
    unittest.main()
