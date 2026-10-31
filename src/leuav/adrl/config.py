"""Explicit ADRL profile resolution; no course .env or group table dependency."""
from pathlib import Path
import re

import yaml

from leuav.resources import load_resources


def load_profile(path, workspace):
    path = Path(path).expanduser().resolve(strict=True)
    data = yaml.safe_load(path.read_text())
    required = {'case', 'scene_resource', 'px4_image', 'ros_image', 'ros_domain_id', 'namespace', 'containers', 'output'}
    if not isinstance(data, dict) or set(data) != required or data['case'] != 'adrl':
        raise ValueError(f'ADRL profile 需要且只支持字段 {sorted(required)}')
    if type(data['ros_domain_id']) is not int or not 0 <= data['ros_domain_id'] <= 232:
        raise ValueError('ros_domain_id 须为 0–232 整数')
    if not isinstance(data['namespace'], str) or not re.fullmatch(r'/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*', data['namespace']):
        raise ValueError('namespace 须为有效的绝对 ROS 命名空间')
    for key in ('scene_resource', 'px4_image', 'ros_image', 'output'):
        if not isinstance(data[key], str) or not data[key].strip():
            raise ValueError(f'{key} 须为非空字符串')
    containers = data['containers']
    if not isinstance(containers, dict) or set(containers) != {'px4', 'ros'} or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', v) for v in containers.values()) or len(set(containers.values())) != 2:
        raise ValueError('containers 需要两个不同的有效 px4/ros 容器名称')
    resources = load_resources(Path(workspace))
    entry = resources.get(data['scene_resource'])
    if entry is None:
        raise ValueError(f"资源 {data['scene_resource']} 未配置，请在 resources.yaml 或 resources.local.yaml 中绑定 ADRL 原包根目录")
    scene = entry['path']
    for relative in ('Engine', 'ADRL/Content', 'ADRL/Binaries/Linux/ADRL'):
        if not (scene / relative).exists():
            raise ValueError(f'ADRL 资源缺失: {scene / relative}')
    output = Path(data['output']).expanduser()
    if not output.is_absolute():
        output = path.parent / output
    data.update(scene=scene, output=output.resolve(), profile=str(path))
    # Compatibility package must never be assembled inside shared source resources.
    if data['output'] == scene or scene in data['output'].parents or data['output'] in scene.parents:
        raise ValueError('output 与原始场景包不得互相包含')
    return data
