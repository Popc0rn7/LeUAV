# flight_board

在现成 PX4/Gazebo 镜像上追加固定版本 MicroXRCEAgent、隔离的运行库及双进程入口。镜像不安装 ROS、编译器或算法；继承基础镜像中已有的 Gazebo 能力。keyboard、flight、规划器和 px4_msgs 仍归算力侧。

## 构建

在 LeUAV 根目录、具有 Docker 权限的 PC 执行：

```sh
docker build --pull=false --network none -t flight_board:local \
  -f environments/flight_board/Dockerfile .
```

默认 PX4 基础镜像固定 digest；Agent 来自本轮构建的 uav-computer-builder:local。两个镜像须已存在。Agent stage 校验 sources.txt 中固定 commit，提取可执行文件和非系统运行库，不将完整 Humble 镜像复制进最终镜像。可用 --build-arg PX4_IMAGE=... / AGENT_IMAGE=... 指定经过验证的来源；切换后重新构建、依赖审计与在线验证。

collect_agent.py 从来源镜像中 source Humble 后解析 ldd 闭包，保留来源和逐文件摘要；目标镜像再次运行 ldd 检查缺失库。加载器、glibc 与 C++ 工具链运行库使用目标系统；Agent 的其他库放 /opt/flight-board/lib，仅设置到 Agent 子进程，不覆盖系统库或改变 PX4/Gazebo 环境。不同 OS/架构不能只凭 ldd 无缺失宣称兼容，还需执行 Agent 和真实 DDS 验证。

当前从统一 builder 提取已有固定版本 Agent 构建产物；builder 的依赖基线与获取条件见 [环境总入口](../README.md)。不把构建工具复制进 flight_board。

## 运行与健康

ADRL profile 的 px4_image 绑定 flight_board:local；键名保持兼容，表示本轮飞控环境。默认入口启动 Agent UDP 8888 和随镜像装入的 AirSim PX4 启动脚本，保持既有飞控参数。AirSim 与 settings 由 host 管理，不在本镜像中启动 Gazebo。

```sh
# 已运行的本次容器内，status 输出进程和 Agent socket 状态。
docker exec <本次flight_board容器> python3 /opt/flight-board/supervisor.py status
```

Agent 和算力侧共同使用唯一维护源 src/leuav/contracts/fastdds_udp.xml 的 UDPv4 配置（镜像内为 fastdds.xml），与算力容器独立 IPC 空间兼容；不硬编码网卡或远端地址。标准 lifecycle 在算力容器通过 check_link 实际订阅递增 PX4 状态，不能只看话题发现。

Docker HEALTHCHECK 验证 PX4/backend 进程、Agent PID/start ticks 与它实际持有的 UDP 8888 socket。它不证明定位、传感器、飞控 preflight 或 DDS 已通过；ADRL 运行管理继续独立检查这些条件。

supervisor 管理两个独立进程组。任一关键进程退出，则终止另一进程并返回失败；SIGTERM/SIGINT 则清理两个进程组后退出，超时限定强制结束本次组。Agent 输出单独写入 /flight-logs/agent-console.log，PX4 输出保留在容器日志，ULog 使用现有挂载。场景、容器的外部所有权仍由运行管理器检查。

如后续接入 Gazebo，可显式给 `run` 传入负责 PX4/Gazebo 的前台启动命令；该启动命令必须管理自己的子进程并转发退出。当前未提供或验证统一 Gazebo 启动配置与原始传感器桥，不用 AirSim 验证替代它们。

正常停机、仿真急停和 host GUI 预检统一见 [ADRL](../../cases/adrl/README.md) 与 [SSH 验证流程](../../docs/ssh-validation.md)。本镜像只用于仿真；实际验证身份与范围见 [Validation](../../docs/Validation.md)。
