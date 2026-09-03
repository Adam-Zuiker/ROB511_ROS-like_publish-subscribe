#!/usr/bin/env python3
"""Publish one OccupancyGrid-like JSON document through Project 1 rosbridge.

This is an external-client example, not part of the Project 1 runtime.  It
uses only the public newline-delimited TCP/JSON protocol documented in
docs/ROSBRIDGE_PROTOCOL.md.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    raise ValueError(message)


def integer(value: Any, label: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        fail(f"{label} must be an integer")
    if positive and value <= 0:
        fail(f"{label} must be positive")


def number(value: Any, label: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{label} must be numeric")
    if not math.isfinite(value):
        fail(f"{label} must be finite")
    if positive and value <= 0:
        fail(f"{label} must be positive")


def object_field(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


def validate_map(payload: Any) -> dict[str, Any]:
    """Reject obvious malformed input before sending it to the runtime."""
    map_message = object_field(payload, "map")
    object_field(map_message.get("header"), "header")
    info = object_field(map_message.get("info"), "info")
    number(info.get("resolution"), "info.resolution", positive=True)
    integer(info.get("width"), "info.width", positive=True)
    integer(info.get("height"), "info.height", positive=True)
    origin = object_field(info.get("origin"), "info.origin")
    position = object_field(origin.get("position"), "info.origin.position")
    number(position.get("x"), "info.origin.position.x")
    number(position.get("y"), "info.origin.position.y")

    data = map_message.get("data")
    if not isinstance(data, list):
        fail("data must be an array")
    expected = info["width"] * info["height"]
    if len(data) != expected:
        fail(f"data must contain width * height entries ({expected})")
    for index, occupancy in enumerate(data):
        integer(occupancy, f"data[{index}]")
    return map_message


def send_line(connection: socket.socket, message: dict[str, Any]) -> None:
    connection.sendall(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish an OccupancyGrid-like JSON file on /map through Project 1 rosbridge."
    )
    parser.add_argument("map_json", type=Path, help="OccupancyGrid-like JSON payload")
    parser.add_argument("--host", default="127.0.0.1", help="rosbridge host (default: 127.0.0.1)")
    parser.add_argument("--port", default=9095, type=int, help="rosbridge port (default: 9095)")
    parser.add_argument("--timeout", default=5.0, type=float, help="connection timeout in seconds")
    args = parser.parse_args()

    try:
        with args.map_json.open(encoding="utf-8") as source:
            payload = validate_map(json.load(source))
        with socket.create_connection((args.host, args.port), timeout=args.timeout) as connection:
            send_line(connection, {"op": "advertise", "topic": "/map", "type": "nav_msgs/OccupancyGrid"})
            # The public protocol does not define an advertise acknowledgement.
            # Give direct-peer implementations a bounded opportunity to attach
            # current subscribers, then send a few equivalent best-effort
            # publications.  This is still one finite external-client action,
            # not a map server or a persistent publisher.
            time.sleep(0.2)
            for _ in range(3):
                send_line(connection, {"op": "publish", "topic": "/map", "msg": payload})
                time.sleep(0.05)
            send_line(connection, {"op": "unadvertise", "topic": "/map"})
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"map_to_rosbridge: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
