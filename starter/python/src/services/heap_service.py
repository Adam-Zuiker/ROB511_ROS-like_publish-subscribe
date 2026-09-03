"""
services/heap_service.py — Wires the Project 1 checkpoint services,
`/heapify` and `/heap_sort`, to the binary min-heap primitives in heap.py.

This file is intentionally thin: all the actual algorithm work happens in
heap.py, which knows nothing about JSON, sockets, or the broker. Here we
only translate between "the JSON `args` value a caller sent" and "a plain
list of numbers heap.py understands," and back — the same translation
role protocol.py plays at the wire-framing layer, just one level up.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import heap
from broker import Broker
# Imported under a different local name than the function we define below
# (also called `register`) so the two can't shadow each other.
from services.provider import InProcessProvider, register as register_provider


def _extract_numbers(args: Any, key: str) -> List[float]:
    """Validate and pull a list of numbers out of `args[key]`.

    Raises ValueError with a human-readable message on any problem. The
    handlers below catch this and turn it into a clean, descriptive
    `result:false` response — as opposed to letting an uncaught exception
    reach services/provider.py's generic handler wrapper, which would
    still keep the service alive but would only be able to report a
    generic "internal error" rather than something a caller could act on.
    """
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    if key not in args:
        raise ValueError(f"args.{key} is required")
    values = args[key]
    if not isinstance(values, list):
        raise ValueError(f"args.{key} must be an array")
    for item in values:
        # bool is a subclass of int in Python (isinstance(True, int) is
        # True), so without this explicit exclusion, {"values": [true]}
        # would be silently accepted as the number 1.
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"args.{key} must contain only numbers")
    return list(values)


def _heapify_handler(args: Any) -> Tuple[Any, bool, str]:
    try:
        values = _extract_numbers(args, "values")
    except ValueError as exc:
        return {}, False, str(exc)
    return {"heap": heap.heapify(values)}, True, ""


def _heap_sort_handler(args: Any) -> Tuple[Any, bool, str]:
    try:
        numbers = _extract_numbers(args, "numbers")
    except ValueError as exc:
        return {}, False, str(exc)
    return {"sorted": heap.heap_sort(numbers)}, True, ""


def register(broker: Broker) -> List[InProcessProvider]:
    """Register /heapify and /heap_sort as in-process providers on `broker`.

    Returns the created providers so main.py can `stop()` them cleanly on
    shutdown.
    """
    return [
        register_provider(broker, "/heapify", _heapify_handler),
        register_provider(broker, "/heap_sort", _heap_sort_handler),
    ]
