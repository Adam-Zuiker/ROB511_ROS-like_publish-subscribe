"""
services/planner_stub.py — placeholder documenting the future /plan_path
service. Not wired up yet; nothing in this file executes.

Why leaving /plan_path unregistered right now is already spec-correct:
`Broker.call_service` (broker.py) checks whether a provider currently
exists for the requested service *first*, before anything else. If none
does — which is the case for /plan_path until a later phase registers
one — it immediately (no timeout wait needed) responds to the caller
with a clean `result:false`. That is exactly the behavior the project
spec requires for "before a map arrives" or any other not-yet-plannable
situation, so there is nothing special to build here yet; the general
"no provider" path already covers it.

When the A* planner is implemented, activating it will look like this,
added to services/__init__.py's register_builtin_services():

    from services.provider import register as register_provider
    from planner import plan_path_handler  # not yet written

    def register_builtin_services(broker):
        providers = heap_service.register(broker)
        providers.append(register_provider(broker, "/plan_path", plan_path_handler))
        return providers

`plan_path_handler` would follow the same shape every handler in this
project already follows — `(args) -> (values, result, status_text)` — so
no changes to broker.py, connection.py, server.py, or services/provider.py
will be needed to add it. That uniformity is the entire reason
services/provider.py exists as a generic adapter instead of something
`/heapify`- and `/heap_sort`-specific.
"""
