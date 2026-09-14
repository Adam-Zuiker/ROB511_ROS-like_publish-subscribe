# Project 1 — Python Runtime

Quick reference for running the runtime, the test suite, and the A* visualization tool. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the system is put together, and `spec/PROJECT1_ASTAR.md` / `spec/ROSBRIDGE_PROTOCOL.md` (in the course starter bundle) for the actual requirements.

## Running the code

All commands run from this directory (`starter/python/`).

```bash
make build   # python3 -m compileall -q src -- syntax-checks everything, no output on success
make run     # starts the runtime in the foreground on 127.0.0.1:9095
```

`make run` blocks in the foreground (that's the point — it's what the grader launches). Open a second terminal for anything else, including:

```bash
make map     # publishes maps/student_map.json on /map, then exits -- run this WHILE `make run` is active
```

`make clean` removes `__pycache__` directories; nothing else is generated.

To stop the runtime, `Ctrl-C` in its terminal (sends SIGINT, which triggers the orderly shutdown path in `main.py`).

### If the port won't bind

`make run` fails with `could not bind 127.0.0.1:9095: [Errno 48] Address already in use` when a previous run didn't exit cleanly (a killed terminal, an interrupted test run) and a stale process is still holding the port. Find and clear it:

```bash
lsof -i :9095                       # shows what's holding the port, and its PID
lsof -ti :9095 | xargs -r kill -9   # clears it
```

## Running the tests

From this directory:

```bash
python3 -m unittest discover -s tests           # the whole suite
python3 -m unittest discover -s tests -v        # verbose -- every test name + pass/fail
```

Run just one file, class, or test — `-k` matches anywhere in the test's `module.Class.method` name:

```bash
python3 -m unittest discover -s tests -k test_heap        # everything in test_heap.py
python3 -m unittest discover -s tests -k TestAStarSearch   # just one class
python3 -m unittest discover -s tests -k test_sift_down    # just tests with this in the name
```

`-x` stops at the first failure — useful when one root cause is cascading into many reported failures and you don't need to see all of them.

**Reading a failure:** `FAIL` means an assertion ran and got the wrong value — the message after the last colon names the specific invariant that broke. `ERROR` means something raised an unexpected exception before any assertion even ran; the traceback above it points at the exact line in the *production* code (not the test) that threw it.

**Test files, by what they cover:**

| File | Covers |
| --- | --- |
| `tests/test_heap.py` | `src/heap.py` — the hand-rolled binary min-heap |
| `tests/test_heap_service.py` | `src/services/heap_service.py` — `/heapify`/`/heap_sort` argument validation |
| `tests/test_map_store.py` | `src/map_store.py` — `/map` validation and storage |
| `tests/test_planner.py` | `src/planner.py` — geometry, A* search, `/plan_path` end to end |
| `tests/test_gateway.py` | `src/broker.py`/`src/connection.py`/`src/server.py` — pub/sub, services, cleanup, over real TCP/JSON |

`test_gateway.py` and `test_planner.py` launch a real `src/main.py` subprocess bound to port 9095 — see the "if the port won't bind" note above if a run behaves inexplicably; a leftover process from an interrupted run is the usual cause.

## The A* visualization tool

**[Frontier Console](https://claude.ai/code/artifact/d705e1f8-c133-4218-9e88-a0ca457d4d1f)** (hosted) or [`tools/frontier_console.html`](tools/frontier_console.html) (local — just open it in a browser, no server needed) — an interactive grid editor for watching A* search a maze step by step: paint walls, place start/goal, then run or single-step the search while a telemetry panel tracks iteration count, frontier size, and (the number that matters most here) how many times `heap_sort` gets called.

It's a **from-scratch JavaScript reimplementation**, not a live connection to this Python runtime — a browser artifact can't open a raw TCP socket to `127.0.0.1:9095`. It deliberately mirrors `planner.py`'s exact algorithm shape (frontier as a plain list, full re-sort by `f = g + h` every iteration instead of an incremental heap, lexicographic `(x, y)` tie-break, the staleness check for stale frontier entries) so it demonstrates *this* project's specific implementation, not generic textbook A*. Useful for building intuition about what a broken heuristic, tie-break, or frontier-update looks like *visually* before hunting for it in code.
