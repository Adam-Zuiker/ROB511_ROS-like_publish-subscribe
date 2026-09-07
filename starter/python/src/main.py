"""
main.py — Entry point for the Project 1 runtime. This is what `make run`
executes: it must launch everything in the foreground, expose
127.0.0.1:9095, fail loudly if startup fails, and shut down cleanly on
Ctrl-C (SIGINT) or SIGTERM.

--------------------------------------------------------------------------
BACKGROUND: signals, and why a blocking accept() loop still shuts down
cleanly when you press Ctrl-C
--------------------------------------------------------------------------
Pressing Ctrl-C in a terminal sends the foreground process group a
SIGINT signal; a process manager stopping this program cleanly typically
sends SIGTERM. By default, Python turns SIGINT into a `KeyboardInterrupt`
exception and lets SIGTERM terminate the process immediately — neither
default gives our threads (the writer threads, the provider worker
threads, every open client socket) a chance to shut down in an orderly
way.

So we install our own handler for both signals with `signal.signal(...)`.
There's a subtlety worth understanding: our main thread spends nearly all
of its time blocked inside `server.serve_forever()`, which is itself
blocked inside the C-level `accept()` system call, deep inside the
socket module — not executing any Python bytecode at all. A signal
handler is Python code, and Python code can only run again once control
returns to the interpreter. When a signal arrives while a thread is
blocked in a system call like `accept()`, the OS interrupts that call
(this happens at the kernel level, independent of Python) so it returns
control to the interpreter, which then runs our handler. Our handler's
job is simple and synchronous: call `server.shutdown()`, which closes the
listening socket (and every client socket) right then and there. Once
the handler returns, Python's socket layer would normally retry the
interrupted `accept()` automatically (per PEP 475) — but since the
listening socket is now already closed, that retry immediately fails with
`OSError` instead of blocking again, which is exactly the signal
`server.serve_forever()` is watching for to know it's time to return.
"""

from __future__ import annotations

import logging
import signal
import sys

import logging_setup
import map_store
from broker import Broker
from server import TCPServer
from services import register_builtin_services

log = logging.getLogger("main")


def main() -> int:
    logging_setup.configure()

    broker = Broker()
    store = map_store.register(broker)
    log.info("subscribed to /map")
    providers = register_builtin_services(broker, store)
    log.info("registered built-in services: %s", ", ".join(p.id for p in providers))

    server = TCPServer(broker)
    try:
        server.bind_and_listen()
    except OSError as exc:
        # Required startup failed (e.g. port 9095 already in use). Fail
        # loudly and exit nonzero rather than limping along without a
        # working listener — per the spec, "make run ... fails if
        # required startup fails."
        log.error("could not bind 127.0.0.1:9095: %s", exc)
        return 1

    def handle_signal(signum: int, frame) -> None:  # noqa: ANN001 - stdlib signature
        log.info("received signal %s, shutting down", signal.Signals(signum).name)
        server.shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log.info("Project 1 runtime ready on 127.0.0.1:9095")
    try:
        server.serve_forever()  # blocks here until shutdown() is called
    finally:
        # Runs both on a clean shutdown and if serve_forever() somehow
        # raises: always give the in-process service providers a chance
        # to exit their worker threads instead of relying solely on them
        # being daemon threads.
        for provider in providers:
            provider.stop()
    log.info("shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
