from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any, Dict

import websockets
from websockets.exceptions import WebSocketException


def _build_message(color: str) -> Dict[str, Any]:
    normalized = str(color).strip().upper()
    return {
        "type": "set_traffic_light",
        "payload": {
            "color": normalized,
        },
    }


def _parse_response(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"type": "invalid_json", "payload": {"raw": raw}}


def _print_result(parsed: Dict[str, Any], expected_color: str, elapsed_ms: int, expect_ok: bool) -> bool:
    message_type = str(parsed.get("type", "unknown"))
    payload = parsed.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    status = str(payload.get("status", "unknown"))
    server_color = str(payload.get("traffic_light", "UNKNOWN")).upper()
    source_type = str(payload.get("message_type", "unknown"))

    ok = message_type == "ack" and server_color == expected_color.upper()
    if expect_ok:
        ok = ok and status.lower() == "ok"

    print("--- RESPONSE SUMMARY ---")
    print(f"type        : {message_type}")
    print(f"status      : {status}")
    print(f"message_type: {source_type}")
    print(f"server_color: {server_color}")
    print(f"elapsed_ms  : {elapsed_ms}")
    if ok:
        print("result      : SUCCESS")
    else:
        print("result      : FAILED")
        print(f"raw         : {json.dumps(parsed, ensure_ascii=False)}")
    return ok


async def _run_client(
    host: str,
    port: int,
    path: str,
    color: str,
    timeout: float,
    repeat: int,
    interval: float,
    expect_ok: bool,
) -> int:
    path_value = path if path.startswith("/") else f"/{path}"
    uri = f"ws://{host}:{port}{path_value}"
    message = _build_message(color)
    passed = 0

    for index in range(max(1, repeat)):
        print(f"Connecting to {uri} (run {index + 1}/{max(1, repeat)})")
        try:
            async with websockets.connect(uri) as websocket:
                send_text = json.dumps(message, ensure_ascii=False)
                started = time.perf_counter()
                await websocket.send(send_text)
                print(f"Sent: {message}")
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    print(f"No response within {timeout:.1f} seconds")
                    continue

                elapsed_ms = int((time.perf_counter() - started) * 1000)
                parsed = _parse_response(str(response))
                is_ok = _print_result(parsed, expected_color=color, elapsed_ms=elapsed_ms, expect_ok=expect_ok)
                if is_ok:
                    passed += 1
        except OSError as error:
            print(f"Connection error: {error}")
        except WebSocketException as error:
            print(f"WebSocket error: {error}")

        if index < max(1, repeat) - 1 and interval > 0:
            await asyncio.sleep(interval)

    total = max(1, repeat)
    print("--- RUN SUMMARY ---")
    print(f"passed: {passed}")
    print(f"failed: {total - passed}")
    print(f"total : {total}")

    if passed == total:
        return 0
    if passed > 0:
        return 3
    return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a traffic light command to the Raspberry Pi WebSocket server")
    parser.add_argument("--host", default="192.168.0.18", help="Raspberry Pi server host")
    parser.add_argument("--port", default=8765, type=int, help="Raspberry Pi server port")
    parser.add_argument("--path", default="/race", help="WebSocket path (default: /race)")
    parser.add_argument("--timeout", default=5.0, type=float, help="ACK wait timeout in seconds")
    parser.add_argument("--repeat", default=1, type=int, help="Number of repeated attempts")
    parser.add_argument("--interval", default=0.5, type=float, help="Delay between attempts in seconds")
    parser.add_argument("--allow-fail-ack", action="store_true", help="Treat ACK status=fail as success for connectivity-only tests")
    parser.add_argument(
        "--color",
        default="GREEN",
        choices=["RED", "YELLOW", "GREEN"],
        help="Traffic light color to send",
    )
    args = parser.parse_args()
    exit_code = asyncio.run(
        _run_client(
            args.host,
            args.port,
            args.path,
            args.color,
            args.timeout,
            args.repeat,
            args.interval,
            expect_ok=not args.allow_fail_ack,
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
