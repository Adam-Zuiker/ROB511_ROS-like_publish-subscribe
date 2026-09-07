"""
services — internal, in-process service *providers* built into this
runtime (as opposed to services an external client provides over the
wire). Each submodule owns one cohesive group of services; this file just
aggregates "register everything this runtime provides out of the box"
into one call for main.py to make.
"""

from __future__ import annotations

from typing import List

import planner
from broker import Broker
from map_store import MapStore
from services import heap_service
from services.provider import InProcessProvider, register as register_provider


def register_builtin_services(broker: Broker, store: MapStore) -> List[InProcessProvider]:
    """Register every service this runtime provides out of the box: the
    Project 1 checkpoint services (/heapify, /heap_sort) plus /plan_path.

    /plan_path needs `store` (the current map) in addition to `broker`
    (to publish on /path after a successful plan), which is why this
    function takes `store` as a parameter and heap_service.register()
    doesn't — see planner.make_plan_path_handler() for how those two are
    captured.

    Returns the created providers so main.py can stop() them on shutdown.
    """
    providers = heap_service.register(broker)
    providers.append(
        register_provider(broker, "/plan_path", planner.make_plan_path_handler(broker, store))
    )
    return providers
