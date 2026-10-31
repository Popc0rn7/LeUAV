#!/usr/bin/env python3
"""RoboPi：接收 keyboard 的 ROS 消息，桥接到 PX4，并返回飞行状态。

阅读顺序：__init__ 建立连接 → on_input/on_command 接收 →
manual_input/send_command 转换和发布 → on_status/on_ack 接收飞控反馈。
PC 的 MicroXRCEAgent 随 ADRL up 启动，本程序不管理它。
"""
import json
import math
import os
import re
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from px4_msgs.msg import ManualControlSetpoint, VehicleStatus, VehicleCommand, VehicleCommandAck

PREFIX = 'teleop'
INPUT_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)


def topic(name, message):
    version = getattr(message, 'MESSAGE_VERSION', 0)
    return name+(f'_v{version}' if version else '')


def manual_input(axes, stamp):
    """案例前/左/上/左转 → PX4 pitch/roll/throttle/yaw，四轴中位均为 0。"""
    forward, left, up, yaw_left = axes
    msg = ManualControlSetpoint()
    msg.timestamp = msg.timestamp_sample = int(stamp)
    msg.valid = True
    msg.data_source = ManualControlSetpoint.SOURCE_MAVLINK_0
    msg.source_system_id, msg.source_component_id = 246, 191
    msg.pitch, msg.roll = float(forward), float(-left)
    msg.throttle, msg.yaw = float(up), float(-yaw_left)
    # 不请求操纵量覆盖自动起降；只有 Position 驾驶阶段传非零轴。
    msg.sticks_moving = False
    return msg


def ros_namespace(identity):
    """ROS 名字不能以数字开头：统一加 user 前缀（01 → user01，00 → user00）。"""
    return 'user'+identity if re.fullmatch(r'0[0-6]', identity) else identity


class FlightController(Node):
    def __init__(self):
        from .protocol import namespace
        super().__init__('flight', namespace=namespace())
        try:
            self.check_exist()
            self.connect_keyboard()
        except BaseException:
            self.destroy_node()
            raise
        self.phase, self.reason = 'idle', 'Position：等待起飞请求'
        self.vehicle = None
        self.status_at = self.input_at = -math.inf
        self.axes = (0.,)*4
        self.deadline = self.last_report = 0.
        self.mode_retry_at = 0.
        self.pending = None
        self.accepted = False
        # 1. 发往 PX4：一次性命令（起降/模式）与持续的四轴操纵输入。
        self.command_pub = self.create_publisher(VehicleCommand, topic('/fmu/in/vehicle_command', VehicleCommand), 10)
        # 2. 发回 PC：键盘界面订阅这个状态话题。
        self.report_pub = self.create_publisher(String, PREFIX+'/status', 1)
        # 3. 从 PX4 收到状态与命令回执。传感器 QoS 与飞控发布端匹配。
        self.create_subscription(VehicleStatus, topic('/fmu/out/vehicle_status', VehicleStatus), self.on_status, qos_profile_sensor_data)
        self.create_subscription(VehicleCommandAck, topic('/fmu/out/vehicle_command_ack', VehicleCommandAck), self.on_ack, qos_profile_sensor_data)
        # 键盘订阅由开头的 connect_keyboard() 建立；回调在 spin 中执行。
        # 5. 20 Hz 持续转发；起飞过程和失流处理集中在 tick，作为进阶阅读。
        self.create_timer(.05, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def connect_keyboard(self):
        self.create_subscription(String, PREFIX+'/command', self.on_command, 1)
        self.create_subscription(Twist, PREFIX+'/input', self.on_input, INPUT_QOS)
        self.manual_pub = self.create_publisher(ManualControlSetpoint, topic('/fmu/in/manual_control_input', ManualControlSetpoint), 1)

    def input_axes(self, msg):
        return msg.linear.x, msg.linear.y, msg.linear.z, msg.angular.z

    def check_exist(self):
        """创建控制发布器前等待 DDS 发现；已有发布者就退出。"""
        topics = (topic('/fmu/in/manual_control_input', ManualControlSetpoint),
                  topic('/fmu/in/vehicle_command', VehicleCommand))
        self.get_logger().info('检查飞控控制话题占用，等待 DDS 发现（2 秒）')
        deadline = time.monotonic() + 2.
        while True:
            occupied = []
            for name in topics:
                for endpoint in self.get_publishers_info_by_topic(name):
                    owner = endpoint.node_namespace.rstrip('/') + '/' + endpoint.node_name
                    occupied.append(f'{name}：{owner}')
            if occupied:
                raise RuntimeError('飞控已有控制程序使用，flight 退出：\n' + '\n'.join(occupied))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            rclpy.spin_once(self, timeout_sec=min(.1, remaining))

    def on_status(self, msg):
        self.vehicle, self.status_at = msg, time.monotonic()

    def on_input(self, msg):
        """Twist 在本案例表达归一化操纵量，不是 m/s；先校验，再保存。"""
        values = self.input_axes(msg)
        if not all(math.isfinite(v) and abs(v) <= 1 for v in values):
            self.reason = '拒绝非法输入'
            return
        self.axes, self.input_at = values, time.monotonic()

    def fresh(self):
        return self.vehicle is not None and time.monotonic()-self.status_at < 2

    def armed(self):
        return self.vehicle is not None and self.vehicle.arming_state == VehicleStatus.ARMING_STATE_ARMED

    def send_command(self, command, *params):
        """将案例请求组装成 VehicleCommand，通过发布器发给 PX4。"""
        msg = VehicleCommand()
        msg.timestamp = int(self.vehicle.timestamp)
        msg.command = command
        for index, value in enumerate(params, 1):
            setattr(msg, 'param'+str(index), float(value))
        msg.target_system = msg.target_component = 1
        msg.source_system, msg.source_component = 246, 191
        msg.from_external = True
        self.pending, self.accepted = command, False
        self.command_pub.publish(msg)

    def on_ack(self, msg):
        if (msg.command != self.pending or msg.target_system != 246
                or msg.target_component not in (0, 191)):
            return
        if msg.result == VehicleCommandAck.VEHICLE_CMD_RESULT_ACCEPTED:
            self.accepted = True
        elif msg.result != VehicleCommandAck.VEHICLE_CMD_RESULT_IN_PROGRESS:
            if (msg.command == VehicleCommand.VEHICLE_CMD_DO_SET_MODE
                    and self.phase == 'position'):
                # PX4 在刚进入 AUTO_LOITER 的瞬间可能暂时拒绝切 POSCTL（result=1）；
                # 不立即放弃，回到 takeoff 稍后重试，超过 deadline 仍失败才释放。
                self.phase, self.pending, self.accepted = 'takeoff', None, False
                self.mode_retry_at = time.monotonic() + .5
                self.reason = f'PX4 暂拒切 POSCTL（result={msg.result}），稍后重试'
                self.get_logger().warning(self.reason)
                return
            self.phase, self.pending = 'released', None
            self.reason = f'PX4 拒绝命令 {msg.command}，result={msg.result}；查看 QGC'
            self.get_logger().warning(self.reason)

    def on_command(self, msg):
        if msg.data == 'land':
            if self.fresh() and self.armed():
                self.send_command(VehicleCommand.VEHICLE_CMD_NAV_LAND)
                self.phase, self.reason, self.deadline = 'landing', '已请求降落，等待 Disarmed', time.monotonic()+60
            return
        if msg.data != 'takeoff':
            return
        blockers = []
        if self.phase not in ('idle', 'done', 'released'):
            blockers.append('当前阶段为 '+self.phase)
        if not self.fresh():
            blockers.append('飞控状态未到达/超时，检查 DDS')
        if self.armed():
            blockers.append('已解锁，不重复起飞')
        if time.monotonic()-self.input_at > .5:
            blockers.append('键盘输入未到达/超时')
        if self.manual_pub.get_subscription_count() == 0:
            blockers.append('PX4 手动输入订阅未连接，检查固件 DDS 接口')
        if blockers:
            self.reason = '未发送起飞请求：'+'；'.join(blockers)
            self.get_logger().warning(self.reason)
            return
        # 与 PX4 commander takeoff 一致：请求自动起飞，获准后普通 arm。
        # NaN 表示使用飞控默认起飞目标；高度由 MIS_TAKEOFF_ALT 决定。
        self.send_command(VehicleCommand.VEHICLE_CMD_NAV_TAKEOFF, 0, 0, 0,
                          math.nan, math.nan, math.nan, math.nan)
        self.phase, self.reason, self.deadline = 'request_takeoff', '等待 PX4 接受自动起飞模式', time.monotonic()+5

    def tick(self):
        now = time.monotonic()
        if self.phase not in ('idle', 'done', 'released'):
            if not self.fresh():
                self.phase, self.reason = 'released', '飞控状态停流；停止输入，由 PX4 失流策略处理'
            elif self.phase != 'landing' and now-self.input_at >= .5:
                self.phase, self.reason = 'released', '键盘输入停流；停止手动输入，由 PX4 失流策略处理'
            elif self.phase == 'request_takeoff' and self.accepted and self.vehicle.nav_state == VehicleStatus.NAVIGATION_STATE_AUTO_TAKEOFF:
                self.send_command(VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, 1, 0)
                self.phase, self.reason, self.deadline = 'arming', '等待 PX4 解锁检查及实际解锁', now+5
            elif self.phase == 'arming' and self.armed():
                self.phase, self.reason, self.deadline = 'takeoff', 'PX4 自动起飞；运动按键暂不转发', now+45
            elif (self.phase == 'takeoff' and now >= self.mode_retry_at
                  and self.vehicle.nav_state == VehicleStatus.NAVIGATION_STATE_AUTO_LOITER):
                self.send_command(VehicleCommand.VEHICLE_CMD_DO_SET_MODE, 1, 3, 0)
                self.phase, self.reason, self.deadline = 'position', '起飞完成，等待 Position', now+5
            elif self.phase == 'position' and self.vehicle.nav_state == VehicleStatus.NAVIGATION_STATE_POSCTL:
                self.phase, self.reason = 'flying', 'Position 驾驶；回中、制动由 PX4 负责'
            elif self.phase in ('takeoff', 'position', 'flying', 'landing') and not self.armed():
                self.phase, self.reason = 'done', '已解除解锁；落地状态仍由赛务确认'
            elif self.phase == 'flying' and self.vehicle.nav_state != VehicleStatus.NAVIGATION_STATE_POSCTL:
                self.phase, self.reason = 'released', '外部退出 Position；停止输入，不夺回模式'
            elif self.phase in ('arming', 'takeoff') and self.vehicle.nav_state not in (VehicleStatus.NAVIGATION_STATE_AUTO_TAKEOFF, VehicleStatus.NAVIGATION_STATE_AUTO_LOITER):
                self.phase, self.reason = 'released', '自动起飞被外部模式切换打断；停止输入'
            elif self.phase != 'flying' and now > self.deadline:
                self.phase, self.reason = 'released', '命令/状态确认超时；查看 PX4 ACK 和 status，不重复解锁'
        # 输入停流不伪造永久中位、不额外发 Land；保留 PX4 原有手动失流策略。
        if self.fresh() and now-self.input_at < .5 and self.phase != 'released':
            axes = self.axes if self.phase == 'flying' else (0.,)*4
            self.send_manual(manual_input(axes, self.vehicle.timestamp))
        if now-self.last_report > .2:
            self.report_pub.publish(String(data=json.dumps(dict(
                phase=self.phase, reason=self.reason, armed=self.armed(),
                nav_state=self.vehicle.nav_state if self.vehicle else None,
                telemetry_fresh=self.fresh(), input_age_s=round(now-self.input_at, 2) if math.isfinite(self.input_at) else None))))
            self.last_report = now

    def send_manual(self, msg):
        self.manual_pub.publish(msg)

def main(node_type=FlightController):
    # PC 的 Agent 随 ADRL up 启动。板端只运行本 ROS 节点。
    # 与 模型服务 一样，先在 shell 加载 ros_env.sh，再运行程序。
    if not os.environ.get('ROS_DOMAIN_ID'):
        raise RuntimeError('请先加载案例 ROS 环境（ROS_DOMAIN_ID）')
    rclpy.init()
    node = None
    try:
        node = node_type()  # 先检查占用，再创建 ROS ↔ PX4 消息桥。
        node.get_logger().info('flight 已启动，等待键盘消息；PC 仿真需已 ADRL up')
        rclpy.spin(node)  # 接收消息时执行回调，定时执行 tick。
    except (KeyboardInterrupt, ExternalShutdownException):
        # 外部 Ctrl+C/SIGTERM 时 rclpy 抛 ExternalShutdownException；正常退出，不打印 traceback。
        pass
    finally:
        if node is not None:
            try:
                node.destroy_node()
            except Exception:  # 上下文已被外部关闭时 rmw 可能无法清理实体。
                pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(str(exc))
