#!/usr/bin/env python3

import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import Int32
from std_msgs.msg import Int32MultiArray

from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    HistoryPolicy
)

DEVICE_ID = 201
SENSOR_ID = 1


class TrafficLightNode(Node):

    def __init__(self):

        super().__init__("tf_control")

        self.start_time = time.monotonic()
        self.last_heartbeat = time.monotonic()

        #
        # QoS
        #
        self.pub_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE
        )

        self.sub_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT
        )

        #
        # Publisher
        #
        self.pub = self.create_publisher(
            Int32MultiArray,
            "tf_light_control",
            self.pub_qos
        )

        #
        # Subscriber
        #
        self.create_subscription(
            Int32MultiArray,
            "tf_light_status",
            self.status_callback,
            self.sub_qos
        )

        self.create_subscription(
            Int32MultiArray,
            "tf_light_heartbeat",
            self.heartbeat_callback,
            self.sub_qos
        )

        self.get_logger().info("Traffic Light Controller Started")

    ########################################################

    def send_command(self, led):

        elapsed = int(
            (time.monotonic() - self.start_time) * 1000
        )

        msg = Int32MultiArray()

        msg.data = [
            led,
            DEVICE_ID,
            SENSOR_ID,
            elapsed
        ]

        self.pub.publish(msg)

        names = {
            0: "RED",
            1: "YELLOW",
            2: "ARROW",
            3: "GREEN"
        }

        print()
        print("--------------------------------------")
        print(f" SEND : {names[led]}")
        print("--------------------------------------")

    ########################################################

    def status_callback(self, msg):

        data = list(msg.data)

        print()
        print("========== STATUS ==========")

        print(f"Raw : {data}")

        if len(data) >= 4:

            names = {
                0: "RED",
                1: "YELLOW",
                2: "ARROW",
                3: "GREEN"
            }

            print(f"LED       : {names.get(data[0], data[0])}")
            print(f"Device ID : {data[1]}")
            print(f"Sensor ID : {data[2]}")
            print(f"Time(ms)  : {data[3]}")

        print("============================")

    ########################################################

    def heartbeat_callback(self, msg):

        self.last_heartbeat = time.monotonic()

        print(f"[Heartbeat] {msg.data[3]}")


############################################################

def heartbeat_monitor(node):

    while rclpy.ok():

        if time.monotonic() - node.last_heartbeat > 3:

            print()
            print("********************************")
            print(" ESP32 HEARTBEAT TIMEOUT")
            print("********************************")

            node.last_heartbeat = time.monotonic()

        time.sleep(1)


############################################################

def keyboard_loop(node):

    while rclpy.ok():

        print()
        print("=================================")
        print(" 1 : RED")
        print(" 2 : YELLOW")
        print(" 3 : ARROW")
        print(" 4 : GREEN")
        print(" 0 : EXIT")
        print("=================================")

        cmd = input("Select : ")

        if cmd == "0":
            break

        elif cmd == "1":
            node.send_command(0)

        elif cmd == "2":
            node.send_command(1)

        elif cmd == "3":
            node.send_command(2)

        elif cmd == "4":
            node.send_command(3)

        else:
            print("Wrong Input")


############################################################

def main():

    rclpy.init()

    node = TrafficLightNode()

    executor = MultiThreadedExecutor()

    executor.add_node(node)

    executor_thread = threading.Thread(
        target=executor.spin,
        daemon=True
    )

    executor_thread.start()

    heartbeat_thread = threading.Thread(
        target=heartbeat_monitor,
        args=(node,),
        daemon=True
    )

    heartbeat_thread.start()

    try:

        keyboard_loop(node)

    except KeyboardInterrupt:
        pass

    executor.shutdown()

    node.destroy_node()

    rclpy.shutdown()


############################################################

if __name__ == "__main__":
    main()
