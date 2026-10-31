"""Regression for the ROS environment bug discovered in the real container."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from leuav.teleop import launch


class LaunchTests(unittest.TestCase):
    def test_preserves_ros_pythonpath_and_uses_owned_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            path.write_text(json.dumps(dict(phase='ready',race=dict(phase='racing'),config=dict(ros_domain_id=23,namespace='/uav/test/teleop'))))
            with patch.object(launch.processes,'owned_ros',return_value=dict(Id='owned-id',State=dict(Running=True))), patch.object(launch.os,'execvp') as execute:
                launch.main(['--state',str(path),'flight'])
            argv=execute.call_args.args[1]
            self.assertIn('owned-id',argv)
            self.assertIn('PYTHONPATH=/leuav-src${PYTHONPATH:+:$PYTHONPATH}',argv[-1])
            self.assertIn('source /opt/px4_ws/install/local_setup.bash',argv[-1])

    def test_never_starts_control_before_native_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            path.write_text(json.dumps(dict(phase='ready',race=dict(phase='prepared'))))
            with patch.object(launch.processes,'owned_ros',return_value=dict(Id='owned-id',State=dict(Running=True))), patch.object(launch.os,'execvp') as execute:
                with self.assertRaises(RuntimeError):launch.main(['--state',str(path),'flight'])
                execute.assert_not_called()
