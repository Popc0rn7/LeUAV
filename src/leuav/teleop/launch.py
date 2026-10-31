"""Run complete keyboard/flight nodes in an existing owned Humble container."""
import argparse
import json
from pathlib import Path
import os

from leuav.runtime import processes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True, help='ADRL 输出目录中的 state.json')
    parser.add_argument('role', choices=['keyboard', 'flight'])
    args = parser.parse_args(argv)
    state = json.loads(args.state.read_text())
    info = processes.owned_ros(state)
    if state.get('phase') != 'ready' or not info or not info['State']['Running']:
        raise RuntimeError('ADRL 实例及 Humble 算力容器须 ready')
    if state.get('race', {}).get('phase') != 'racing':
        raise RuntimeError('请先 start-race；控制程序不自动开赛')
    config = state['config']
    module = 'leuav.teleop.'+args.role
    command = ['docker', 'exec', '-it' if args.role == 'keyboard' else '-i',
               '--env', f"ROS_DOMAIN_ID={config['ros_domain_id']}",
               '--env', f"LEUAV_NAMESPACE={config['namespace']}",
               info['Id'], '/bin/bash', '-c',
               'source /opt/ros/humble/setup.bash && source /opt/px4_ws/install/local_setup.bash && PYTHONPATH=/leuav-src${PYTHONPATH:+:$PYTHONPATH} exec python3 -m '+module]
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
