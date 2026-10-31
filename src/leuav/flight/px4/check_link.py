"""Read-only PX4 ROS message probe; never publishes control commands."""
import argparse
import json
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from px4_msgs.msg import VehicleStatus


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-disarmed',action='store_true')
    args=parser.parse_args()
    rclpy.init();node=Node('flight_board_link_check');messages=[]
    version=getattr(VehicleStatus,'MESSAGE_VERSION',0)
    topic='/fmu/out/vehicle_status'+(f'_v{version}' if version else '')
    subscription=node.create_subscription(VehicleStatus,topic,
        lambda msg:messages.append(dict(timestamp=msg.timestamp,arming_state=msg.arming_state,nav_state=msg.nav_state)),qos_profile_sensor_data)
    try:
        deadline=time.monotonic()+10
        while len(messages)<3 and time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.1)
        passed=len(messages)>=3 and messages[-1]['timestamp']>messages[0]['timestamp']
        if args.require_disarmed:
            passed=passed and all(msg['arming_state']==1 for msg in messages)
        print(json.dumps(dict(passed=passed,topic=topic,messages=messages)),flush=True)
        return 0 if passed else 1
    finally:
        node.destroy_node();rclpy.shutdown()


if __name__=='__main__':
    raise SystemExit(main())
