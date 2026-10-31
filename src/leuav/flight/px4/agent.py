#!/usr/bin/env python3
"""PC ROS 容器：显式启动 PX4 uXRCE-DDS ↔ ROS 2 的 Agent。"""
import os
import shutil
import socket


def main():
    # Agent 留在 PC，与 PX4 的 UDP 8888 连接；flight.py 可以运行在 RoboPi。
    # 它转换通信协议，flight.py 则转换课程操纵消息与 PX4 消息。
    agent = shutil.which('MicroXRCEAgent')
    if not agent:
        raise RuntimeError('请在课程 ROS 容器中运行，未找到 MicroXRCEAgent')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.bind(('0.0.0.0', 8888))
        except OSError as exc:
            raise RuntimeError('UDP 8888 已占用，请检查是否已启动 bridge；不接管已有进程') from exc
    print('启动 PX4 DDS bridge：MicroXRCEAgent udp4 -p 8888；Ctrl+C 退出', flush=True)
    # exec 替换当前进程，Agent 在前台运行，没有隐藏的后台子进程。
    os.execv(agent, [agent, 'udp4', '-p', '8888'])


if __name__ == '__main__':
    main()
