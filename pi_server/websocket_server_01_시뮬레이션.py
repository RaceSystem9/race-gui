from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
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


def _build_simulation_config(args: argparse.Namespace) -> Dict[str, Any]:
    seed = args.seed
    if seed is not None:
        random.seed(seed)
    return {
        "ack_delay_ms": max(0.0, float(args.ack_delay_ms)),
        "ack_jitter_ms": max(0.0, float(args.ack_jitter_ms)),
        "ack_drop_rate": min(1.0, max(0.0, float(args.ack_drop_rate))),
        "ack_fail_rate": min(1.0, max(0.0, float(args.ack_fail_rate))),
        "disconnect_after_ack_rate": min(1.0, max(0.0, float(args.disconnect_after_ack_rate))),
    }


async def _handle_client_with_simulation(
    websocket: websockets.WebSocketServerProtocol,
    simulation: Dict[str, Any],
) -> None:
    print("client connected")
    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                print(f"invalid json: {raw_message}")
                continue

            message_type = str(message.get("type", "unknown"))
            if message_type not in {"state_update", "set_traffic_light"}:
                print(f"message => {message}")
                continue

            traffic_light = _extract_traffic_light(message)
            print(f"traffic light => {traffic_light}")

            if random.random() < simulation["ack_drop_rate"]:
                print("ack dropped (simulated)")
                continue

            delay_ms = simulation["ack_delay_ms"]
            jitter_ms = simulation["ack_jitter_ms"]
            if jitter_ms > 0.0:
                delay_ms += random.uniform(0.0, jitter_ms)
            if delay_ms > 0.0:
                await asyncio.sleep(delay_ms / 1000.0)

            status = "fail" if random.random() < simulation["ack_fail_rate"] else "ok"
            await websocket.send(
                json.dumps(
                    {
                        "type": "ack",
                        "payload": {
                            "message_type": message_type,
                            "traffic_light": traffic_light,
                            "status": status,
                        },
                    }
                )
            )

            if random.random() < simulation["disconnect_after_ack_rate"]:
                print("disconnect after ack (simulated)")
                await websocket.close(code=1011, reason="simulated disconnect")
                return
    except websockets.ConnectionClosed:
        print("client disconnected")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple WebSocket server for traffic light commands")
    parser.add_argument("--host", default=os.getenv("WS_HOST", "0.0.0.0"), help="Bind host (default: WS_HOST or 0.0.0.0)")
    parser.add_argument("--port", default=int(os.getenv("WS_PORT", "8765")), type=int, help="Bind port (default: WS_PORT or 8765)")
    parser.add_argument("--ack-delay-ms", default=float(os.getenv("WS_ACK_DELAY_MS", "0")), type=float, help="Fixed ACK delay in milliseconds")
    parser.add_argument("--ack-jitter-ms", default=float(os.getenv("WS_ACK_JITTER_MS", "0")), type=float, help="Additional random ACK delay in milliseconds")
    parser.add_argument("--ack-drop-rate", default=float(os.getenv("WS_ACK_DROP_RATE", "0")), type=float, help="Probability [0..1] to drop ACK")
    parser.add_argument("--ack-fail-rate", default=float(os.getenv("WS_ACK_FAIL_RATE", "0")), type=float, help="Probability [0..1] to send ACK status=fail")
    parser.add_argument("--disconnect-after-ack-rate", default=float(os.getenv("WS_DISCONNECT_AFTER_ACK_RATE", "0")), type=float, help="Probability [0..1] to disconnect right after ACK")
    parser.add_argument("--seed", default=None, type=int, help="Random seed for reproducible simulation")
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
    args = _parse_args()
    simulation = _build_simulation_config(args)

    async def client_handler(ws: websockets.WebSocketServerProtocol) -> None:
        await _handle_client_with_simulation(ws, simulation)

    async with websockets.serve(client_handler, host, port, ping_interval=10, ping_timeout=10):
        print(f"WebSocket server listening on ws://{host}:{port}/race")
        print(
            "Simulation settings: "
            f"ack_delay_ms={simulation['ack_delay_ms']}, "
            f"ack_jitter_ms={simulation['ack_jitter_ms']}, "
            f"ack_drop_rate={simulation['ack_drop_rate']}, "
            f"ack_fail_rate={simulation['ack_fail_rate']}, "
            f"disconnect_after_ack_rate={simulation['disconnect_after_ack_rate']}"
        )
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
