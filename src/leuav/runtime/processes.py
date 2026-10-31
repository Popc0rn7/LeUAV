"""Linux host process identity, port checks and owned-resource cleanup."""
from contextlib import contextmanager, ExitStack
import errno
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

LABEL = "io.leuav.airsim.owner"
AIRSIM_INPUT_ARGS = ['-ini:Input:[/Script/Engine.InputSettings]:bCaptureMouseOnLaunch=False,DefaultViewportMouseCaptureMode=NoCapture,bDefaultViewportMouseLock=False,DefaultViewportMouseLockMode=DoNotLock', '-NoMouseCapture']

def command(*args, check=True, timeout=15):
    return subprocess.run(list(map(str, args)), capture_output=True, text=True,
                          check=check, timeout=timeout)


def inspect_container(name):
    result = command("docker", "inspect", name, check=False)
    if result.returncode == 0:
        return json.loads(result.stdout)[0]
    if "no such object" in result.stderr.lower() or "no such container" in result.stderr.lower():
        return None
    raise RuntimeError(result.stderr.strip() or "无法查询 Docker 容器")


def start_ticks(pid):
    data = Path(f"/proc/{pid}/stat").read_text()
    tail = data[data.rfind(")") + 2:].split()
    if tail[0] == "Z":
        raise ProcessLookupError(pid)
    return tail[19]


def host_alive(state):
    try:
        pid = state["pid"]
        return (start_ticks(pid) == state["start_ticks"]
                and Path(f"/proc/{pid}/exe").resolve() == Path(state["binary"]).resolve()
                and f"-settings={state['runtime_settings']}".encode()
                in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0"))
    except (OSError, KeyError, ProcessLookupError):
        return False


def owned_container(state):
    info = inspect_container(state["container"])
    if info and ((state.get("container_id") and info["Id"] != state["container_id"])
                 or (info["Config"].get("Labels") or {}).get(LABEL) != state["owner"]):
        raise RuntimeError("同名容器不属于本次运行，拒绝操作")
    return info


def write_state(directory, state):
    temporary = directory / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    temporary.replace(directory / "state.json")


@contextmanager
def management_lock(directory, action, force=False):
    """任务互斥；只读状态/急救请求不被整轮任务及复盘阻塞。"""
    if action=='dashboard':
        yield
        return
    recovery = action in ('land', 'stop', 'reset') or (action == 'down' and force)
    with ExitStack() as stack:
        if recovery:
            recovery_lock = stack.enter_context((directory/'recovery.lock').open('a'))
            try:
                fcntl.flock(recovery_lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('另一个恢复命令正在执行；可用 status 查看状态') from exc
        lock = stack.enter_context((directory/'runtime.lock').open('a'))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            holder = lock_holder(directory/'runtime.lock')
            who = f'（持有者：{holder}）' if holder else ''
            if not (recovery or action in ('status','task-status')):
                raise RuntimeError(f'任务/管理命令正在执行{who}；仍可 status、land 或 down --force（仿真急停）；卡在 up 时先中断该进程') from exc
            if recovery:
                state_file = directory/'state.json'
                state = json.loads(state_file.read_text()) if state_file.exists() else {}
                if state.get('phase') not in ('ready', 'stopping', 'stopped'):
                    raise RuntimeError(f'实例正在初始化{who}，先中断 up 进程，再 down --force；不与创建资源并行操作') from exc
        yield


def lock_holder(path):
    """仅用于诊断：找出打开该锁文件的进程及其命令行。"""
    target = str(Path(path))
    try:
        resolved = str(Path(path).resolve())
    except OSError:
        resolved = target
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            handles = list((proc/'fd').iterdir())
        except OSError:
            continue
        for handle in handles:
            try:
                opened = os.readlink(handle)
            except OSError:
                continue
            if opened not in (target, resolved):
                continue
            try:
                command = (proc/'cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace').strip()
            except OSError:
                command = ''
            return f'{proc.name} {command}'.strip()
    return None


def listen_owned(pid, port):
    """只查监听，不连接 4560，避免消耗 AirSim 的单次 accept。"""
    inodes = set()
    try:
        for fd in Path(f"/proc/{pid}/fd").iterdir():
            try:
                link = os.readlink(fd)
                if link.startswith("socket:["):
                    inodes.add(link[8:-1])
            except OSError:
                pass
        for row in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = row.split()
            if int(fields[1].split(":")[1], 16) == port and fields[3] == "0A" and fields[9] in inodes:
                return True
    except OSError:
        pass
    return False


def tcp_states(port):
    """读取本网络命名空间的 TCP 状态，不建立探测连接。"""
    states = []
    for name in ("tcp", "tcp6"):
        for row in Path(f"/proc/net/{name}").read_text().splitlines()[1:]:
            fields = row.split()
            if int(fields[1].split(":")[1], 16) == port:
                states.append(fields[3])
    return states


def check_port(kind, port, time_wait_timeout_s=75):
    deadline = time.monotonic() + time_wait_timeout_s
    announced = False
    protocol = "TCP" if kind == socket.SOCK_STREAM else "UDP"
    while True:
        with socket.socket(socket.AF_INET, kind) as sock:
            try:
                if kind == socket.SOCK_STREAM:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                if kind == socket.SOCK_STREAM:
                    sock.listen(1)
                return
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise RuntimeError(f"无法检查 {protocol} 端口 {port}：{exc}") from exc
                states = tcp_states(port) if kind == socket.SOCK_STREAM else []
                if not states or any(state != "06" for state in states):
                    raise RuntimeError(f"{protocol} 端口 {port} 已占用；先确认现有实例用途") from exc
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"TCP 端口 {port} 的 TIME_WAIT 尚未释放，等待超时；稍后重试") from exc
                if not announced:
                    print(f"TCP {port} 仅有 TIME_WAIT 残留，自动等待释放（最多 {time_wait_timeout_s} 秒）…", flush=True)
                    announced = True
        time.sleep(.5)


def check_ports():
    for kind, ports in [(socket.SOCK_STREAM, [4560, 41451]),
                        (socket.SOCK_DGRAM, [14540, 14580, 18570, 14280, 13030])]:
        for port in ports:
            check_port(kind, port)


def owned_ros(state):
    if not state.get('ros_container'):
        return None
    info = inspect_container(state['ros_container'])
    if info and ((state.get('ros_container_id') and info['Id'] != state['ros_container_id'])
                 or (info['Config'].get('Labels') or {}).get(LABEL) != state['owner']):
        raise RuntimeError('算法容器不属于本次运行，拒绝操作')
    return info


def px4(state, module, *args):
    info = owned_container(state)
    if not info or not info["State"]["Running"]:
        raise RuntimeError("本实例 PX4 未运行")
    return command("docker", "exec", state["container"],
                   f"/opt/px4-gazebo/bin/px4-{module}", *args, check=False, timeout=6)


def stop_host(state):
    if not host_alive(state):
        return
    os.killpg(state["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 5
    while host_alive(state) and time.monotonic() < deadline:
        time.sleep(.2)
    if host_alive(state):
        os.killpg(state["pid"], signal.SIGKILL)


def shutdown(state, directory, force=False, *, stop_workload=None):
    info = owned_container(state)
    ros = owned_ros(state)
    if info and info["State"]["Running"] and not force:
        if "arming_state: 1" not in px4(state, "listener", "vehicle_status").stdout:
            raise RuntimeError("未确认 PX4 已解除解锁；正常降落用 land，碰撞/卡住用 down --force；保留日志")
    elif host_alive(state) and not force:
        if state.get("config",{}).get("rpc_in_computer"):
            raise RuntimeError("PX4 unavailable: cannot confirm disarmed; use down --force for recovery")
        raise RuntimeError('PX4 不可用，无法确认 Disarmed；检查现场后使用 down --force 回收仿真')
    state['phase'] = 'stopping'
    write_state(directory, state)
    errors = []
    def attempt(operation):
        try:
            operation()
        except Exception as exc:
            if not force:
                raise
            errors.append(str(exc))
    def remove_container(info, logfile):
        identity = info['Id']
        if info['State']['Running']:
            attempt(lambda: command('docker', 'stop', '-t', '5', identity, timeout=12))
        def save_console():
            result = command('docker', 'logs', identity, check=False)
            (Path(state['run_dir'])/logfile).write_text(result.stdout+result.stderr)
        attempt(save_console)
        # 急停允许强制移除已核实身份的容器；日志保存失败不能阻断其他资源回收。
        attempt(lambda: command('docker', 'rm', *(['-f'] if force else []), identity))
    workload_unknown = False
    if state.get('rviz_container'):
        view = inspect_container(state['rviz_container'])
        if view:
            if view['Id'] != state.get('rviz_container_id') or view['Config'].get('Labels', {}).get(LABEL) != state['owner']:
                raise RuntimeError('RViz 容器身份变化，拒绝回收')
            remove_container(view, 'rviz-console.log')
    if stop_workload:
        try:
            stop_workload(state)
        except Exception as exc:
            workload_unknown = True
            errors.append('附属节点回收未确认：'+str(exc))
    if ros:
        remove_container(ros,'ros-console.log')
    # 先停止场景，让仍连接的仿真循环处理正常退出，避免断连后 lockstep 卡住。
    attempt(lambda: stop_host(state))
    if info:
        remove_container(info,'px4-console.log')
    remaining = bool(workload_unknown or host_alive(state) or owned_container(state) or owned_ros(state))
    state["phase"] = "stopping" if remaining else "stopped"
    write_state(directory, state)
    if errors or remaining:
        raise RuntimeError('资源回收状态：'+state['phase']+'；'+ '; '.join(errors))
