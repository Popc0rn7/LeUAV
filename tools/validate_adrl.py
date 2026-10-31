#!/usr/bin/env python3
"""SSH GUI preflight and repeatable ADRL static lifecycle verification.

Run outside an agent sandbox only after its normal permission approval.
Does not change system permissions, claim API control, arm, or take off.
"""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

from leuav.adrl.config import load_profile
from leuav.runtime import processes


def desktop_environment(display=None, authority=None):
    env = os.environ.copy()
    if display:
        env['DISPLAY'] = display
    if authority:
        env['XAUTHORITY'] = str(Path(authority).expanduser())
    if not env.get('DISPLAY') or not env.get('XAUTHORITY'):
        candidates = set()
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if proc.stat().st_uid != os.getuid() or proc.joinpath('comm').read_text().strip() not in ('gnome-shell', 'gnome-session-b', 'plasmashell', 'xfce4-session'):
                    continue
                values = dict(part.split(b'=', 1) for part in proc.joinpath('environ').read_bytes().split(b'\0') if b'=' in part)
                found = tuple(values.get(key.encode(), b'').decode() for key in ('DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR'))
                if found[0] and found[1]:
                    if display and found[0] != display:
                        continue
                    candidates.add(found)
            except (OSError, ValueError, UnicodeError):
                continue
        if len(candidates) != 1:
            raise RuntimeError('无法唯一识别同用户桌面；显式传入 --display 和 --xauthority，不猜测 :0、不放宽 X11 权限')
        for key, value in zip(('DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR'), candidates.pop()):
            if value and not env.get(key):
                env[key] = value
    if not Path(env['XAUTHORITY']).is_file():
        raise RuntimeError('Xauthority 不存在或不可读；请提供目标桌面授权文件')
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--display')
    parser.add_argument('--xauthority')
    parser.add_argument('--observe-seconds', type=int, default=15)
    parser.add_argument('stage', choices=['preflight', 'lifecycle'])
    args = parser.parse_args(argv)
    if not 3 <= args.observe_seconds <= 60:
        parser.error('--observe-seconds 须为 3–60')
    config = load_profile(args.profile, args.workspace)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = config['output'] / 'validation' / stamp
    evidence.mkdir(parents=True, exist_ok=False)
    env = None
    report = dict(stage=args.stage, started_at=stamp, result='running', profile=str(args.profile.resolve()),
                  desktop={}, commands=[])
    root = Path(__file__).resolve().parents[1]
    report['sources'] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((root/'src/leuav').rglob('*')) if path.is_file() and path.suffix in ('.py', '.sh', '.json', '.xml')}
    report['environment_sources'] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((root/'environments/flight_board').rglob('*')) if path.is_file()}
    report['validator_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['python'] = sys.version
    if (root/'uv.lock').is_file():
        report['uv_lock_sha256'] = hashlib.sha256((root/'uv.lock').read_bytes()).hexdigest()

    def save():
        (evidence / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')

    def run(label, command, timeout=30):
        result = subprocess.run(list(map(str, command)), env=env, capture_output=True, text=True, timeout=timeout)
        (evidence / (label+'.log')).write_text(result.stdout+result.stderr)
        report['commands'].append(dict(label=label, argv=list(map(str, command)), returncode=result.returncode))
        save()
        if result.returncode:
            raise RuntimeError(f'{label} 失败；见 {evidence / (label+".log")}。若为沙箱/系统权限限制，申请对应权限后重试，不修改系统权限或换工具绕过。')
        return result.stdout

    cli = [sys.executable, '-m', 'leuav.adrl.cli', '--profile', str(args.profile.resolve()), '--workspace', str(args.workspace.resolve())]
    started = False
    try:
        env = desktop_environment(args.display, args.xauthority)
        report['desktop'] = {key: env.get(key) for key in ('DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR')}
        run('x11', ['xdpyinfo', '-display', env['DISPLAY']])
        run('gpu', ['vulkaninfo', '--summary'])
        run('docker-info', ['docker', 'info', '--format', '{{.ServerVersion}}'])
        for key in ('px4_image', 'ros_image'):
            run(key, ['docker', 'image', 'inspect', config[key]])
        run('plan', cli+['plan'])
        if args.stage == 'lifecycle':
            state_path = config['output']/'state.json'
            if state_path.exists() and json.loads(state_path.read_text()).get('phase') != 'stopped':
                raise RuntimeError('已有未停止实例，拒绝接管；先按 ADRL status/down 处理')
            # The CLI cleans resources it creates on startup failure. This tool also
            # performs bounded force recovery if its own up times out or is interrupted.
            started = True
            run('up', cli+['up'], timeout=240)
            state = json.loads(state_path.read_text())
            report['run_id'] = state['owner']
            report['run_dir'] = state['run_dir']
            # Discovery alone is insufficient when Agent and algorithms live in
            # separate containers. Require real, advancing PX4 ROS messages.
            run('dds-link', ['docker', 'exec', state['ros_container'], '/bin/bash', '-c',
                'source /opt/ros/humble/setup.bash && source /opt/px4_ws/install/local_setup.bash && '
                'PYTHONPATH=/leuav-src${PYTHONPATH:+:$PYTHONPATH} exec python3 -m '
                'leuav.flight.px4.check_link --require-disarmed'], timeout=20)
            deadline = time.monotonic()+args.observe_seconds
            index = 0
            while True:
                status = run(f'status-{index}', cli+['status'])
                if '"live_sensor_position_ready": true' not in status or '"agent_running": true' not in status:
                    raise RuntimeError('静止链路未持续 ready')
                vehicle = run(f'vehicle-{index}', ['docker','exec',state['container'],'/opt/px4-gazebo/bin/px4-listener','vehicle_status'])
                landed = run(f'landed-{index}', ['docker','exec',state['container'],'/opt/px4-gazebo/bin/px4-listener','vehicle_land_detected'])
                if 'arming_state: 1' not in vehicle or 'landed: True' not in landed:
                    raise RuntimeError('静止验证未确认 Disarmed 与 landed')
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(3, max(0, deadline-time.monotonic())))
                index += 1
            run('down', cli+['down'])
            started = False
            final = json.loads(state_path.read_text())
            if final.get('phase') != 'stopped' or processes.host_alive(final) or processes.owned_container(final) or processes.owned_ros(final):
                raise RuntimeError('正常关闭后仍有本次资源残留')
        report['result'] = 'passed'
    except BaseException as exc:
        report.update(result='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        if started:
            try:
                run('failure-recovery', cli+['down','--force'])
            except Exception as exc:
                report['recovery_error'] = str(exc)
        save()
        print(f'验证结果 {report["result"]}: {evidence / "report.json"}', flush=True)


if __name__ == '__main__':
    main()
