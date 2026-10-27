"""Direct tests of src/heap.py and src/services/heap_service.py. No runtime needed."""

import random

from planning_support import is_min_heap

import heap
from services import heap_service


def random_lists(seed, count=200, max_len=40):
    rng = random.Random(seed)
    cases = [[], [7], [2, 2, 2, 2], list(range(10)), list(range(10, 0, -1)), [0.5, -0.5, 0, -3, 3.25]]
    for _ in range(count):
        length = rng.randint(0, max_len)
        if rng.random() < 0.5:
            cases.append([rng.randint(-20, 20) for _ in range(length)])
        else:
            cases.append([round(rng.uniform(-100, 100), 2) for _ in range(length)])
    return cases


def test_sift_up_bubbles_new_minimum_to_root_and_stops_early():
    values = [1, 3, 5, 7, 9, 6, 0]
    heap.sift_up(values, 6)
    assert values == [0, 3, 1, 7, 9, 6, 5], f"sift_up of 0 from a leaf should reach the root: {values}"

    values = [1, 3, 5, 7, 9, 6, 4]
    heap.sift_up(values, 6)
    assert values == [1, 3, 4, 7, 9, 6, 5], f"sift_up should stop once the parent is smaller: {values}"

    values = [4, 8, 9]
    heap.sift_up(values, 0)
    assert values == [4, 8, 9], f"sift_up on the root must not change anything: {values}"


def test_sift_down_swaps_with_smaller_child_and_honors_size():
    values = [9, 2, 1, 5, 6, 3, 4]
    heap.sift_down(values, 0)
    assert values == [1, 2, 3, 5, 6, 9, 4], f"sift_down should follow the smaller child each level: {values}"

    values = [9, 1, 2, 0, 0]
    heap.sift_down(values, 0, 3)
    assert values == [1, 9, 2, 0, 0], f"sift_down(size=3) must not touch indices >= 3: {values}"

    values = [5, 3, 1]
    heap.sift_down(values, 0, 2)
    assert values == [3, 5, 1], f"sift_down(size=2) must ignore the right child at index 2: {values}"

    values = [1, 5, 3]
    heap.sift_down(values, 0)
    assert values == [1, 5, 3], f"sift_down must not move a root smaller than its children: {values}"


def test_heapify_builds_valid_heap_and_preserves_values():
    for items in random_lists(seed=1):
        original = list(items)
        result = heap.heapify(items)
        assert items == original, f"heapify mutated its input: {original} -> {items}"
        assert result is not items, "heapify must return a new list"
        assert is_min_heap(result), f"heapify({original}) is not a min-heap: {result}"
        assert sorted(result) == sorted(original), f"heapify({original}) changed the values: {result}"


def test_heap_push_then_pop_returns_ascending_order():
    for items in random_lists(seed=2, count=100):
        h = []
        for item in items:
            heap.heap_push(h, item)
            assert is_min_heap(h), f"heap invariant broken after pushing {item}: {h}"
        assert len(h) == len(items), f"heap_push lost or duplicated items: {h} vs {items}"
        popped = []
        while h:
            popped.append(heap.heap_pop(h))
            assert is_min_heap(h), f"heap invariant broken after a pop: {h}"
        assert popped == sorted(items), f"popping everything should give {sorted(items)}, got {popped}"


def test_heap_pop_on_empty_heap_raises_index_error():
    try:
        heap.heap_pop([])
    except IndexError:
        pass
    else:
        raise AssertionError("heap_pop([]) should raise IndexError")
    single = [42]
    assert heap.heap_pop(single) == 42 and single == [], f"popping a 1-element heap: {single}"


def test_heap_sort_matches_sorted_and_leaves_input_untouched():
    for items in random_lists(seed=3):
        original = list(items)
        result = heap.heap_sort(items)
        assert items == original, f"heap_sort mutated its input: {original} -> {items}"
        assert result == sorted(original), f"heap_sort({original}) = {result}, expected {sorted(original)}"


def test_heap_sort_orders_priority_cell_tuples_like_the_planner_uses():
    frontier = [(5, (0, 0)), (3, (2, 1)), (3, (1, 4)), (7, (0, 1)), (3, (1, 2)), (4, (9, 9))]
    result = heap.heap_sort(frontier)
    assert result == sorted(frontier), f"heap_sort on (priority, cell) tuples: {result}"
    assert result[0] == (3, (1, 2)), f"lowest priority with lowest cell should come first: {result[0]}"
    rng = random.Random(4)
    for _ in range(100):
        entries = [(rng.randint(0, 6), (rng.randint(0, 4), rng.randint(0, 4))) for _ in range(rng.randint(1, 25))]
        assert heap.heap_sort(entries) == sorted(entries), f"heap_sort tuples failed on {entries}"


def test_heap_services_return_results_and_reject_bad_input():
    values, ok, _ = heap_service._heapify_handler({"values": [5, -1, 3.5, 2, 2]})
    assert ok is True and is_min_heap(values["heap"]), f"/heapify: {values}"
    assert sorted(values["heap"]) == [-1, 2, 2, 3.5, 5], f"/heapify changed the values: {values}"

    values, ok, _ = heap_service._heap_sort_handler({"numbers": [3, -1, 2.5, 3]})
    assert ok is True and values == {"sorted": [-1, 2.5, 3, 3]}, f"/heap_sort: {values}"

    values, ok, _ = heap_service._heap_sort_handler({"numbers": []})
    assert ok is True and values == {"sorted": []}, f"/heap_sort of [] should succeed: {values}"

    bad_cases = [
        (heap_service._heapify_handler, {"numbers": [1, 2]}),
        (heap_service._heapify_handler, {"values": [1, True]}),
        (heap_service._heap_sort_handler, {"values": [1, 2]}),
        (heap_service._heap_sort_handler, {"numbers": [1, "2"]}),
        (heap_service._heap_sort_handler, {"numbers": [1, False]}),
        (heap_service._heap_sort_handler, {"numbers": None}),
        (heap_service._heap_sort_handler, {"numbers": {"a": 1}}),
        (heap_service._heap_sort_handler, [3, 1, 2]),
        (heap_service._heap_sort_handler, None),
    ]
    for handler, args in bad_cases:
        _, ok, text = handler(args)
        assert ok is False, f"{handler.__name__}({args!r}) should fail, got result {ok}"
