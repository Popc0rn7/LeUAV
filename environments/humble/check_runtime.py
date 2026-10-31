"""No-network runtime import/CDR probe; does not initialize a ROS node."""
import json
import shutil

import rclpy
from rclpy.serialization import serialize_message, deserialize_message
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from px4_msgs.msg import ManualControlSetpoint, VehicleCommand, VehicleCommandAck, VehicleStatus

messages=(Twist,String,ManualControlSetpoint,VehicleCommand,VehicleCommandAck,VehicleStatus)
for cls in messages:
    msg=cls()
    assert deserialize_message(serialize_message(msg),cls)==msg,cls.__name__
assert VehicleStatus.MESSAGE_VERSION==4
# Build and transport-server duties must not be needed by this runtime.
assert shutil.which('gcc') is None
assert shutil.which('colcon') is None
assert shutil.which('MicroXRCEAgent') is None
print(json.dumps(dict(passed=True,scope='imports/CDR only',messages=[cls.__name__ for cls in messages],vehicle_status_version=4)))
