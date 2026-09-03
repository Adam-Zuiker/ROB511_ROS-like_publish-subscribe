"""
services — internal, in-process service *providers* built into this
runtime (as opposed to services an external client provides over the
wire). Each submodule owns one cohesive group of services; this file just
aggregates "register everything this runtime provides out of the box"
into one call for main.py to make.
"""

from __future__ import annotations

from typing import List

from broker import Broker
from services import heap_service
from services.provider import InProcessProvider


def register_builtin_services(broker: Broker) -> List[InProcessProvider]:
    """Register every service this runtime provides out of the box.

    Currently just the Project 1 checkpoint services (/heapify,
    /heap_sort). A future /plan_path registration (see planner_stub.py)
    will be added here once the A* planner exists — that addition won't
    require any change to broker.py, connection.py, or server.py.

    Returns the created providers so main.py can stop() them on shutdown.
    """
    return heap_service.register(broker)
