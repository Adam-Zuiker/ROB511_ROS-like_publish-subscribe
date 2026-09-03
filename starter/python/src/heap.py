"""
heap.py — A hand-rolled binary min-heap.

This module deliberately does NOT use Python's built-in `heapq` module.
The assignment's stated learning goal is to "implement numeric binary
min-heap operations," so this file builds the two fundamental primitives —
sift-up and sift-down — from scratch, and every other operation
(`heapify`, `heap_push`, `heap_pop`, `heap_sort`) is written in terms of
those two.

--------------------------------------------------------------------------
THE BINARY MIN-HEAP INVARIANT
--------------------------------------------------------------------------
A binary min-heap is a *complete* binary tree (every level full except
possibly the last, which fills left-to-right) stored implicitly in a flat
Python list, maintaining one property at all times:

    heap[i] <= heap[2*i + 1]   (left child, if it exists)
    heap[i] <= heap[2*i + 2]   (right child, if it exists)

Because the tree is stored as a flat array rather than as linked nodes, we
can compute "parent of i" and "children of i" with pure arithmetic — no
pointers needed:

    parent(i) = (i - 1) // 2
    left(i)   = 2*i + 1
    right(i)  = 2*i + 2

The invariant only constrains a node relative to its *children*, not to
its siblings or to nodes elsewhere in the tree — so many different array
layouts can be valid heaps for the same multiset of values. That's why the
project spec says "any valid heap layout is accepted": there is no single
canonical heap for a given input.

The invariant guarantees `heap[0]` (the root) is always the minimum
element, which is what makes a heap useful as a priority queue: "give me
the smallest item" is an O(1) lookup, at the cost of O(log n) work to
restore the invariant whenever the heap's contents change.
"""

from __future__ import annotations

from typing import List, Sequence, Union

# Heap entries in this project are always plain numbers (the spec's
# /heapify and /heap_sort both operate on numeric arrays), so we use a
# simple numeric type alias rather than a generic/comparable type parameter.
Number = Union[int, float]


def _parent(index: int) -> int:
    return (index - 1) // 2


def _left(index: int) -> int:
    return 2 * index + 1


def _right(index: int) -> int:
    return 2 * index + 2


# --------------------------------------------------------------------------
# TODO(human): implement the two sift primitives below.
#
# sift_up(heap, index)
#   Restore the invariant by moving heap[index] *up* toward the root,
#   swapping with its parent for as long as it is smaller than its parent.
#   Needed after appending a brand-new element to the end of the list
#   (heap_push does this): every other position already satisfies the
#   invariant, so only the new leaf can possibly be out of place, and only
#   relative to nodes directly above it.
#
# sift_down(heap, index, size=None)
#   Restore the invariant by moving heap[index] *down* toward the leaves,
#   repeatedly swapping with the smaller of its two children until it is
#   no longer larger than either (or it runs out of children).
#   `size` lets a caller treat only heap[:size] as "live" data, leaving the
#   tail of the list untouched — heap_sort below will rely on this to grow
#   a sorted region at the end of the array without reallocating.
#   Needed in two situations: (1) after heap_pop moves the last element
#   into the root's old slot, and (2) as heapify's core subroutine, called
#   bottom-up over every internal node to build a heap from scratch.
# --------------------------------------------------------------------------


def sift_up(heap: List[Number], index: int) -> None:
    raise NotImplementedError


def sift_down(heap: List[Number], index: int, size: Union[int, None] = None) -> None:
    raise NotImplementedError


def heapify(items: Sequence[Number]) -> List[Number]:
    """Return a new list containing the same multiset as `items`, arranged
    to satisfy the binary min-heap invariant everywhere.

    Naively, you could build a heap by starting from an empty list and
    calling something like `heap_push` once per item: n pushes, each up to
    O(log n), for O(n log n) total. Instead we use the classic "Floyd
    build-heap" trick, which runs in O(n):

    Every index from `len(items) // 2` onward is a *leaf* (it has no
    children, because `2*i + 1 >= len(items)`), and a single element on
    its own trivially satisfies the heap invariant. So we only need to fix
    up the *internal* nodes, and we do it in reverse — from the last
    internal node back to the root — calling `sift_down` at each one.

    Why does bottom-up order make each `sift_down` call correct? Because
    by the time `sift_down(heap, i, n)` runs, both of node `i`'s child
    subtrees have *already* been fixed by earlier iterations (we visit
    higher indices first), so they are already valid heaps in their own
    right — exactly the precondition `sift_down` needs to work correctly.
    """
    heap = list(items)
    n = len(heap)
    for index in reversed(range(n // 2)):
        sift_down(heap, index, n)
    return heap


def heap_push(heap: List[Number], item: Number) -> None:
    """Insert `item` into `heap` in place, preserving the invariant.

    Appending to the end of the array is the only way to add a new leaf to
    a *complete* binary tree without leaving a gap partway through the
    array, so we always append first, then let `sift_up` walk the new
    element up to wherever it belongs.
    """
    heap.append(item)
    sift_up(heap, len(heap) - 1)


def heap_pop(heap: List[Number]) -> Number:
    """Remove and return the minimum element (`heap[0]`) in place,
    preserving the invariant for whatever remains.

    We can't simply delete index 0: removing from the *front* of a Python
    list is O(n) (every remaining element shifts left), and, more
    importantly, doing so naively wouldn't preserve the complete-tree
    shape the heap relies on. Instead: move the *last* element into the
    root's position (an O(1) move that keeps the tree complete, since
    we're removing the very last leaf), shrink the list by one, then
    `sift_down` from the root to fix the one spot that might now violate
    the invariant.
    """
    if not heap:
        raise IndexError("heap_pop from an empty heap")
    minimum = heap[0]
    last = heap.pop()  # removes and returns the last element, O(1)
    if heap:
        heap[0] = last
        sift_down(heap, 0)
    return minimum


def heap_sort(items: Sequence[Number]) -> List[Number]:
    """Return a new list containing the same multiset as `items`, in
    ascending order.

    Approach: build a min-heap in O(n) via `heapify`, then repeatedly pop
    the minimum. Each pop is O(log n) and we do it n times, so the overall
    cost is O(n log n) — the same asymptotic cost as Python's built-in
    `sorted()`, but built here from our own heap primitives per the
    assignment's learning goal, and reused directly by the A* planner
    later to order its search frontier by priority (per the spec:
    "/heap_sort is both a public service and a required A* dependency").
    """
    heap = heapify(items)
    result: List[Number] = []
    while heap:
        result.append(heap_pop(heap))
    return result
