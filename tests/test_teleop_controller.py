"""无 ROS 的控制状态机回归；替身只记录消息，不代表 DDS/飞行验收。"""

import importlib.util
import math
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Message:
    MESSAGE_VERSION = 0
    ARMING_STATE_ARMED = 2
    NAVIGATION_STATE_POSCTL = 2
    NAVIGATION_STATE_AUTO_LOITER = 4
    NAVIGATION_STATE_AUTO_TAKEOFF = 17
    VEHICLE_CMD_NAV_LAND = 21
    VEHICLE_CMD_NAV_TAKEOFF = 22
    VEHICLE_CMD_DO_SET_MODE = 176
    VEHICLE_CMD_COMPONENT_ARM_DISARM = 400
    VEHICLE_CMD_RESULT_ACCEPTED = 0
    VEHICLE_CMD_RESULT_IN_PROGRESS = 5
    SOURCE_MAVLINK_0 = 2

    def __init__(self, **kwargs):
        self.linear = types.SimpleNamespace(x=0., y=0., z=0.)
        self.angular = types.SimpleNamespace(x=0., y=0., z=0.)
        self.__dict__.update(kwargs)


class Publisher:
    def __init__(self):
        self.messages = []
        self.subscribers = 1

    def publish(self, msg):
        self.messages.append(msg)

    def get_subscription_count(self):
        return self.subscribers


class Node:
    def __init__(self, name, **kwargs):
        pass

    def get_logger(self):
        from unittest.mock import Mock
        return Mock()

    def declare_parameter(self, name, value):
        return types.SimpleNamespace(value=value)

    def create_publisher(self, *args):
        return Publisher()

    def create_subscription(self, *args):
        pass

    def create_timer(self, *args, **kwargs):
        pass


def load_controller(filename='flight.py'):
    modules = {}
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        modules[name] = mod
    module('rclpy')
    module('rclpy.executors', ExternalShutdownException=RuntimeError)
    module('rclpy.node', Node=Node)
    module('rclpy.clock', Clock=lambda **kw: None, ClockType=Message(STEADY_TIME=1))
    module('rclpy.qos', qos_profile_sensor_data=None, QoSProfile=lambda **kw: None,
           ReliabilityPolicy=Message(BEST_EFFORT=1))
    for parent, names in [('geometry_msgs', ['Twist']), ('std_msgs', ['String']),
                          ('px4_msgs', ['ManualControlSetpoint', 'VehicleStatus', 'VehicleCommand', 'VehicleCommandAck'])]:
        module(parent)
        module(parent+'.msg', **dict.fromkeys(names, Message))
    path = Path(__file__).resolve().parents[1] / 'src/leuav/teleop'/filename
    spec = importlib.util.spec_from_file_location('leuav.teleop._controller_under_test', path)
    result = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(result)
    return result


controller = load_controller()
class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(controller.time, 'monotonic', return_value=100.)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        identity = patch.dict(os.environ, LEUAV_NAMESPACE='/uav/demo/teleop')
        identity.start()
        self.addCleanup(identity.stop)
        with patch.object(controller.FlightController, 'check_exist'):
            self.node = controller.FlightController()
        self.node.on_status(Message(timestamp=123, arming_state=1, nav_state=4, pre_flight_checks_pass=False))
        self.input()

    def input(self, forward=0.):
        self.node.on_input(Message(linear=Message(x=forward, y=0., z=0.), angular=Message(z=0.)))

    def ack(self, command, result=0, system=246):
        self.node.on_ack(Message(command=command, result=result, target_system=system, target_component=191))

    def flying(self):
        self.node.phase = 'flying'
        self.node.vehicle.arming_state = 2
        self.node.vehicle.nav_state = 2

    def test_manual_axis_signs_and_zero_throttle(self):
        msg = controller.manual_input((.5, .2, -.3, .4), 123)
        self.assertEqual((msg.pitch,msg.roll,msg.throttle,msg.yaw), (.5,-.2,-.3,-.4))
        self.assertEqual(controller.manual_input((0,)*4,123).throttle, 0.)
        self.assertTrue(msg.valid)
        self.assertFalse(msg.sticks_moving)

    def test_takeoff_ack_and_actual_mode_required_before_arm(self):
        n=self.node
        n.on_command(Message(data='takeoff'))
        self.assertEqual(n.command_pub.messages[-1].command,22)
        n.vehicle.nav_state=17
        n.tick()
        self.assertEqual(len(n.command_pub.messages),1)
        self.ack(22)
        n.tick()
        self.assertEqual(n.command_pub.messages[-1].command,400)
        self.assertEqual(n.command_pub.messages[-1].param2,0.)  # 普通 arm，无强制值
        n.vehicle.arming_state=2
        n.tick()
        self.assertEqual(n.phase,'takeoff')
        n.vehicle.nav_state=4
        n.tick()
        self.assertEqual(n.command_pub.messages[-1].command,176)
        self.assertEqual(n.command_pub.messages[-1].param2,3.)  # Position
        n.vehicle.nav_state=2
        n.tick()
        self.assertEqual(n.phase,'flying')

    def test_px4_rejection_prevents_arm(self):
        self.node.on_command(Message(data='takeoff'))
        self.ack(22,2)
        self.node.tick()
        self.assertEqual(self.node.phase,'released')
        self.assertEqual(len(self.node.command_pub.messages),1)

    def test_foreign_ack_ignored(self):
        self.node.on_command(Message(data='takeoff'))
        self.ack(22,system=255)
        self.assertFalse(self.node.accepted)

    def test_no_extra_odometry_or_preflight_gate(self):
        self.node.on_command(Message(data='takeoff'))
        self.assertEqual(self.node.phase,'request_takeoff')
        self.assertFalse(hasattr(self.node,'odom'))

    def test_takeoff_requires_fresh_input_and_dds_subscriber(self):
        self.node.input_at=90
        self.node.manual_pub.subscribers=0
        self.node.on_command(Message(data='takeoff'))
        self.assertEqual(self.node.phase,'idle')
        self.assertIn('键盘输入',self.node.reason)
        self.assertIn('订阅',self.node.reason)
        self.assertFalse(self.node.command_pub.messages)

    def test_invalid_input_does_not_refresh_watchdog(self):
        self.now.return_value=101
        self.input(math.nan)
        self.assertEqual(self.node.input_at,100)
        self.input(2)
        self.assertEqual(self.node.input_at,100)

    def test_release_sends_neutral_without_position_setpoint(self):
        self.flying()
        self.input(1)
        self.node.tick()
        self.assertEqual(self.node.manual_pub.messages[-1].pitch,1.)
        self.input()
        self.node.tick()
        self.assertEqual(self.node.manual_pub.messages[-1].pitch,0.)
        self.assertFalse(hasattr(self.node,'setpoint_pub'))
        self.assertFalse(self.node.command_pub.messages)

    def test_input_timeout_stops_instead_of_masking_loss(self):
        self.flying()
        self.now.return_value=100.6
        self.node.tick()
        self.assertEqual(self.node.phase,'released')
        self.assertFalse(self.node.manual_pub.messages)
        self.assertFalse(self.node.command_pub.messages)

    def test_external_takeover_stops_without_land_or_rearm(self):
        self.flying()
        self.node.vehicle.nav_state=4
        self.node.tick()
        self.assertEqual(self.node.phase,'released')
        self.assertFalse(self.node.manual_pub.messages)
        self.assertFalse(self.node.command_pub.messages)

    def test_stale_telemetry_stops_without_mode_change(self):
        self.flying()
        self.node.status_at=90
        self.node.tick()
        self.assertEqual(self.node.phase,'released')
        self.assertFalse(self.node.command_pub.messages)

    def test_repeated_takeoff_does_not_duplicate_command(self):
        self.node.on_command(Message(data='takeoff'))
        self.node.on_command(Message(data='takeoff'))
        self.assertEqual(len(self.node.command_pub.messages),1)

    def test_landing_timeout_even_when_status_stops(self):
        self.flying()
        self.node.on_command(Message(data='land'))
        self.assertEqual(self.node.command_pub.messages[-1].command,21)
        self.now.return_value=161
        self.node.tick()
        self.assertEqual(self.node.phase,'released')


class OccupancyTests(unittest.TestCase):
    def test_occupied_control_topic_exits_before_creating_publishers(self):
        for occupied in ('/fmu/in/manual_control_input', '/fmu/in/vehicle_command'):
            endpoint = types.SimpleNamespace(node_namespace='/uav/test/teleop', node_name='flight')
            with self.subTest(topic=occupied), patch.dict(os.environ, LEUAV_NAMESPACE='/uav/demo/teleop'), \
                    patch.object(controller.FlightController, 'get_publishers_info_by_topic',
                                 side_effect=lambda name: [endpoint] if name == occupied else [], create=True), \
                    patch.object(controller.FlightController, 'create_publisher') as publish, \
                    patch.object(controller.FlightController, 'destroy_node', create=True) as destroy:
                with self.assertRaisesRegex(RuntimeError, '/uav/test/teleop/flight'):
                    controller.FlightController()
                publish.assert_not_called()
                destroy.assert_called_once()

    def test_discovery_wait_catches_late_publisher_and_uses_versioned_topic(self):
        node = controller.FlightController.__new__(controller.FlightController)
        endpoint = types.SimpleNamespace(node_namespace='/', node_name='other_controller')
        with patch.object(controller.ManualControlSetpoint, 'MESSAGE_VERSION', 1), \
                patch.object(node, 'get_publishers_info_by_topic', side_effect=[[], [], [endpoint], []], create=True) as query, \
                patch.object(controller.time, 'monotonic', side_effect=[100., 100.]), \
                patch.object(controller.rclpy, 'spin_once', create=True) as spin:
            with self.assertRaisesRegex(RuntimeError, '/fmu/in/manual_control_input_v1：/other_controller'):
                node.check_exist()
            spin.assert_called_once()
            self.assertEqual(query.call_args_list[0].args[0], '/fmu/in/manual_control_input_v1')

    def test_empty_topics_allow_start_after_discovery_window(self):
        node = controller.FlightController.__new__(controller.FlightController)
        with patch.object(node, 'get_publishers_info_by_topic', return_value=[], create=True), \
                patch.object(controller.time, 'monotonic', side_effect=[100., 100., 102.]), \
                patch.object(controller.rclpy, 'spin_once', create=True) as spin:
            node.check_exist()
            spin.assert_called_once()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        from leuav.flight.px4 import agent as bridge
        self.bridge = bridge

    def test_start_replaces_process_with_foreground_agent(self):
        with patch.object(self.bridge.shutil, 'which', return_value='/usr/local/bin/MicroXRCEAgent'), \
                patch.object(self.bridge.socket, 'socket'), patch.object(self.bridge.os, 'execv') as start:
            self.bridge.main()
        start.assert_called_once_with('/usr/local/bin/MicroXRCEAgent',
                                      ['/usr/local/bin/MicroXRCEAgent', 'udp4', '-p', '8888'])

    def test_busy_port_does_not_start_agent(self):
        with patch.object(self.bridge.shutil, 'which', return_value='/usr/local/bin/MicroXRCEAgent'), \
                patch.object(self.bridge.socket, 'socket') as factory, patch.object(self.bridge.os, 'execv') as start:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError('busy')
            with self.assertRaisesRegex(RuntimeError, '8888'):
                self.bridge.main()
            start.assert_not_called()
