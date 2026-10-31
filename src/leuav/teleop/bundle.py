"""Assemble a content-addressed RoboPi Python runtime; never contacts a device."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil


def bundle(output, domain, namespace, ros_prefix, messages_prefix, python_root):
    if type(domain) is not int or not 0 <= domain <= 232:
        raise ValueError('ROS domain 须为 0–232 整数')
    if not re.fullmatch(r'/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*', namespace):
        raise ValueError('namespace 无效')
    for value in (ros_prefix, messages_prefix, python_root):
        if not value.startswith('/') or '\n' in value:
            raise ValueError('板端依赖路径须为绝对路径')
    source = Path(__file__).parent
    files = {'leuav/__init__.py': b'"""RoboPi teleop runtime."""\n',
             'leuav/teleop/__init__.py': b'"""Teleop control."""\n'}
    for name in ('flight.py', 'protocol.py'):
        ast.parse((source/name).read_text())
        files['leuav/teleop/'+name] = (source/name).read_bytes()
    ros, messages, pyroot = map(shlex.quote, (ros_prefix, messages_prefix, python_root))
    environment = f'''#!/bin/sh
# 显式目标依赖快照；不复制 PC ROS 二进制。
unset LD_PRELOAD
export PATH={pyroot}/bin:{ros}/bin:$PATH
export LD_LIBRARY_PATH={messages}/lib:{ros}/lib:{pyroot}/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}
export PYTHONPATH={messages}/lib/python3.12/site-packages:{ros}/lib/python3.12/site-packages:{pyroot}/lib/python3.12/site-packages:{pyroot}/lib/python3.12${{PYTHONPATH:+:$PYTHONPATH}}
export COLCON_CURRENT_PREFIX={ros}
. {ros}/local_setup.sh || return 1
unset COLCON_CURRENT_PREFIX
export AMENT_PREFIX_PATH={messages}:${{AMENT_PREFIX_PATH:-}}
export ROS_DOMAIN_ID={domain}
export LEUAV_NAMESPACE={shlex.quote(namespace)}
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
'''
    files['ros_env.sh'] = environment.encode()
    files['start.sh'] = b'''#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
. ./ros_env.sh
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m leuav.teleop.flight
'''
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    release = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    directory = Path(output).resolve()/release
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        destination = directory/name
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f'拒绝覆盖未知产物: {destination}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (directory/'manifest.json').write_text(json.dumps(dict(release=release, files=hashes, target_python='3.12', domain=domain, namespace=namespace), indent=2)+'\n')
    (directory/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in hashes.items()))
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--domain', type=int, required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--ros-prefix', required=True)
    parser.add_argument('--messages-prefix', required=True)
    parser.add_argument('--python-root', required=True, help='板端 Python out 根目录，当前模板针对 3.12')
    args = parser.parse_args(argv)
    print(bundle(args.output, args.domain, args.namespace, args.ros_prefix, args.messages_prefix, args.python_root))


if __name__ == '__main__':
    main()
