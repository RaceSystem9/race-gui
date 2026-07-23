#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import threading
import time
from typing import Any, Dict, Tuple

import websockets

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Int32MultiArray

# =============================================================================
# [1. 프로토콜 상수 및 색상/상태 매핑] (ROS2 Communication Protocol v1.0 기준)
# =============================================================================
COLOR_MAP = {
    "RED": 0,
    "YELLOW": 1,
    "ARROW": 2,
    "GREEN": 3,
    "OFF": 100,
    "BLINK": 101,
    "ALL_OFF": 102,
    "SELF_TEST": 103,
}
REV_COLOR_MAP = {v: k for k, v in COLOR_MAP.items()}

# 웹소켓 연결된 클라이언트 관리를 위한 집합
CONNECTED_CLIENTS = set()


# =============================================================================
# [2. ROS2 Integrated Node] 신호등 및 Gate Sensor 통합 노드
# =============================================================================
class IntegratedControlNode(Node):

    def __init__(self):
        super().__init__("integrated_control_node")

        self.start_time = time.monotonic()
        # 장치 식별자 키: (device_id, sensor_id) -> last_heartbeat_time
        self.device_heartbeats: Dict[Tuple[int, int], float] = {}

        # ---------------------------------------------------------------------
        # QoS 프로필 정의 (Protocol 6항)
        # ---------------------------------------------------------------------
        self.reliable_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
        )

        self.best_effort_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )

        # ---------------------------------------------------------------------
        # Publishers & Subscribers (Protocol 2항)
        # ---------------------------------------------------------------------
        # Traffic Light Publisher
        self.pub_tf_control = self.create_publisher(
            Int32MultiArray, "/tf_light_control", self.reliable_qos
        )

        # Traffic Light Subscribers
        self.create_subscription(
            Int32MultiArray, "/tf_light_status", self.tf_status_callback, self.best_effort_qos
        )
        self.create_subscription(
            Int32MultiArray, "/tf_light_heartbeat", self.tf_heartbeat_callback, self.best_effort_qos
        )

        # Gate Sensor Subscribers
        self.create_subscription(
            Int32MultiArray, "/gate_trigger", self.gate_trigger_callback, self.reliable_qos
        )
        self.create_subscription(
            Int32MultiArray, "/gate_heartbeat", self.gate_heartbeat_callback, self.best_effort_qos
        )

        self.get_logger().info("Integrated ROS 2 Control Node Started (Multi-Device Ready)")

    # -------------------------------------------------------------------------
    # Traffic Light 제어 명령 전송 (Protocol 5항)
    # -------------------------------------------------------------------------
    def send_traffic_command(self, cmd_val: int, device_id: int = 201, sensor_id: int = 1):
        elapsed = int((time.monotonic() - self.start_time) * 1000)

        msg = Int32MultiArray()
        # data format: [Value, Device ID, Sensor ID, Timestamp]
        msg.data = [cmd_val, device_id, sensor_id, elapsed]

        self.pub_tf_control.publish(msg)

        cmd_name = REV_COLOR_MAP.get(cmd_val, str(cmd_val))
        print(f"\n[ROS2 Send] -> Traffic Light [Dev:{device_id}, Sen:{sensor_id}] = {cmd_name}")

    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    def tf_status_callback(self, msg: Int32MultiArray):
        data = list(msg.data)
        if len(data) >= 4:
            val, dev_id, sen_id, ts = data[0], data[1], data[2], data[3]
            color_str = REV_COLOR_MAP.get(val, str(val))
            print(f"[ROS2 Status] Traffic Light [Dev:{dev_id}, Sen:{sen_id}] -> State: {color_str} (ts:{ts}ms)")

    def tf_heartbeat_callback(self, msg: Int32MultiArray):
        data = list(msg.data)
        if len(data) >= 4:
            dev_id, sen_id = data[1], data[2]
            self.device_heartbeats[(dev_id, sen_id)] = time.monotonic()

    def gate_trigger_callback(self, msg: Int32MultiArray):
        data = list(msg.data)
        if len(data) >= 4:
            val, dev_id, sen_id, ts = data[0], data[1], data[2], data[3]
            event_type = "DETECTED" if val == 1 else "NO_DETECTION"
            print(f"\n[ROS2 Event] Gate Sensor [Dev:{dev_id}, Sen:{sen_id}] -> {event_type} (ts:{ts}ms)")

            # 웹소켓 연결 클라이언트들에게 이벤트 실시간 브로드캐스트
            broadcast_msg = json.dumps({
                "type": "gate_trigger",
                "payload": {
                    "device_id": dev_id,
                    "sensor_id": sen_id,
                    "detected": bool(val == 1),
                    "value": val,
                    "timestamp": ts
                }
            })
            asyncio.run_coroutine_threadsafe(
                broadcast_to_clients(broadcast_msg),
                asyncio.get_event_loop()
            )

    def gate_heartbeat_callback(self, msg: Int32MultiArray):
        data = list(msg.data)
        if len(data) >= 4:
            dev_id, sen_id = data[1], data[2]
            self.device_heartbeats[(dev_id, sen_id)] = time.monotonic()


def heartbeat_monitor(node: IntegratedControlNode):
    """등록된 모든 장치의 생존 상태 모니터링 스레드"""
    while rclpy.ok():
        now = time.monotonic()
        for (dev_id, sen_id), last_time in list(node.device_heartbeats.items()):
            if now - last_time > 3.0:
                print(f"\n[WARNING] HEARTBEAT TIMEOUT -> Device ID: {dev_id}, Sensor ID: {sen_id}")
                node.device_heartbeats[(dev_id, sen_id)] = now  # 경고 중복 출력 방지용 갱신
        time.sleep(1)


# =============================================================================
# [3. WebSocket Server & Client Handler]
# =============================================================================
async def broadcast_to_clients(message: str):
    """접속된 모든 웹소켓 클라이언트에 메시지 송신 (Gate Sensor 감지 등)"""
    if CONNECTED_CLIENTS:
        await asyncio.gather(*[client.send(message) for client in CONNECTED_CLIENTS], return_exceptions=True)


async def handle_client(
    websocket: websockets.WebSocketServerProtocol,
    ros_node: IntegratedControlNode,
) -> None:
    CONNECTED_CLIENTS.add(websocket)
    print(f"WebSocket client connected. Total clients: {len(CONNECTED_CLIENTS)}")
    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                print(f"Invalid JSON: {raw_message}")
                continue

            message_type = str(message.get("type", "unknown"))

            if message_type in {"state_update", "set_traffic_light"}:
                payload = message.get("payload", {})
                
                # 색상 파싱
                color_str = str(payload.get("color", payload.get("traffic_light", "UNKNOWN"))).upper()
                
                # 다중 장치를 위한 ID 파싱 (기본값: Traffic Light #1 -> Dev:201, Sen:1)
                device_id = int(payload.get("device_id", 201))
                sensor_id = int(payload.get("sensor_id", 1))

                if color_str in COLOR_MAP:
                    cmd_val = COLOR_MAP[color_str]
                    ros_node.send_traffic_command(cmd_val, device_id=device_id, sensor_id=sensor_id)
                    status_result = "ok"
                else:
                    print(f"Unknown traffic light color requested: {color_str}")
                    status_result = "fail"

                # ACK 회신
                await websocket.send(
                    json.dumps({
                        "type": "ack",
                        "payload": {
                            "message_type": message_type,
                            "device_id": device_id,
                            "sensor_id": sensor_id,
                            "traffic_light": color_str,
                            "status": status_result,
                        },
                    })
                )
            else:
                print(f"[WebSocket Recv] Other message => {message}")

    except websockets.ConnectionClosed:
        pass
    finally:
        CONNECTED_CLIENTS.remove(websocket)
        print(f"WebSocket client disconnected. Total clients: {len(CONNECTED_CLIENTS)}")


def _discover_local_ipv4() -> list[str]:
    discovered: list[str] = []
    host_name = socket.gethostname()
    candidates = set()

    try:
        for info in socket.getaddrinfo(host_name, None, family=socket.AF_INET):
            candidates.add(info[4][0])
    except socket.gaierror:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            candidates.add(probe.getsockname()[0])
    except OSError:
        pass

    for ip in sorted(candidates):
        if not ip.startswith("127."):
            discovered.append(ip)

    return discovered


# =============================================================================
# [4. Main Entry Point]
# =============================================================================
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WebSocket Server integrated with ROS 2 (Traffic Lights & Gate Sensors)"
    )
    parser.add_argument("--host", default=os.getenv("WS_HOST", "0.0.0.0"), help="Bind host")
    parser.add_argument("--port", default=int(os.getenv("WS_PORT", "8765")), type=int, help="Bind port")
    return parser.parse_args()


async def main():
    args = _parse_args()

    # 1. ROS 2 초기화
    rclpy.init()
    ros_node = IntegratedControlNode()

    executor = MultiThreadedExecutor()
    executor.add_node(ros_node)

    # 2. ROS 2 Spin & Heartbeat Monitor 스레드 실행
    threading.Thread(target=executor.spin, daemon=True).start()
    threading.Thread(target=heartbeat_monitor, args=(ros_node,), daemon=True).start()

    # 3. WebSocket 서버 실행
    async def client_handler(ws: websockets.WebSocketServerProtocol) -> None:
        await handle_client(ws, ros_node)

    async with websockets.serve(client_handler, args.host, args.port, ping_interval=10, ping_timeout=10):
        print(f"WebSocket server listening on ws://{args.host}:{args.port}/race")
        local_ips = _discover_local_ipv4()
        if local_ips:
            print("Available local endpoints: " + ", ".join(f"ws://{ip}:{args.port}/race" for ip in local_ips))

        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass
        finally:
            executor.shutdown()
            ros_node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer shutting down...")