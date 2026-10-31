"""ADRL AirSim/PX4 lifecycle and native race entry point."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from . import runtime
from .config import load_profile
from .scene import prepare_race, verify_race


class Task:
    prepare = staticmethod(prepare_race)
    verify = staticmethod(verify_race)


def start_race(state, directory):
    if state.get('race', {}).get('phase') != 'prepared':
        raise RuntimeError('本轮不在 prepared 状态；本版重复比赛需落地后 down/up')
    if 'arming_state: 1' not in runtime.process_manager.px4(state, 'listener', 'vehicle_status').stdout:
        raise RuntimeError('开赛前须 Disarmed')
    if not runtime.ready(state, require_preflight=False):
        raise RuntimeError('传感器/定位未就绪')
    # Persist before RPC: an uncertain reply must never cause an automatic replay.
    state['race']['phase'] = 'starting'
    runtime.process_manager.write_state(directory, state)
    if runtime.rpc(state, 'simStartRace', 2) is False:
        raise RuntimeError('原生赛务拒绝开赛；保留 starting 状态供诊断')
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        if runtime.rpc(state, 'simGetDisqualified', 'drone_2'):
            state['race'].update(phase='racing', started_wall_time=time.time())
            runtime.process_manager.write_state(directory, state)
            print('原生 Tier 2 已开赛，未自动解锁；可启动选定控制端')
            return
        time.sleep(.1)
    raise RuntimeError('未确认 Tier 2 开赛状态；不自动重试 RPC')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('action', choices=['plan', 'up', 'status', 'start-race', 'land', 'down', 'stop'])
    parser.add_argument('--force', action='store_true', help='仅用于 down；仿真急停')
    args = parser.parse_args(argv)
    if args.force and args.action != 'down':
        parser.error('--force 仅用于 down')
    # Recovery uses the profile's output location without requiring source weights/resources.
    if args.action in ('plan', 'up'):
        config = load_profile(args.profile, args.workspace)
        directory = config['output']
    else:
        import yaml
        data = yaml.safe_load(args.profile.read_text())
        output = Path(data['output']).expanduser()
        directory = (output if output.is_absolute() else args.profile.resolve().parent / output).resolve()
    if args.action == 'plan':
        print(json.dumps(config, default=str, indent=2, ensure_ascii=False))
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    runtime.STATE_DIR = directory
    with runtime.process_manager.management_lock(directory, args.action, args.force):
        if args.action == 'up':
            previous = directory/'state.json'
            if previous.exists() and json.loads(previous.read_text()).get('phase') != 'stopped':
                raise RuntimeError('此输出目录保留未停止实例；先 status 或 down，避免覆盖恢复入口')
            runtime.PX4_CONTAINER = config['containers']['px4']
            runtime.ROS_CONTAINER = config['containers']['ros']
            options = SimpleNamespace(image=config['px4_image'], ros_image=config['ros_image'], domain=config['ros_domain_id'],
                namespace=config['namespace'], profile=config['profile'], scene=config['scene'],
                settings=Path(__file__).with_name('settings.json'), window_mode=None, display=None)
            runtime.up(options, Task)
            return 0
        path = directory/'state.json'
        if not path.exists():
            if args.action in ('status', 'down', 'stop'):
                print('尚无管理实例')
                return 0
            raise RuntimeError('请先 up')
        state = json.loads(path.read_text())
        if args.action == 'status':
            runtime.status(state)
        elif args.action == 'start-race':
            start_race(state, directory)
        elif args.action == 'land':
            runtime.land(state)
        elif args.action in ('down', 'stop'):
            runtime.shutdown(state, force=args.force or args.action == 'stop')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
