# Keyboard 遥控

启动位置总表见 [ADRL 进程部署](../adrl/README.md#进程部署)。PC keyboard 始终在 uav-computer 运行，flight 在同容器或 RoboPi 二选一；不需要日常启动 builder。

完整键盘输入和 flight 控制节点位于 `src/leuav/teleop/`。从课程骨架及参考实现组合迁入，已补齐映射和消息收发；无 TODO 或教学答案依赖。来源见 [ADRL 来源清单](../adrl/ORIGIN.json)。

```text
PC keyboard → ROS 2/DDS → flight（PC 或 RoboPi）
                              ↓ PX4 ROS 消息
                       flight_board：MicroXRCEAgent ↔ PX4 ↔ ADRL
```

四轴是前/左/上/左转归一化操纵量，不是 m/s；PX4 使用 Position 模式。W/S、A/D、上下箭头、左右箭头分别控制四轴，空格回中，L 请求起飞，K 请求降落，Q/Ctrl+C 回中并请求降落后退出。20 Hz 输入、按键 0.2 s 过期；飞行状态机、ACK、占用检查与失流语义保留。输入失流停止转发，仍由 PX4 原有手动失流策略处理，不额外添加自动 Land 策略。

新三镜像布局 PC 控制链已通过一次真实键盘起飞、Position 悬停、短 W 前向输入、空格回中与 K 降落。其余方向、失流、完整比赛与 RoboPi 路径仍未验收。PC 与 RoboPi 二选一运行 flight；不要同时运行多个输入控制端。启动占用检查不能替代网络隔离或控制权仲裁。

## PC 控制节点

先按 [ADRL 入口](../adrl/README.md) 完成 up、status、start-race。以下在 LeUAV 根目录、两个 PC 终端分别前台运行；state 路径须对应本次 profile 的 output：

```sh
# 终端 A：uav-computer 角色容器中的 flight。
uv run python -m leuav.teleop.launch --state artifacts/adrl/state.json flight
# 终端 B：同一容器中的键盘，须使用本机交互终端。
uv run python -m leuav.teleop.launch --state artifacts/adrl/state.json keyboard
```

launch 检查本次 ROS 容器身份及已开赛状态，使用启动快照中的 domain 与命名空间。不接管同名外部容器，不创建 Agent；Agent 仅在 flight_board 中运行。

## RoboPi 控制节点

使用同一 flight 源码。当前运行包模板针对已预装的 OpenHarmony Humble、Python 3.12 与 Fast DDS；实际前缀、PX4 消息版本、网卡、地址和 DDS 配置须核实。HDC 只传文件，不能替代跨机 DDS。

在 PC 离线生成内容寻址的运行包，显式填写实际前缀、与本轮 profile 相同的 domain/namespace：

```sh
uv run python -m leuav.teleop.bundle \
  --output artifacts/teleop-releases \
  --domain 23 --namespace /uav/demo/teleop \
  --ros-prefix /sys_prod/robot/install \
  --messages-prefix /data/local/workspace/ros/install \
  --python-root /sys_prod/robot/out
```

这三个前缀是旧环境示例，不能作为当前设备已具备依赖的证据。输出包含 flight、命名空间协议、环境脚本、前台启动脚本、摘要与清单，不复制 PC 库或整套 ROS。Python 应用不需要交叉编译；若目标消息绑定缺失，须先使用 Docker 准备匹配目标 ABI 的公共依赖，不在部署时临时替换 Linux 二进制。

实际部署前完成 HDC 版本/目标核实、板端 Python/rclpy、四种 px4_msgs 和标准消息的加载/序列化及双向 DDS 预检。使用 hdc-master、oh-ros2 技能时按各自预检规则执行。设备操作入口：

```sh
# PC，替换明确设备标识与上一步打印的 release 目录。
uv run python -m leuav.deployment.hdc \
  --target '<connect-key>' --bundle artifacts/teleop-releases/<release-id>
```

部署只上传到 `/data/local/workspace/leuav/teleop/releases/<release-id>`，传输后校验摘要，不覆盖已有 release，不启动/停止程序；失败保留文件供诊断。已有目录时拒绝覆盖，应检查其状态。设备 shell 中按上传命令打印的完整路径前台运行 `sh .../start.sh`。不要同时启动 PC flight；PC keyboard 仍通过 launch 运行。命名空间变化后重新装配部署，实际网卡白名单与 peer 由环境准备提供，本版不自动改网络。

退出顺序：K/land 请求降落 → status 确认 Disarmed → 退出 keyboard 与 flight → down。板端 flight 单独退出，仿真 down 不会停止它。键盘退出发出的 Land 请求不能作为已落地的证明。
