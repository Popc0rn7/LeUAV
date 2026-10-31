#!/usr/bin/env python3
"""PC：官方 AirSim SDK 的单持久会话代理；Unix socket 仅用于本机管理。"""
import argparse
import json
from pathlib import Path
import socket

import sys



class Connection:
    """管理代理保持 SDK 会话，复用官方客户端及其数据类型。"""
    def __init__(self):
        from leuav.simulation.airsim.sdk import Session
        self.client = Session(timeout=10)

    def call(self, method, args):
        return self.client.call(method, *args)

    def close(self):
        self.client.close()


def rpc(state, method, *args):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(12)
        client.connect(str(Path(state['run_dir'])/'rpc.sock'))
        client.sendall((json.dumps([method, args])+'\n').encode())
        with client.makefile('rb') as stream:
            raw = stream.readline(4*1024*1024)
        response = json.loads(raw)
        if 'error' in response:
            raise RuntimeError(response['error'])
        return response['result']


def serve(path):
    backend = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(4)
        while True:
            client, _ = server.accept()
            with client:
                client.settimeout(12)
                try:
                    with client.makefile('rb') as stream:
                        method, args = json.loads(stream.readline(65536))
                    if backend is None:
                        backend = Connection()
                    result = backend.call(method, args)
                    response = {'result': result}
                except Exception as exc:
                    response = {'error': f'{type(exc).__name__}: {exc}'}
                try:
                    client.sendall((json.dumps(response)+'\n').encode())
                except OSError:
                    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve'])
    parser.add_argument('socket', type=Path)
    args = parser.parse_args()
    serve(args.socket)
