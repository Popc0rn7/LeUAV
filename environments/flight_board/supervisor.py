#!/usr/bin/env python3
"""Own the PX4/backend process and XRCE Agent as one flight_board instance."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

STATE = Path('/run/flight-board/state.json')


def ticks(pid):
    data = Path(f'/proc/{pid}/stat').read_text()
    fields = data[data.rfind(')')+2:].split()
    if fields[0] == 'Z':
        raise ProcessLookupError(pid)
    return fields[19]


def alive(record):
    try:
        return ticks(record['pid']) == record['ticks']
    except (OSError, KeyError, ProcessLookupError):
        return False


def udp_bound(record, port=8888):
    if not alive(record):
        return False
    try:
        inodes = set()
        for fd in Path(f"/proc/{record['pid']}/fd").iterdir():
            try:
                link = os.readlink(fd)
                if link.startswith('socket:['):
                    inodes.add(link[8:-1])
            except OSError:
                pass
        for name in ('udp', 'udp6'):
            for row in Path('/proc/net/'+name).read_text().splitlines()[1:]:
                fields = row.split()
                if int(fields[1].split(':')[1], 16) == port and fields[9] in inodes:
                    return True
    except OSError:
        pass
    return False


def status(path=STATE):
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return dict(phase='absent', px4_running=False, agent_running=False, healthy=False)
    px4 = alive(state.get('px4', {}))
    agent = udp_bound(state.get('agent', {}))
    return dict(phase=state['phase'], px4_running=px4, agent_running=agent,
                healthy=state['phase']=='running' and px4 and agent)


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2)+'\n')
    temporary.replace(path)


def terminate(process):
    # Children each own a process group; no global kill or port-based cleanup.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)


def run(command, *, agent_command=None, path=STATE, log_dir=Path('/flight-logs')):
    if not command:
        raise ValueError('需要显式 PX4/backend 启动命令')
    if path.exists() and status(path)['healthy']:
        raise RuntimeError('已有健康 flight_board，拒绝重复启动')
    log_dir.mkdir(parents=True, exist_ok=True)
    stop = False
    handlers = {}
    def interrupted(signum, frame):
        nonlocal stop
        stop = True
    for sig in (signal.SIGINT, signal.SIGTERM):
        handlers[sig] = signal.signal(sig, interrupted)
    children = []
    state = dict(phase='starting')
    save(path, state)
    result = 0
    try:
        with (log_dir/'agent-console.log').open('a') as log:
            env = os.environ.copy()
            env['LD_LIBRARY_PATH'] = '/opt/flight-board/lib'
            env['FASTRTPS_DEFAULT_PROFILES_FILE'] = '/opt/flight-board/fastdds.xml'
            agent = subprocess.Popen(agent_command or ['/opt/flight-board/bin/MicroXRCEAgent','udp4','-p','8888'],
                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            children.append(agent)
            state['agent'] = dict(pid=agent.pid, ticks=ticks(agent.pid))
            px4 = subprocess.Popen(command, start_new_session=True)
            children.append(px4)
            state.update(px4=dict(pid=px4.pid, ticks=ticks(px4.pid)), phase='running')
            save(path, state)
            while not stop:
                if any(child.poll() is not None for child in children):
                    state['error'] = '关键进程退出：'+str([child.poll() for child in children])
                    print(state['error'], file=sys.stderr, flush=True)
                    result = 1
                    break
                time.sleep(.1)
    finally:
        for child in reversed(children):
            terminate(child)
        state['phase'] = 'stopped'
        save(path, state)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','status','healthcheck'])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'run':
        return run(args.command)
    report = status()
    if args.action == 'status':
        print(json.dumps(report))
        return 0
    return 0 if report['healthy'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
