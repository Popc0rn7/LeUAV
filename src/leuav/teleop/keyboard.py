#!/usr/bin/env python3
"""PC ROS Humble 键盘输入；通过 DDS 连接 PC 或 RoboPi flight 节点。"""
import math
import os
import re
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.qos import QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import Twist
from std_msgs.msg import String

from .terminal import RecentKeys, Terminal

PREFIX = 'teleop'


def map_keys(keys, authority=.5):
    if 'space' in keys:
        return (0.,)*4
    def axis(positive, negative):
        return authority*(int(positive in keys)-int(negative in keys))
    return axis('w', 's'), axis('a', 'd'), axis('up', 'down'), axis('left', 'right')


def command_for(key):
    return {'l': 'takeoff', 'k': 'land'}.get(key)


def ros_namespace(identity):
    """ROS 名字不能以数字开头：统一加 user 前缀（01 → user01，00 → user00）。"""
    return 'user'+identity if re.fullmatch(r'0[0-6]', identity) else identity


class Keyboard(Node):
    map_keys = staticmethod(map_keys)
    command_for = staticmethod(command_for)

    def __init__(self):
        from .protocol import namespace
        super().__init__('keyboard', namespace=namespace())
        self.keys = RecentKeys()
        self.status = '等待 RoboPi flight 状态'
        self.status_at = -math.inf
        self.axes = (0.,)*4
        try:
            self.connect_ros()
        except BaseException:
            self.destroy_node()
            raise
        self.timer = self.create_timer(.05, self.publish_input, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def connect_ros(self):
        self.input_pub = self.create_publisher(Twist, PREFIX+'/input', QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.command_pub = self.create_publisher(String, PREFIX+'/command', 1)
        self.create_subscription(String, PREFIX+'/status', self.on_status, 1)

    def on_status(self, msg):
        self.status = msg.data
        self.status_at = time.monotonic()

    def on_key(self, key):
        command = self.command_for(key)
        if command:
            if command == 'land':
                self.keys.press('space', time.monotonic())
            if command != 'takeoff' or time.monotonic()-self.status_at < 1:
                msg = String()
                msg.data = command
                self.command_pub.publish(msg)  # L 的请求在这里发往 RoboPi。
        elif key in ('w', 's', 'a', 'd', 'up', 'down', 'left', 'right', 'space'):
            self.keys.press(key, time.monotonic())

    def publish_input(self):
        self.axes = self.map_keys(self.keys.active(time.monotonic()))
        if len(self.axes) != 4 or not all(math.isfinite(x) and abs(x) <= 1 for x in self.axes):
            raise ValueError('映射须返回四个 [-1,1] 有限数值')
        msg = Twist()
        msg.linear.x, msg.linear.y, msg.linear.z, msg.angular.z = map(float, self.axes)
        self.send_input(msg)

    def send_input(self, msg):
        self.input_pub.publish(msg)


def main(node_type=Keyboard):
    if not os.environ.get('ROS_DOMAIN_ID'):
        raise RuntimeError('请先加载案例 ROS 环境（ROS_DOMAIN_ID）')
    rclpy.init()
    node = None
    try:
        node = node_type()
        with Terminal() as terminal:
            while rclpy.ok():
                for key in terminal.read_keys():
                    if key in ('q', '\x03'):
                        return
                    node.on_key(key)
                # 处理收到的状态消息和 20 Hz 发布定时器。
                rclpy.spin_once(node, timeout_sec=.01)
                status = node.status if time.monotonic()-node.status_at < 1 else '控制端状态未到达/超时'
                terminal.draw(['W forward | L takeoff | Q/Ctrl+C land request + exit',
                               'S/A/D, arrows control | K land | SPACE neutral.',
                               'axes: '+str(node.axes), status])
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # 退出时回中并请求降落；仍需通过仿真 status 确认实际落地与 Disarmed。
        if node is not None and rclpy.ok():
            node.destroy_timer(node.timer)
            node.input_pub.publish(Twist())
            node.command_pub.publish(String(data='land'))
            end = time.monotonic()+.2
            while rclpy.ok() and time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=.02)
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
