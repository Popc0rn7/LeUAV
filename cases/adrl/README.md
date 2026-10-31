# ADRL＋AirSim＋PX4

初版已接入场景准备、PX4/DDS Agent 生命周期、状态、降落请求、仿真急停和原生 Tier 2 开赛。Python 实现在 `src/leuav/adrl/`，通用 SDK 在 `simulation/airsim/`，进程身份与回收在 `runtime/processes.py`。不依赖课程仓库、组号或排行榜。

当前已在本机通过静止启停及一次 PC keyboard 短起降；范围与证据见 Validation。换机仍须绑定资源与镜像，按 [SSH 验证流程](../../docs/ssh-validation.md) 预检。QGC 作为外部工具，不需要专门接入。

## 进程部署

| 进程 | PC 控制模式 | RoboPi 控制模式 |
| --- | --- | --- |
| 管理 CLI、资源/profile 解析、兼容准备、RPC 持久代理 | PC host | PC host |
| ADRL/AirSim GUI，读取生成的 settings | PC host | PC host |
| PX4 SITL | flight_board 角色容器；本例不启动 Gazebo | 相同 |
| MicroXRCEAgent | 与 PX4 同属 flight_board，由统一入口管理 | 相同，Agent 不迁到板端 |
| keyboard | 同一个 uav-computer 容器，交互 PTY | 相同 |
| flight | 同一个 uav-computer 容器 | RoboPi 原生 Humble；不再启动 PC flight |
| uav-computer-builder | 日常运行不启动；准备 PC 产物时使用 | 需要目标原生构建时使用；Python flight 本身直接装配 |

镜像角色不等于容器名称。当前实际容器为 leuav-adrl-px4、leuav-adrl-humble，绑定的兼容镜像仍由本机 profile 指定；新三镜像布局已通过静止、实际状态接收及一次 PC keyboard 起降/短前向输入；仅验证这一明确组合。

up 启动 host 场景、RPC 代理、PX4 与 Agent，不启动 keyboard/flight。start-race 发起原生赛务；随后按 [Keyboard 入口](../keyboard/README.md) 单独启动控制进程。宿主机及 runtime 的依赖需各自齐备，builder 不参与该启动链。两端控制只能选择一份 flight。

## PC 一次性准备

需要 Linux 图形桌面、X11/XWayland、Vulkan、Docker，以及完整 ADRL 原包。资源实体保持原位。兼容补丁只接受 ELF SHA-256 `094ad6b3cb8f55b63a05ab6ca9ee91e18c3eac1d21b64b20451302ba427c68bc`，未知版本直接拒绝；不覆盖原包。

在用户级 `~/.config/leuav/resources.yaml` 或工作区 `resources.local.yaml` 中绑定完整包根目录：

```yaml
resources:
  adrl_package:
    path: /本机原包目录
```

该目录应包含 `Engine/`、`ADRL/Content/`、`ADRL/Binaries/Linux/ADRL`。

在 LeUAV 根目录安装宿主机管理工具与可选 AirSim SDK：

```sh
uv sync --extra airsim
```

Humble 镜像准备见 [环境说明](../../environments/humble/README.md)，flight_board 构建与启动要求见 [飞控环境](../../environments/flight_board/README.md)。镜像身份与实际兼容性在运行验证时记录，不自动拉取未知镜像。

复制 `profiles/adrl.example.yaml` 为 `profiles/adrl.local.yaml`，填写实际镜像、ROS domain 和命名空间。示例 domain 只是待选择参数，不是本机验收值。配置不依赖课程根 `.env`。`output` 相对 YAML 文件解析，资源路径相对资源映射文件解析。

## PC 启停与原生开赛

以下在 LeUAV 根目录执行：

```sh
uv run leuav adrl --profile profiles/adrl.local.yaml plan
uv run leuav adrl --profile profiles/adrl.local.yaml up
uv run leuav adrl --profile profiles/adrl.local.yaml status
uv run leuav adrl --profile profiles/adrl.local.yaml start-race
```

`plan` 只解析配置与资源，不调用 Docker。`up` 要求 px4_image 绑定已构建的 flight_board 镜像，固定实际镜像 ID，生成独立兼容 ELF 与设置快照；大型 Content/Engine 仅建立到原包的链接。算力容器只保持空闲供控制程序启动；Agent 在 flight_board 内运行。等待传感器时间递增、定位有效、RPC 及 Agent 就绪，准备原生出发位，不自动解锁或开赛。preflight 单独报告，ready 不等于允许起飞。

`start-race` 要求 prepared、未解锁及链路就绪，调用原生 `simStartRace(2)` 并观察占位机退出比赛；不确定回复不会自动重放。之后按 [Keyboard](../keyboard/README.md) 启动控制链。当前保持单实例 host 网络，改容器名不能隔离相同端口。

```sh
# 请求降落；随后 status 检查实际 Disarmed。
uv run leuav adrl --profile profiles/adrl.local.yaml land
uv run leuav adrl --profile profiles/adrl.local.yaml status
# 退出控制程序且确认 Disarmed 后正常关闭。
uv run leuav adrl --profile profiles/adrl.local.yaml down
# 失控或场景卡住时，明确使用仿真急停；不代表正常降落成功。
uv run leuav adrl --profile profiles/adrl.local.yaml down --force
```

`stop` 与 `down --force` 都是仿真急停。正常关闭拒绝未确认 Disarmed 的实例。只操作本次 owner label、容器 ID 和 PID/start ticks 匹配的资源，保留日志；恢复命令不要求原包路径仍可用。运行中不要改变配置的 output 或移走状态文件。

## 本版范围与后续验收

原生赛务保留五分钟时限及结束不自动摆位的兼容行为。本版未迁入排行榜、成绩监测、赛末自动降落、abandon 或落地 reset；比赛结束后须独立降落并确认 Disarmed，重复运行使用 down/up。不能把原生赛务结束视为飞控停止。本版不宣称完整竞速交付或课程原流程等价。

`artifacts/adrl/<run-id>/` 保存配置/镜像快照、兼容摘要、场景、算力容器及 PX4 日志，px4-logs/agent-console.log 和 ULog。启动失败保留错误与 traceback，并尝试回收本轮已知资源。板端 flight 由操作者单独管理，down 不会远程杀板端程序。

来源与迁移摘要见 [ORIGIN.json](ORIGIN.json)，当前结果见 [Validation](../../docs/Validation.md)。下一步先绑定真实资源和镜像，通过静止启停，再分别验证 PC 控制、RoboPi DDS、短程起降与失流行为。已有课程证据仅作参考。
