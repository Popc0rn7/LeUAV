"""遥控命名空间；两端必须显式配置相同值。"""
import os
import re


def namespace():
    value = os.environ.get('LEUAV_NAMESPACE', '')
    if not re.fullmatch(r'/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*', value):
        raise ValueError('请设置绝对 ROS 命名空间 LEUAV_NAMESPACE，例如 /uav/demo/teleop')
    return value
