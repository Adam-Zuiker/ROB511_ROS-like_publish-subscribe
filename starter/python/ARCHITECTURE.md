# Project 1 architecture (Python) — Phase 1: pub/sub gateway + heap checkpoint

This document explains *what* was built in `src/` and, more importantly,
*why* it was built this way — especially the networking and concurrency
decisions, which are the parts of this project most students haven't seen
before. Read this alongside the docstrings at the top of each file; the
docstrings go deeper on individual mechanisms, this document is the map
that ties them together.

This phase covers the TCP/JSON gateway (the pub/sub + service-call
"rosbridge" from `spec/ROSBRIDGE_PROTOCOL.md`) and the `/heapify` /
`/heap_sort` checkpoint services from `spec/PROJECT1_ASTAR.md`. Map
handling and the A* planner are a later phase, but the design below was
chosen so that adding them later doesn't require reworking anything here
— see "What's deliberately not built yet," below.

## 1. The big picture

```text
                     External clients (Autograder, test scripts, nc, ...)
                                        |
                                   TCP / JSON
                                        |
                              127.0.0.1:9095
                                        |
                    +-------------------------------------+
                    |         server.py: TCPServer         |
                    |   (accept loop, one thread per       |
                    |    connection)                       |
                    +-------------------+-------------------+
                                        |
                      +-----------------+-----------------+
                      |                                   |
              connection.py:                       connection.py:
              Connection (client A)                 Connection (client B)
              reader thread + writer                reader thread + writer
              thread + outbound queue                thread + outbound queue
                      |                                   |
                      +-----------------+-----------------+
                                        |
                                 broker.py: Broker
                        (topics, services, outstanding
                         calls — one shared Lock)
                                        |
                      +-----------------+-----------------+
                      |                                   |
        services/provider.py:                   (future: /plan_path,
        InProcessProvider                         registered the same way)
        /heapify, /heap_sort
        (own worker thread each)
                      |
                  heap.py
          (pure binary min-heap primitives,
           no networking/JSON awareness)
```

Every arrow in that diagram is a **thread boundary** except the bottom
one (`InProcessProvider` calling straight into `heap.py` is an ordinary
function call, not cross-thread). Understanding where the thread
boundaries are — and the one rule about what may cross them while holding
a lock — is most of what there is to understand about this system.

## 2. Why thread-per-connection, not `asyncio`

The protocol spec allows any implementation strategy, as long as "a slow
client must not prevent unrelated clients from making progress." Two
mainstream ways to satisfy that in Python:

- **`asyncio`** (or raw `select`/`selectors`): one thread, an event loop,
  and non-blocking sockets. The loop juggles many connections by
  switching between them whenever one would otherwise block.
- **Thread-per-connection** (what this project uses): one OS thread
  handles one connection's blocking `recv()` calls; the OS scheduler is
  what switches between connections, not application code.

`asyncio` is arguably the more "production" choice for high connection
counts, but it requires understanding an event loop, coroutines
(`async`/`await`), and cooperative scheduling before you can reason about
*anything* — a second substantial topic layered on top of sockets
themselves. Thread-per-connection lets you trace one concrete thread from
`accept()` (in `server.py`) through a genuinely blocking `recv()` loop
(in `connection.py`) into the broker and back out, using only concepts
(threads, blocking calls, locks) that map directly onto what's actually
happening at the OS level. Since this project's grading weight is on the
pub/sub semantics, the heap, and A* — not on maximizing concurrent
connection counts — the simpler, more transparent model is the better fit
for learning it, at essentially zero real-world cost (a course project
will see a handful of concurrent connections, not thousands).

## 3. The one rule that makes threads-plus-shared-state safe

`broker.py`'s `Broker` object is shared by every connection's thread.
Multiple threads reading and writing the same Python dicts/sets at once
is a **race condition** waiting to happen unless something serializes
access — that something is `Broker._lock`, a single `threading.Lock`.

The rule, stated once so it can be repeated everywhere: **hold the lock
only for in-memory bookkeeping (dict/set reads and writes); release it
before doing any socket I/O.** Concretely, every `Broker` method that
needs to deliver a message:

1. Acquires the lock.
2. Reads or copies whatever state it needs (e.g. the current set of
   subscribers to a topic).
3. Releases the lock.
4. *Then* calls `sink.send(message)` on whichever connections need one.

Why does step 4 have to happen outside the lock? `sink.send()` (see
`connection.py`) only ever appends a message to that connection's own
`queue.Queue` — fast, and it never blocks, no matter how slow that
connection's peer currently is. The actual, potentially-slow
`socket.send()` call happens later, on that connection's own dedicated
**writer thread**, completely decoupled from whoever produced the
message. If we instead called `socket.send()` directly while holding
`Broker._lock`, one subscriber that stopped reading its socket (their TCP
receive buffer full, or the client just wedged) would eventually make
`send()` block — and since *every* thread in the gateway needs that same
lock to do anything, the whole system would freeze waiting on one bad
connection. The queue + dedicated writer thread per connection is what
turns "slow client" into "that one client's own queue backs up" instead
of "the whole gateway stalls."

## 4. Two threads per connection: why split reader and writer?

A socket supports two independently-blocking operations: `recv()` (waits
for the peer to send something) and `send()` (can block if the peer isn't
reading fast enough and the kernel's outbound buffer fills up). If one
thread tried to do both — read a request, write a response, repeat — a
slow-to-read peer stuck in that thread's `send()` call would also prevent
it from getting back around to `recv()`, tangling two independent waits
into one thread with no way to make progress on either. `connection.py`
avoids this by giving each connection two threads:

- **Reader thread:** `recv()` → parse (via `protocol.LineReader`) →
  dispatch to the broker. Loops forever until the peer disconnects.
- **Writer thread:** pull the next message off this connection's own
  outbound queue → `send()` it. Loops forever until told to stop.

Neither thread ever needs a timeout or has to poll — each is a simple,
fully-blocking loop, which is exactly what makes this model easy to
reason about compared to non-blocking I/O.

## 5. TCP framing: why every message ends in `\n`

TCP delivers a *byte stream*, not a sequence of messages — there is no
built-in concept of "where one JSON object ends and the next begins" once
bytes are in flight. A single `recv()` call might return part of one
message, several whole messages concatenated together, or anything in
between, regardless of how the sender originally called `send()`. The
protocol fixes this by requiring exactly one `\n` after every JSON
object; `protocol.LineReader` buffers raw bytes across as many `recv()`
calls as it takes and hands back only complete, parsed JSON objects, no
matter how the underlying bytes happened to be chunked. See that file's
module docstring for the full explanation and a worked example.

## 6. Service calls: correlation IDs, not caller IDs

When client A calls `/heap_sort` with `id: "call-1"`, and — completely
independently — client B also happens to choose `id: "call-1"` for an
unrelated call, the protocol explicitly allows this (a caller's `id` only
has to be unique among *that caller's own* outstanding requests). If the
broker tracked in-flight calls in a dictionary keyed directly by that raw
id, A's and B's entries would collide.

`broker.py` avoids this by minting its own globally unique
`provider_call_id` for every forwarded call (see `Broker.call_service`
and the `PendingCall` dataclass) and remembering, server-side, which
caller and which *original* id that corresponds to. The provider only
ever sees the broker-minted id; the original caller only ever sees their
own id echoed back. Collisions become structurally impossible rather than
something the code has to detect and special-case.

## 7. Built-in services are in-process, not loopback sockets

`/heapify` and `/heap_sort` are registered as **in-process providers**
(`services/provider.py`'s `InProcessProvider`) rather than as extra
client sockets that dial back into our own `127.0.0.1:9095` listener.
Both are legal under the spec ("the internal design is entirely yours");
in-process avoids a real startup-ordering hazard a loopback design would
introduce (our own listener would need to be up *before* we could
register our own built-in services), for no benefit an external client
could ever observe.

The key design move: `InProcessProvider` implements the exact same
`MessageSink` interface (`id` + `send(message)`) that a real socket
`Connection` does. The broker's `call_service` / `service_response`
methods never branch on "is this a socket or an in-process function" —
they treat every provider identically. That uniformity is what lets a
*future* `/plan_path` service be registered the same way, with zero
changes to `broker.py`, `connection.py`, or `server.py` — see
`services/planner_stub.py`.

## 8. What's deliberately not built yet

- **`/plan_path` (A* planner):** unregistered on purpose. `Broker.call_service`'s
  existing "no provider registered" path already returns a clean,
  immediate `result:false` for any caller that tries it early — which is
  exactly the spec-correct behavior for "before a map arrives," so there
  is nothing special to add for that case right now.
- **`/map` handling:** no map storage or replacement logic exists yet.
  `starter/python/maps/student_map.json` is still a placeholder the
  student needs to fill in; `make map` will work mechanically (the
  gateway will accept and route the `/map` publication like any other
  topic) once that file exists, but nothing currently *stores* the
  latest map for a planner to consult.

Both are intentionally deferred to keep this phase focused on the
networking layer and the heap checkpoint; the `MessageSink` /
`InProcessProvider` design above means neither addition should require
touching the gateway internals.

## 9. File-by-file responsibility summary

| File | What it owns |
|---|---|
| `src/protocol.py` | TCP byte stream ↔ parsed JSON message boundary; envelope builders |
| `src/heap.py` | Binary min-heap primitives (sift-up/down, heapify, push/pop, heap_sort) — no I/O awareness at all |
| `src/broker.py` | Thread-safe topic/service/outstanding-call registry; one method per protocol op |
| `src/connection.py` | One TCP client: reader thread, writer thread, outbound queue, dispatch to the broker |
| `src/server.py` | Listening socket, accept loop, live-connection bookkeeping |
| `src/services/provider.py` | Generic in-process `MessageSink` adapter (function → service) |
| `src/services/heap_service.py` | `/heapify` and `/heap_sort` handlers, wired through `provider.py` |
| `src/services/planner_stub.py` | Notes on how `/plan_path` will plug in later — no executable code |
| `src/logging_setup.py` | Routes all diagnostics to stderr, keeping stdout free of anything that could be confused with protocol traffic |
| `src/main.py` | Startup/shutdown orchestration: bind, register services, block in the foreground, handle SIGINT/SIGTERM cleanly |
| `tests/test_heap.py` | Unit tests for `heap.py`, no networking involved |
| `tests/test_gateway.py` | Black-box integration tests against a real running `src/main.py` subprocess, over real TCP sockets |

## 10. Where to look for each spec requirement

| Requirement (from `spec/ROSBRIDGE_PROTOCOL.md`) | Where it's implemented |
|---|---|
| Multiple concurrent TCP clients at 127.0.0.1:9095 | `server.py` (`TCPServer`), one `Connection` per accepted socket |
| Newline-delimited JSON framing | `protocol.py` (`LineReader`, `encode`) |
| `advertise` / `unadvertise` / `publish` / `subscribe` / `unsubscribe` | `connection.py` dispatch → `broker.py` (`Broker.advertise` etc.) |
| `advertise_service` / `unadvertise_service` / `call_service` / `service_response` | same dispatch path → `broker.py` service methods |
| Status after subscribe / service registration | `Broker.subscribe`, `Broker.advertise_service` |
| Correlation by connection + id, no cross-talk | `PendingCall` + broker-minted `provider_call_id` (§6 above) |
| Missing provider / disconnect / timeout → clean `result:false` | `Broker.call_service` (no-provider path), `Broker.cleanup_connection`, `Broker._on_timeout` |
| Slow client can't block others | Per-connection outbound queue + writer thread; lock never held during I/O (§3, §4 above) |
| Malformed requests don't crash the gateway | `Connection._dispatch`'s `except` clause; `LineReader`/`ProtocolError` |
| Connection close cleans up its own registrations | `Connection._shutdown` → `Broker.cleanup_connection` |

## 11. Running and testing this phase

```bash
make build   # python3 -m compileall -q src  — syntax-checks every module
make run     # foreground; binds 127.0.0.1:9095; Ctrl-C to stop cleanly
```

In a second terminal, while `make run` is active:

```bash
python3 -m unittest discover -s tests   # from starter/python/
```

`tests/test_heap.py` runs in well under a second (pure Python, no
sockets). `tests/test_gateway.py` starts its own runtime subprocess
automatically — it does not require `make run` to already be running —
and exercises the scenarios listed in the plan's verification section,
including the two heap services' example payloads straight from
`spec/PROJECT1_ASTAR.md`.
