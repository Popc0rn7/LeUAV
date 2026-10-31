#!/usr/bin/env python3
"""PC：AirSim 场景与 PX4 runtime manager：生命周期、状态、实例身份和故障回收；任务由调用方传入。"""
import json
import os
import signal
import socket
from pathlib import Path
import subprocess
import sys
import time
import traceback
import uuid

from types import SimpleNamespace
from leuav.runtime import processes as process_manager
from leuav.simulation.airsim.adrl_compat import prepare
from leuav.simulation.airsim.session import rpc
from .scene import load_settings, maximize_window

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent

def ready(state, require_preflight=True):
    try:
        return check_ready(state, require_preflight)
    except subprocess.TimeoutExpired:
        # 切图会暂时停止 HIL；单次 listener 超时只表示尚未就绪。
        # up/load_level 的总 deadline 仍负责判定持续停流失败。
        return False


def check_ready(state, require_preflight=True):
    if not process_manager.host_alive(state):
        return False
    info = process_manager.owned_container(state)
    if not info or not info['State']['Running']:
        return False
    sensors = process_manager.px4(state, 'listener', 'sensor_combined', '-n', '2')
    import re
    stamps = re.findall(r'^    timestamp: (\d+)', sensors.stdout, re.M)
    if sensors.returncode or len(stamps) != 2 or int(stamps[1]) <= int(stamps[0]):
        return False
    position = process_manager.px4(state, 'listener', 'vehicle_local_position').stdout
    if not all(x in position for x in ('xy_valid: True', 'z_valid: True')):
        return False
    if require_preflight and 'Preflight check: OK' not in process_manager.px4(state, 'commander', 'check').stdout:
        return False
    try:
        return bool(rpc(state, 'ping')) and 'kinematics_estimated' in rpc(state, 'getMultirotorState', 'PX4')
    except (OSError, RuntimeError):
        return False


def stop_session(state):
    pid = state.get('rpc_pid')
    if pid is None:
        return
    try:
        if process_manager.start_ticks(pid) != state['rpc_start_ticks']:
            return
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if b'leuav.simulation.airsim.session' not in argv or str(Path(state['run_dir'])/'rpc.sock').encode() not in argv:
            raise RuntimeError('RPC 代理进程身份不匹配，拒绝停止')
        os.killpg(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        pass


def shutdown(state, force=False):
    STATE_DIR = Path(state["run_dir"]).parent
    try:
        process_manager.shutdown(state, STATE_DIR, force=force)
    finally:
        # 先停场景，后关闭持久 RPC；避免旧 rpclib 会话 teardown 崩溃。
        if not process_manager.host_alive(state):
            stop_session(state)


def reset(state, args, task):
    task.reset_race(state, args)


def check_conflicts(containers):
    """只检查本课程的固定容器及实际端口，不用旧 state 判断存活。"""
    for name in containers:
        info = process_manager.inspect_container(name)
        if info:
            if info['State']['Running']:
                raise RuntimeError(f'容器 {name} 正在运行；请先查看 run.py status，结束原实例后再 up')
            raise RuntimeError(f'容器 {name} 已停止但仍占用名称；请先清理该容器再 up')
    process_manager.check_port(socket.SOCK_DGRAM, 8888)
    try:
        # 共用已验证的绑定检查；仅 TIME_WAIT 时有限等待，不判为活实例。
        process_manager.check_ports()
    except RuntimeError as exc:
        if '已占用' not in str(exc):
            raise
        try:
            result = process_manager.command(
                'ss', '-lntup', '( sport = :4560 or sport = :41451 or sport = :14540 or sport = :14580 or sport = :18570 or sport = :14280 or sport = :13030 )',
                check=False)
            details = result.stdout.strip() if result.returncode == 0 else ''
        except OSError:
            details = ''
        raise RuntimeError(str(exc)+(f'\n占用端口（进程信息取决于当前用户权限）：\n{details}' if details else '')) from exc


def start_computer(state):
    STATE_DIR = Path(state["run_dir"]).parent
    ROS_CONTAINER = state["config"]["ros_container"]
    # 算力运行容器；Agent 归 flight_board，此处不启动控制节点。
    state.update(ros_container=ROS_CONTAINER, ros_container_id=None)
    process_manager.write_state(STATE_DIR, state)
    result = process_manager.command('docker', 'run', '--pull', 'never', '-d', '--init',
        '--name', ROS_CONTAINER, '--network', 'host',
        '--label', f"{process_manager.LABEL}={state['owner']}",
        '--env', f"ROS_DOMAIN_ID={state['config']['ros_domain_id']}",
        '--env', 'ROS_LOCALHOST_ONLY=0', '--env', 'RMW_IMPLEMENTATION=rmw_fastrtps_cpp',
        '--env', 'FASTRTPS_DEFAULT_PROFILES_FILE=/leuav-src/leuav/contracts/fastdds_udp.xml',
        '--mount', f'type=bind,source={PACKAGE},target=/leuav-src/leuav,readonly',
        '--entrypoint', '/bin/bash', state['config']['ros_image'], '-c',
        'exec sleep infinity', timeout=30)
    state['ros_container_id'] = result.stdout.strip()
    process_manager.write_state(STATE_DIR, state)


def computer_running(state):
    info = process_manager.owned_ros(state)
    return bool(info and info['State']['Running'])


def agent_running(state):
    # Read historical states without relabelling their old topology.
    if state.get('config', {}).get('agent_location') != 'flight_board':
        return computer_running(state)
    info = process_manager.owned_container(state)
    if not info or not info['State']['Running']:
        return False
    result = process_manager.command('docker', 'exec', info['Id'], 'python3',
        '/opt/flight-board/supervisor.py', 'status', check=False)
    if result.returncode:
        return False
    try:
        return json.loads(result.stdout).get('agent_running') is True
    except ValueError:
        return False


def up(args, task, *, context=None):
    # 可由后续阶段复用场景生命周期，默认行为与 Stage 1 保持一致。
    context = context or sys.modules[__name__]
    settings = load_settings(args.settings)
    window = settings.get('Window', {})
    args.window_mode = args.window_mode or window.get('Mode', 'windowed')
    width, height = window.get('Width', 1280), window.get('Height', 720)
    if args.window_mode not in ('windowed', 'maximized') or any(
            type(value) is not int or not 320 <= value <= 16384 for value in (width, height)):
        raise ValueError('Window 需要有效的 Mode 和 320–16384 的整数 Width/Height')
    image = process_manager.command('docker', 'image', 'inspect', args.image)
    flight_image = json.loads(image.stdout)[0]
    if (flight_image.get('Config', {}).get('Labels') or {}).get('io.leuav.flight-board.version') != '1':
        raise ValueError('px4_image 必须绑定带 Agent/supervisor 的 flight_board 镜像；先按 environments/flight_board/README.md 构建')
    args.image = flight_image['Id']
    ros_image = json.loads(process_manager.command('docker', 'image', 'inspect', args.ros_image).stdout)[0]['Id']
    domain = args.domain
    context.check_conflicts((context.PX4_CONTAINER, context.ROS_CONTAINER))
    if not os.environ.get('DISPLAY'):
        raise RuntimeError('需要 PC 图形会话及 DISPLAY；未启动任何资源')
    package = context.STATE_DIR/'package-online-sitl-ground-reset-300s-v2'
    executable = prepare(args.scene, package, disable_lockstep=True, online_race=True)
    owner = uuid.uuid4().hex
    run_dir = context.STATE_DIR/owner
    run_dir.mkdir()
    (run_dir/'px4-logs').mkdir()
    settings_path = run_dir/'settings.json'
    settings_path.write_text(json.dumps(settings, indent=2)+'\n')
    # ADRL 旧包从可执行文件旁读取设置，避免修改用户 Documents/AirSim。
    sidecar = executable.parent/'settings.json'
    if sidecar.is_symlink() and not sidecar.resolve().is_relative_to(context.STATE_DIR):
        raise RuntimeError(f'拒绝覆盖未知设置链接：{sidecar}')
    if sidecar.exists() and not sidecar.is_symlink():
        raise RuntimeError(f'拒绝覆盖未知设置：{sidecar}')
    sidecar.unlink(missing_ok=True)
    sidecar.symlink_to(settings_path)
    state = dict(owner=owner, fingerprint=owner, phase='starting', run_dir=str(run_dir),
                 container=context.PX4_CONTAINER, container_id=None,
                 binary=str(executable), runtime_settings=str(settings_path),
                 config=dict(image=args.image, agent_location='flight_board', ros_image=ros_image, ros_domain_id=domain, settings_input=str(args.settings.resolve()),
                             ros_container=context.ROS_CONTAINER,
                             namespace=args.namespace, profile=args.profile,
                             timing='native_wall_ms_v1', native_race_limit_ms=300_000,
                             scene_input=str(args.scene.resolve()) if args.scene is not None else None,
                             level=settings.get('Default Environment', ''),
                             view_mode=settings.get('ViewMode', ''), window_mode=args.window_mode))
    if hasattr(context, 'configure'):
        context.configure(state)
    env = os.environ.copy()
    if args.display:
        env['DISPLAY'] = args.display
    if not env.get('DISPLAY'):
        raise RuntimeError('需要在 PC 图形会话中启动，检查 DISPLAY 环境变量')
    with (run_dir/'airsim-console.log').open('w') as log:
        process = subprocess.Popen([str(executable), 'ADRL', '-windowed', f'-ResX={width}', f'-ResY={height}',
                                    '-nosound', '-vulkan', *process_manager.AIRSIM_INPUT_ARGS,
                                    f'-settings={settings_path}'],
                                   cwd=package, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    state.update(pid=process.pid, start_ticks=process_manager.start_ticks(process.pid))
    process_manager.write_state(context.STATE_DIR, state)
    try:
        with (run_dir/'rpc-session.log').open('w') as log:
            proxy = subprocess.Popen([sys.executable, '-m', 'leuav.simulation.airsim.session', 'serve', str(run_dir/'rpc.sock')],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        state.update(rpc_pid=proxy.pid, rpc_start_ticks=process_manager.start_ticks(proxy.pid))
        process_manager.write_state(context.STATE_DIR, state)
        deadline = time.monotonic()+180
        print(f'AirSim PID={process.pid}，等待场景 TCP 4560；日志 {run_dir}', flush=True)
        while not process_manager.listen_owned(process.pid, 4560):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('场景没有监听 4560；查看 airsim-console.log')
            time.sleep(.3)
        if args.window_mode == 'maximized':
            state['window'] = maximize_window(process.pid, env.get('DISPLAY'))
            process_manager.write_state(context.STATE_DIR, state)
            print(f"窗口已最大化（非全屏）：{state['window']['width']}×{state['window']['height']}", flush=True)
        start_pose = task.prepare(context, state, settings, deadline)
        context.start_computer(state)
        result = process_manager.command('docker', 'run', '-d', '--init', '--name', state['container'],
            '--network', 'host', '--label', f'{process_manager.LABEL}={owner}',
            # PX4 原生 rcS 用 ROS_DOMAIN_ID 设置 UXRCE_DDS_DOM_ID；未传时强制归零。
            '--env', f'ROS_DOMAIN_ID={domain}',
            '--mount', f'type=bind,source={run_dir}/px4-logs,target=/flight-logs',
            '--mount', f'type=bind,source={run_dir}/px4-logs,target=/root/.local/share/px4/rootfs/fs/log',
            args.image, timeout=30)
        state['container_id'] = result.stdout.strip()
        process_manager.write_state(context.STATE_DIR, state)
        print('PX4 已启动，等待传感器、定位与 RPC…', flush=True)
        while not ready(state, require_preflight=False):
            if not process_manager.host_alive(state) or time.monotonic() > deadline:
                raise RuntimeError('PX4/场景未就绪；查看本轮日志')
            time.sleep(1)
        if not agent_running(state):
            raise RuntimeError('flight_board DDS Agent 未运行；查看 px4-logs/agent-console.log')
        task.verify(context, state, settings, start_pose, deadline)
        health = process_manager.px4(state, 'commander', 'check').stdout
        state['startup_preflight'] = dict(ok='Preflight check: OK' in health, output=health)
        state['phase'] = 'ready'
        process_manager.write_state(context.STATE_DIR, state)
        print('AirSim/PX4 已就绪；任务初始化完成，未自动解锁。')
        if not state['startup_preflight']['ok']:
            print('PX4 preflight 尚未通过：保留场景供 诊断/等待定位收敛；不代表允许解锁。请检查飞控日志。')
    except BaseException as exc:
        failure = dict(error_type=type(exc).__name__, error=str(exc),
                       host_returncode=process.poll(), traceback=traceback.format_exc())
        (run_dir/'startup-error.json').write_text(json.dumps(failure, indent=2)+'\n')
        state['startup_error'] = failure
        process_manager.write_state(context.STATE_DIR, state)
        print(f'启动失败：{type(exc).__name__}: {exc}；回收本轮资源。诊断：{run_dir}/startup-error.json',
              file=sys.stderr, flush=True)
        context.shutdown(state, force=True)
        raise




def _read_optional(state, name):
    path = Path(state['run_dir'])/name
    return json.loads(path.read_text()) if path.exists() else None


def status(state):
    info = process_manager.owned_container(state)
    running = bool(info and info['State']['Running'])
    print(json.dumps(dict(phase=state['phase'], airsim_alive=process_manager.host_alive(state),
        px4_running=running, agent_running=agent_running(state), computer_running=computer_running(state), run_dir=state['run_dir'],
        live_sensor_position_ready=ready(state, require_preflight=False) if running else False,
        startup=state['config'], window=state.get('window'), level_loaded=state.get('level_loaded'),
        startup_preflight=state.get('startup_preflight'), startup_error=state.get('startup_error'),
        race_reset=state.get('race_reset'), race=state.get('race'),
        native_race_only=True,
        auto_abandon=_read_optional(state, 'auto-abandon.json'),
        recovery=_read_optional(state, 'recovery.json')), indent=2, ensure_ascii=False))
    if running:
        print(process_manager.px4(state, 'commander', 'status').stdout)
        print(process_manager.px4(state, 'commander', 'check').stdout)


def land(state):
    (Path(state['run_dir'])/'land.request').touch()
    process_manager.owned_container(state)
    result = process_manager.px4(state, 'commander', 'mode', 'auto:land')
    if result.returncode:
        raise RuntimeError(result.stdout+result.stderr)
    print(result.stdout)
    print('已请求降落；通过 status 确认解除解锁')
