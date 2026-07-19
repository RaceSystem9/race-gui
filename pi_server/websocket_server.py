from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from typing import Any, Dict

import websockets


def _extract_traffic_light(message: Dict[str, Any]) -> str:
    payload = message.get("payload", {})
    if isinstance(payload, dict):
        if "color" in payload:
            return str(payload.get("color", "UNKNOWN"))
        return str(payload.get("traffic_light", "UNKNOWN"))
    return "UNKNOWN"


async def handle_client(websocket: websockets.WebSocketServerProtocol) -> None:
    print("client connected")
    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                print(f"invalid json: {raw_message}")
                continue

            message_type = str(message.get("type", "unknown"))
            if message_type in {"state_update", "set_traffic_light"}:
                traffic_light = _extract_traffic_light(message)
                print(f"traffic light => {traffic_light}")
                await websocket.send(
                    json.dumps(
                        {
                            "type": "ack",
                            "payload": {
                                "message_type": message_type,
                                "traffic_light": traffic_light,
                                "status": "ok",
                            },
                        }
                    )
                )
            else:
                print(f"message => {message}")
    except websockets.ConnectionClosed:
        print("client disconnected")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple WebSocket server for traffic light commands")
    parser.add_argument("--host", default=os.getenv("WS_HOST", "0.0.0.0"), help="Bind host (default: WS_HOST or 0.0.0.0)")
    parser.add_argument("--port", default=int(os.getenv("WS_PORT", "8765")), type=int, help="Bind port (default: WS_PORT or 8765)")
    return parser.parse_args()


def _discover_local_ipv4() -> list[str]:
    discovered: list[str] = []
    host_name = socket.gethostname()
    candidates = set()

    # Hostname lookup
    try:
        for info in socket.getaddrinfo(host_name, None, family=socket.AF_INET):
            ip = info[4][0]
            candidates.add(ip)
    except socket.gaierror:
        pass

    # Outbound socket trick to identify primary local interface
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            candidates.add(probe.getsockname()[0])
    except OSError:
        pass

    for ip in sorted(candidates):
        if ip.startswith("127."):
            continue
        discovered.append(ip)

    return discovered


async def main(host: str, port: int) -> None:
    async with websockets.serve(handle_client, host, port, ping_interval=10, ping_timeout=10):
        print(f"WebSocket server listening on ws://{host}:{port}/race")
        local_ips = _discover_local_ipv4()
        if local_ips:
            endpoints = ", ".join(f"ws://{ip}:{port}/race" for ip in local_ips)
            print(f"Available local endpoints: {endpoints}")
        else:
            print("Available local endpoints: none detected")
        await asyncio.Future()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.host, int(args.port)))
