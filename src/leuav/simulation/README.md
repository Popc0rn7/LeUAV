# 模拟器接入

airsim/sdk.py 和 session.py 提供官方 SDK 兼容调用与本机持久代理；adrl_compat.py 保留固定摘要的旧 ADRL 兼容。ADRL 专属场景逻辑归案例。ProjectAirSim/Gazebo 后续迁入。

实际操作见 cases/adrl 与 cases/keyboard；结果见 docs/Validation.md。
