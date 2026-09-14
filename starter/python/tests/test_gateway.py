"""
tests/test_gateway.py — Integration tests that launch the *real* runtime
(`python3 src/main.py`, exactly what `make run` executes) as a subprocess
and drive it purely over the external TCP/JSON protocol, using raw
sockets in the same style as tools/map_to_rosbridge.py. These are
black-box tests: they exercise this project the same way Autograder.io
eventually will, and none of them import broker.py/connection.py/etc.
directly.

Run with:  python3 -m unittest discover -s tests   (from starter/python/)

One server subprocess is shared across the whole test class (starting a
fresh process per test would be needlessly slow); each test instead opens
its own client connection(s) and closes them when done, so tests stay
independent of each other even though the runtime process itself persists.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # starter/python/
HOST, PORT = "127.0.0.1", 9095


class RawClient:
    """A minimal hand-rolled protocol client for tests: connect, send one
    JSON object per line, and read one JSON object per line back.

    Deliberately independent of src/protocol.py's LineReader — these
    tests talk to the runtime the same way any external, unrelated client
    (including the autograder) would, so they shouldn't rely on any
    internal implementation detail to pass.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        self._buffer = b""

    def send(self, message: Dict[str, Any]) -> None:
        self.sock.sendall(json.dumps(message).encode("utf-8") + b"\n")

    def send_raw(self, raw: bytes) -> None:
        self.sock.sendall(raw)

    def read_message(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Block (up to `timeout` seconds) for the next complete JSON line."""
        self.sock.settimeout(timeout)
        while b"\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed before a full message arrived")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return json.loads(line.decode("utf-8"))

    def expect_no_message(self, timeout: float = 0.3) -> None:
        """Assert nothing arrives within `timeout` seconds — used to prove
        a negative, e.g. "this subscriber must NOT receive this publish."
        """
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return
        except OSError:
            return
        if data:
            raise AssertionError(f"expected no message, but got: {data!r}")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class GatewayTestCase(unittest.TestCase):
    """Base class that starts one runtime subprocess for the whole test
    class and tears it down afterward, the same way `make run` /
    Ctrl-C would from a user's terminal.
    """

    process: subprocess.Popen

    @classmethod
    def setUpClass(cls) -> None:
        cls.process = subprocess.Popen(
            [sys.executable, "src/main.py"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        cls._wait_for_port()

    @classmethod
    def _wait_for_port(cls, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                output = cls.process.stdout.read() if cls.process.stdout else ""
                raise RuntimeError(f"runtime exited early during startup:\n{output}")
            try:
                socket.create_connection((HOST, PORT), timeout=0.2).close()
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        raise TimeoutError(f"runtime never started listening on {HOST}:{PORT}: {last_error}")

    @classmethod
    def tearDownClass(cls) -> None:
        # SIGTERM, the same signal `make run`'s foreground process would
        # get from Ctrl-C/process-group termination during grading.
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5.0)
            raise AssertionError("runtime did not exit cleanly within 5s of SIGTERM")

    def make_client(self, timeout: float = 5.0) -> RawClient:
        client = RawClient(timeout=timeout)
        self.addCleanup(client.close)
        return client


class TestTopicsAndServices(GatewayTestCase):
    def test_topic_isolation(self) -> None:
        # Two different topic names must never leak into each other.
        a = self.make_client()
        b = self.make_client()
        publisher = self.make_client()

        a.send({"op": "subscribe", "topic": "/x", "type": "std_msgs/String", "id": "sub-a"})
        self.assertEqual(a.read_message()["op"], "status", "subscribe must be acknowledged with a status message")
        b.send({"op": "subscribe", "topic": "/y", "type": "std_msgs/String", "id": "sub-b"})
        self.assertEqual(b.read_message()["op"], "status")

        publisher.send({"op": "advertise", "topic": "/x", "type": "std_msgs/String"})
        publisher.send({"op": "publish", "topic": "/x", "msg": {"data": "hello"}})

        delivered = a.read_message()
        self.assertEqual(
            delivered, {"op": "publish", "topic": "/x", "msg": {"data": "hello"}},
            "subscriber to /x must receive exactly the message published on /x",
        )
        b.expect_no_message()  # subscriber to /y must never see a /x publish

    def test_duplicate_subscribe_delivers_exactly_once(self) -> None:
        client = self.make_client()
        publisher = self.make_client()
        for _ in range(2):
            client.send({"op": "subscribe", "topic": "/dup", "type": "std_msgs/String"})
        # Both subscribe requests get an informational status...
        client.read_message()
        client.read_message()
        publisher.send({"op": "advertise", "topic": "/dup", "type": "std_msgs/String"})
        publisher.send({"op": "publish", "topic": "/dup", "msg": {"data": "once"}})
        # ...but the underlying registration is a *set*, so exactly one
        # publish message should follow, not two.
        first = client.read_message()
        self.assertEqual(first["msg"], {"data": "once"})
        client.expect_no_message()  # a second identical delivery would mean subscribers isn't deduplicated

    def test_disconnect_cleans_up_and_others_keep_working(self) -> None:
        doomed = RawClient()
        doomed.send({"op": "subscribe", "topic": "/z", "type": "std_msgs/String"})
        doomed.read_message()
        doomed.close()
        time.sleep(0.2)  # give the reader thread a moment to notice EOF

        # A totally unrelated client must be unaffected by the disconnect
        # above — this is the "one bad connection can't take down the
        # gateway" guarantee from the protocol spec.
        survivor = self.make_client()
        survivor.send({"op": "subscribe", "topic": "/z", "type": "std_msgs/String"})
        self.assertEqual(survivor.read_message()["op"], "status")
        publisher = self.make_client()
        publisher.send({"op": "advertise", "topic": "/z", "type": "std_msgs/String"})
        publisher.send({"op": "publish", "topic": "/z", "msg": {"data": "still alive"}})
        self.assertEqual(
            survivor.read_message()["msg"], {"data": "still alive"},
            "an unrelated subscriber must still receive publishes after a different connection disconnects",
        )

    def test_publish_without_advertise_is_not_delivered(self) -> None:
        # Baseline for the unadvertise scenario below: a connection that
        # never advertised at all must not be able to publish either.
        subscriber = self.make_client()
        subscriber.send({"op": "subscribe", "topic": "/never-advertised", "type": "std_msgs/String"})
        self.assertEqual(subscriber.read_message()["op"], "status")

        publisher = self.make_client()
        publisher.send({"op": "publish", "topic": "/never-advertised", "msg": {"data": "unauthorized"}})
        subscriber.expect_no_message()

    def test_publish_after_unadvertise_is_not_delivered(self) -> None:
        # The exact scenario: advertise, publish (works), unadvertise,
        # publish again on the same connection -- that second publish
        # must not reach a still-subscribed client. Withdrawing publisher
        # registration must actually stop future publishes, not just
        # update bookkeeping nothing else looks at.
        publisher = self.make_client()
        publisher.send({"op": "advertise", "topic": "/withdraw-me", "type": "std_msgs/String"})

        subscriber = self.make_client()
        subscriber.send({"op": "subscribe", "topic": "/withdraw-me", "type": "std_msgs/String"})
        self.assertEqual(subscriber.read_message()["op"], "status")

        publisher.send({"op": "publish", "topic": "/withdraw-me", "msg": {"data": "before"}})
        self.assertEqual(subscriber.read_message()["msg"], {"data": "before"})

        publisher.send({"op": "unadvertise", "topic": "/withdraw-me"})
        publisher.send({"op": "publish", "topic": "/withdraw-me", "msg": {"data": "stale"}})
        subscriber.expect_no_message()

        # Re-advertising must restore the ability to publish -- this
        # isn't a one-way trip.
        publisher.send({"op": "advertise", "topic": "/withdraw-me", "type": "std_msgs/String"})
        publisher.send({"op": "publish", "topic": "/withdraw-me", "msg": {"data": "after"}})
        self.assertEqual(
            subscriber.read_message()["msg"], {"data": "after"},
            "re-advertising after an unadvertise must restore the ability to publish",
        )

    def test_service_round_trip_preserves_caller_id(self) -> None:
        provider = self.make_client()
        provider.send({"op": "advertise_service", "service": "/echo", "type": "test/Echo", "id": "adv-1"})
        self.assertEqual(provider.read_message()["op"], "status")

        caller = self.make_client()
        caller.send({"op": "call_service", "service": "/echo", "id": "call-17", "args": {"n": 42}})

        forwarded = provider.read_message()
        self.assertEqual(forwarded["op"], "call_service")
        self.assertEqual(forwarded["args"], {"n": 42}, "the provider must receive the caller's original args unchanged")
        # The provider-side id must NOT be the caller's original id — see
        # broker.py's PendingCall docstring for why that distinction
        # matters (two different callers could reuse "call-17").
        self.assertNotEqual(
            forwarded["id"], "call-17",
            "the forwarded call must use a broker-minted provider-side id, not the caller's raw id",
        )

        provider.send(
            {
                "op": "service_response",
                "service": "/echo",
                "id": forwarded["id"],
                "values": {"echo": forwarded["args"]},
                "result": True,
                "status": "",
            }
        )
        response = caller.read_message()
        self.assertEqual(response["op"], "service_response")
        self.assertEqual(
            response["id"], "call-17", "the response back to the caller must use the caller's own original id"
        )
        self.assertTrue(response["result"])
        self.assertEqual(response["values"], {"echo": {"n": 42}})

    def test_call_id_collision_across_callers_does_not_cross_talk(self) -> None:
        provider = self.make_client()
        provider.send({"op": "advertise_service", "service": "/tag", "type": "test/Tag"})
        provider.read_message()

        caller_a = self.make_client()
        caller_b = self.make_client()
        # Both callers independently choose the same id value, which the
        # protocol explicitly permits (ids only need to be unique *within*
        # one caller's own outstanding requests).
        caller_a.send({"op": "call_service", "service": "/tag", "id": "dup", "args": {"who": "a"}})
        caller_b.send({"op": "call_service", "service": "/tag", "id": "dup", "args": {"who": "b"}})

        forwarded_1 = provider.read_message()
        forwarded_2 = provider.read_message()
        for forwarded in (forwarded_1, forwarded_2):
            who = forwarded["args"]["who"]
            provider.send(
                {
                    "op": "service_response",
                    "service": "/tag",
                    "id": forwarded["id"],
                    "values": {"answered": who},
                    "result": True,
                    "status": "",
                }
            )

        response_a = caller_a.read_message()
        response_b = caller_b.read_message()
        self.assertEqual(response_a["id"], "dup")
        self.assertEqual(response_b["id"], "dup")
        self.assertEqual(
            response_a["values"], {"answered": "a"},
            "caller_a's response must be its own answer, not caller_b's, despite the shared id 'dup'",
        )
        self.assertEqual(response_b["values"], {"answered": "b"})

    def test_call_with_no_provider_fails_promptly(self) -> None:
        caller = self.make_client()
        started = time.monotonic()
        caller.send({"op": "call_service", "service": "/nobody_home", "id": "call-x", "args": {}})
        response = caller.read_message(timeout=2.0)
        elapsed = time.monotonic() - started
        self.assertFalse(response["result"], "calling a service with no provider must fail")
        self.assertEqual(response["id"], "call-x")
        # A missing provider is known synchronously in broker.py (no timer
        # is started), so this must return almost immediately, not after
        # waiting out the multi-second service-call timeout.
        self.assertLess(
            elapsed, 1.0,
            f"a missing-provider failure must be synchronous (< 1s), took {elapsed:.2f}s -- "
            f"looks like it fell through to the timeout path instead",
        )

    def test_provider_disconnect_mid_call_fails_the_caller(self) -> None:
        provider = self.make_client()
        provider.send({"op": "advertise_service", "service": "/flaky", "type": "test/Flaky"})
        provider.read_message()

        caller = self.make_client()
        caller.send({"op": "call_service", "service": "/flaky", "id": "call-y", "args": {}})
        provider.read_message()  # receive the forwarded call, then vanish without answering
        provider.close()

        response = caller.read_message(timeout=2.0)
        self.assertFalse(response["result"], "a caller must get result:false when its provider vanishes mid-call")
        self.assertEqual(response["id"], "call-y")

    def test_unadvertise_service_removes_provider(self) -> None:
        provider = self.make_client()
        provider.send({"op": "advertise_service", "service": "/temp", "type": "test/Temp"})
        provider.read_message()
        provider.send({"op": "unadvertise_service", "service": "/temp"})
        time.sleep(0.2)

        caller = self.make_client()
        caller.send({"op": "call_service", "service": "/temp", "id": "after-withdraw", "args": {}})
        response = caller.read_message(timeout=2.0)
        self.assertFalse(
            response["result"],
            "calling a service after its only provider unadvertised must fail (no provider), not hang or succeed",
        )

    def test_unadvertise_service_only_removes_if_sender_is_current_owner(self) -> None:
        # Spec: "unadvertise_service removes a service only when the
        # sender is its current provider." A connection that never owned
        # the service must not be able to evict the real provider.
        real_provider = self.make_client()
        real_provider.send({"op": "advertise_service", "service": "/owned", "type": "test/Owned"})
        real_provider.read_message()

        impostor = self.make_client()
        impostor.send({"op": "unadvertise_service", "service": "/owned"})  # never advertised /owned itself
        time.sleep(0.2)

        caller = self.make_client()
        caller.send({"op": "call_service", "service": "/owned", "id": "still-owned", "args": {}})
        forwarded = real_provider.read_message(timeout=2.0)
        self.assertEqual(
            forwarded["service"], "/owned",
            "the real provider must still receive forwarded calls -- an unrelated connection's "
            "unadvertise_service must not have evicted it",
        )
        real_provider.send({
            "op": "service_response", "service": "/owned", "id": forwarded["id"],
            "values": {}, "result": True, "status": "",
        })
        response = caller.read_message(timeout=2.0)
        self.assertTrue(response["result"], "the call must still succeed through the still-registered real provider")

    def test_advertise_service_conflict_first_registrant_wins(self) -> None:
        first = self.make_client()
        first.send({"op": "advertise_service", "service": "/contested", "type": "test/Contested", "id": "first-adv"})
        first_ack = first.read_message()
        self.assertEqual(first_ack["level"], "info", "the first registrant's advertise_service must succeed")

        second = self.make_client()
        second.send({"op": "advertise_service", "service": "/contested", "type": "test/Contested", "id": "second-adv"})
        second_ack = second.read_message()
        self.assertEqual(
            second_ack["level"], "error",
            "a second advertise_service for an already-owned service must be rejected with an error status",
        )

        # Calls must still route to the first (winning) registrant, never the second.
        caller = self.make_client()
        caller.send({"op": "call_service", "service": "/contested", "id": "route-check", "args": {}})
        forwarded = first.read_message(timeout=2.0)
        self.assertEqual(forwarded["service"], "/contested")
        second.expect_no_message(timeout=0.3)  # the loser must never receive a forwarded call

    def test_malformed_line_does_not_crash_connection_or_gateway(self) -> None:
        client = self.make_client()
        client.send_raw(b"not json at all\n")
        error = client.read_message()
        self.assertEqual(error["op"], "status")
        self.assertEqual(error["level"], "error", "malformed input must produce an error status, not be silently dropped")

        # The same connection must still work afterward...
        client.send({"op": "subscribe", "topic": "/after-garbage", "type": "std_msgs/String"})
        self.assertEqual(
            client.read_message()["op"], "status",
            "the same connection must still work after sending malformed input",
        )

        # ...and an unrelated client must never have noticed anything.
        other = self.make_client()
        other.send({"op": "subscribe", "topic": "/still-fine", "type": "std_msgs/String"})
        self.assertEqual(other.read_message()["op"], "status")

    def test_multiple_messages_in_one_send_are_both_processed(self) -> None:
        client = self.make_client()
        two_lines = (
            json.dumps({"op": "subscribe", "topic": "/multi-a", "type": "t", "id": "1"})
            + "\n"
            + json.dumps({"op": "subscribe", "topic": "/multi-b", "type": "t", "id": "2"})
            + "\n"
        )
        client.send_raw(two_lines.encode("utf-8"))
        first = client.read_message()
        second = client.read_message()
        self.assertEqual(
            {first["id"], second["id"]}, {"1", "2"},
            "both messages sent in a single TCP write must be parsed and processed, not just the first",
        )

    def test_message_split_across_two_sends_is_still_parsed(self) -> None:
        client = self.make_client()
        whole = json.dumps({"op": "subscribe", "topic": "/split", "type": "t", "id": "s1"}) + "\n"
        midpoint = len(whole) // 2
        client.send_raw(whole[:midpoint].encode("utf-8"))
        time.sleep(0.1)  # force these onto two separate recv() calls, not one
        client.send_raw(whole[midpoint:].encode("utf-8"))
        message = client.read_message()
        self.assertEqual(
            message["id"], "s1", "a message split across two TCP writes must still be reassembled and parsed"
        )

    def test_slow_subscriber_does_not_block_other_clients(self) -> None:
        # A subscriber that stops calling recv() will eventually back up
        # its own outbound buffer, but must never stall delivery to (or
        # service calls from) anyone else.
        slow = self.make_client()
        slow.send({"op": "subscribe", "topic": "/firehose", "type": "std_msgs/String"})
        slow.read_message()  # consume the subscribe status, then stop reading

        publisher = self.make_client()
        publisher.send({"op": "advertise", "topic": "/firehose", "type": "std_msgs/String"})
        big_payload = {"data": "x" * 4096}
        for _ in range(500):  # enough to fill a typical kernel socket buffer
            publisher.send({"op": "publish", "topic": "/firehose", "msg": big_payload})

        # Meanwhile, a completely unrelated client must still get prompt
        # service, proving the broker lock/queueing design isn't stalled
        # by `slow`'s full send buffer.
        other = self.make_client()
        other.send({"op": "subscribe", "topic": "/unrelated", "type": "std_msgs/String"})
        self.assertEqual(other.read_message(timeout=2.0)["op"], "status")
        other_publisher = self.make_client()
        other_publisher.send({"op": "advertise", "topic": "/unrelated", "type": "std_msgs/String"})
        other_publisher.send({"op": "publish", "topic": "/unrelated", "msg": {"data": "prompt"}})
        self.assertEqual(
            other.read_message(timeout=2.0)["msg"], {"data": "prompt"},
            "an unrelated client must get prompt delivery even while a slow subscriber's buffer is backed up",
        )


class TestHeapServicesOverTheWire(GatewayTestCase):
    """End-to-end coverage for the Project 1 checkpoint services, hitting
    them the same way an external grader would: call_service over TCP,
    not a direct Python function call. Algorithmic correctness (heap
    property, multiset preservation) is already covered thoroughly by
    tests/test_heap.py; these tests exist to confirm the *wiring*
    (services/provider.py's in-process adapter, broker.py's routing) is
    correct, not to re-derive the algorithm's correctness.
    """

    def _call(self, client: RawClient, service: str, args: Dict[str, Any], call_id: str) -> Dict[str, Any]:
        client.send({"op": "call_service", "service": service, "id": call_id, "args": args})
        response = client.read_message(timeout=2.0)
        self.assertEqual(response["id"], call_id)
        return response

    def test_heapify_example_from_spec(self) -> None:
        client = self.make_client()
        response = self._call(client, "/heapify", {"values": [3.0, 1.0, 2.0]}, "h1")
        self.assertTrue(response["result"], f"expected /heapify to succeed, got: {response}")
        result_heap = response["values"]["heap"]
        self.assertEqual(sorted(result_heap), [1.0, 2.0, 3.0], "the returned heap must contain the same multiset")
        n = len(result_heap)
        for i in range(n):
            for child in (2 * i + 1, 2 * i + 2):
                if child < n:
                    self.assertLessEqual(
                        result_heap[i], result_heap[child],
                        f"heap property violated at index {i} via the /heapify service",
                    )

    def test_heap_sort_example_from_spec(self) -> None:
        client = self.make_client()
        response = self._call(client, "/heap_sort", {"numbers": [3.0, 1.0, 2.0]}, "s1")
        self.assertTrue(response["result"])
        self.assertEqual(response["values"]["sorted"], [1.0, 2.0, 3.0])

    def test_heap_sort_handles_empty_negative_and_duplicate_input(self) -> None:
        client = self.make_client()
        cases = [[], [-1.0, -1.0, 0.0, 5.5, -2.25]]
        for i, numbers in enumerate(cases):
            with self.subTest(numbers=numbers):
                response = self._call(client, "/heap_sort", {"numbers": numbers}, f"s-case-{i}")
                self.assertTrue(response["result"], f"expected success for input {numbers}, got: {response}")
                self.assertEqual(response["values"]["sorted"], sorted(numbers))

    def test_malformed_args_fail_cleanly_without_killing_the_service(self) -> None:
        client = self.make_client()
        bad = self._call(client, "/heap_sort", {"numbers": "not-a-list"}, "bad-1")
        self.assertFalse(bad["result"], "non-list 'numbers' must fail cleanly, not crash the service")

        # The service must still work for the next caller — a bad request
        # must not have wedged the in-process provider's worker thread.
        good = self._call(client, "/heap_sort", {"numbers": [2.0, 1.0]}, "good-1")
        self.assertTrue(good["result"], "a malformed prior request must not prevent a later valid one from working")
        self.assertEqual(good["values"]["sorted"], [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
