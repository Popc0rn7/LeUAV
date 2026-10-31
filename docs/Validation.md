# 验证记录

## 2026-10-30 初版骨架

- YAML 资源解析与 CLI 已实现，4 项自动测试覆盖配置覆盖、相对路径、错误格式及缺失资源。
- 已建立模块职责说明、案例及 Docker 环境边界；模块导入检查不代表运行链路已实现。
- 未绑定真实模型/SDK/场景；未完整安装开发环境、构建镜像、迁移案例、连接设备或飞行。
- FastAPI 服务为已确定的架构边界，服务端与请求协议尚未迁入实现。
- 历史课程运行结果仅作为迁移参考，不能计为 LeUAV 验收。

后续按变更记录源码版本、环境条件、结果、证据索引和下一步；原始日志不提交 Git。

## 2026-10-30 ADRL 与 keyboard 初版接入

- 来源提交与文件摘要见 cases/adrl/ORIGIN.json；未复制场景、镜像或模型。课程仓库保持不变。
- 已接入：ADRL 兼容副本准备、独立资源/profile、场景与 PX4/Agent 生命周期、原生 Tier 2 开赛、完整键盘/flight、板端 Python 包装配与显式 HDC 上传入口。
- 实际通过：35 项离线测试，覆盖已有控制状态机、键盘映射与过期、资源/profile、未知 ELF 拒绝、外部容器拒绝、Agent 单一职责、开赛不确定回复不重放、启动失败清理、包摘要及定向上传；Python AST、CLI help、shell 语法与本地文档链接检查通过。测试使用 ROS/Docker/HDC 替身，不是在线验收。
- 未测：AirSim 可选依赖完整安装、Docker 镜像构建、真实 ADRL 补丁与启动、PX4/Agent 实际通信、板端加载/序列化、双向 DDS、起降与飞行。当前工作区无课程 .env，历史 ADRL 原包路径不存在；未扫描整个 home，也未连接设备。
- 运行现场：未生成真实 run ID、日志或 ULog；测试仅在临时目录生成合成产物。
- 实现边界：仅原生赛务；排行榜、赛末自动降落/成绩监测、abandon 与落地 reset 未迁入。本版重复比赛须独立降落、确认 Disarmed 后 down/up。
- 下一步：绑定实际原包和明确镜像，记录版本/摘要并先验静止启停，再分别验 PC 控制及 RoboPi 消息/短程；不能继承课程历史飞行通过结论。

## 2026-10-30 SSH GUI、静止生命周期与 PC keyboard 在线验证

条件：SSH 登录同用户本机桌面，实际 DISPLAY=:1、XAUTHORITY=/run/user/1002/gdm/Xauthority；xdpyinfo 与 Vulkan 检查通过。RTX 4090、驱动 580.178.04。沙箱内 Docker socket/桌面总线受限，经 require_escalated 授权后执行，未改变系统权限或使用 xhost +。

- 原包：`/home/wqy/AirSim/scenes/adrl`；ELF SHA-256 `094ad6b3cb8f55b63a05ab6ca9ee91e18c3eac1d21b64b20451302ba427c68bc`。复验后摘要未变；兼容副本及日志在忽略 artifacts。
- PX4：`sha256:54a7a15ba35b3f4786256296d89edd144e000f40084cb6ed692fcbf74c9168f2`；Humble：`sha256:33e69ebfdc2fa44cf1de692244358a234c03f5aa379296d543bfee373a14d4f8`。复用了本机已准备镜像；新 environments/humble/Dockerfile 尚未构建验收。
- 安装：`uv sync --extra airsim` 成功，独立 Python 3.12.16 venv 与 uv.lock；真实 SDK/RPC 工作。ROS 运行端为现成 Humble 镜像内 Python 3.10。
- 第一轮 run ID：`781942d0656044e6a736e0bbd1b956d4`。GUI 窗口 1280×720、Soccer_Field_Easy 12 赛门、传感器递增、定位有效、Agent 存活、preflight OK；原生准备位水平误差 0，静止 landed/Disarmed 通过。
- PC 控制：真实 keyboard PTY 的 L→flight→DDS→PX4 起飞，确认 Armed、nav_state=2（Position）、failsafe=False；三次悬停采样 z 约 -2.053 m，水平速度分量绝对值小于 0.015 m/s。K 请求降落后实际 landed=True 且 arming_state=1（Disarmed）；退出 keyboard/flight 后正常 down。一次短起降通过，不代表方向操纵、失流、完整比赛或重复成功率通过。
- 在线发现并修复：teleop.launch 覆盖 PYTHONPATH，导致 flight import rclpy 失败；改为在已 source 的 ROS 路径前追加框架目录，Agent 启动同样保留环境。补充回归测试，不能将先前离线替身测试当作已覆盖环境接线。
- 第二轮 run ID：`6338d3a15dd843e4a9b98cf9e9d3f4c9`。可重复工具执行冷启动、至少 15 秒静止 ready/Disarmed/landed 观察、正常 down 与无残留核查通过。报告：`artifacts/adrl/validation/20261030T104512Z/report.json`，结果 passed。
- 证据：第一轮 `artifacts/adrl/<run-id>/pc-keyboard-validation.json`；两轮各有 settings、source-snapshot、兼容摘要索引、场景/Agent/PX4 日志及 px4-logs 下 ULog；未对 ULog 做完整离线质量评审。第二轮分项日志在 validation 目录。源码快照在运行后采集，期间除第一轮控制前已记录的 PYTHONPATH 修复外未改运行源码。
- 板端：HDC `/home/wqy/robopi/ohos-sdk/toolchains/hdc`，版本 3.2.0g，实际设备列表 Empty。未连接/上传/启动 RoboPi；目标 ABI、序列化、以太网 DDS 和板端控制未测。
- 收尾：本次两轮场景与容器正常关闭，日志保留，原包未修改，课程仓库未修改。方向控制、失流、完整竞速、排行榜/赛末收尾/reset 仍待实现或验证。

复用入口与权限规则见 [SSH 验证流程](ssh-validation.md)。以当前验证范围为准，上节“在线未测”是接入当时状态，不覆盖本节新增证据。

最终独立工作区检查：从 LeUAV 根目录运行 39 项测试通过。另修正了迁入测试里残留的 stage1.bridge 导入；此前从课程目录执行时该依赖被掩盖，不能视为独立性验证。今后回归必须从 LeUAV 工作区执行。

## 2026-10-30 三镜像职责统一

架构、环境说明、示例 profile 与开发约定统一为 uav-computer-builder / uav-computer / px4-gazebo；builder 同时承担 PC/OHOS 构建。此次仅统一文档与示例，未修改本机 profile、历史镜像、Dockerfile 或运行代码，未重建或重飞。单阶段 Dockerfile 的实际拆分及新镜像验证仍待实施；既有在线结果保持原镜像身份。

## 2026-10-31 flight_board 镜像升级与 Agent 迁移

- 变更：三镜像角色中的 px4-gazebo 改为 flight_board。24 行增量 Dockerfile 基于固定 PX4/Gazebo 镜像，提取现有 Humble 镜像中固定 commit 的 Agent 及私有动态库，不安装 ROS/编译工具，不修改基础镜像。builder/computer 的彻底构建运行拆分仍待实施。
- 基础：`px4io/px4-sitl-gazebo@sha256:54a7a15ba35b3f4786256296d89edd144e000f40084cb6ed692fcbf74c9168f2`（Ubuntu 24.04）；Agent 来源 `uav-computer-ros-humble:local`，实际身份 `sha256:33e69ebfdc2fa44cf1de692244358a234c03f5aa379296d543bfee373a14d4f8`（Humble/Ubuntu 22.04），Agent commit `57d086216d01ec43121845d385894a25987f8a2c`。OS 不同的兼容性只在本轮明确组合下验证。
- 最终构建身份：`flight_board:local`，Docker inspect 返回 `sha256:a62f00e2f609e64f2467779bfe9feaacb7d1e9568c797905913fcb628c11971d`。镜像总大小 4627140281 B，基础 4603549730 B，增量约 23.6 MB。Agent 的来源/逐文件摘要和目标 ldd 结果随镜像保留。
- 运行：统一入口管理 PX4 和 Agent 两个进程组。Agent 环境中的私有动态库和传输配置不泄漏到 PX4。uav-computer 仅保持空闲供显式启动 keyboard/flight，实际 Agent 不再运行于该容器。本机 profile 绑定新镜像，原 profile 备份在忽略目录 artifacts/flight-board-upgrade/profile-before.yaml。
- 离线：45 项测试通过，包含 Agent/PX4 任一退出时结束另一进程、SIGTERM 清理、Agent/PX4 环境隔离、真实 socket 健康逻辑和消息端命名空间回归。shell/Python/XML/文档检查按本次范围完成。
- 真实容器收尾：最终镜像使用隔离网络和 sleep 代替 PX4，实际 Agent 启动健康；正常 SIGTERM 退出码 0，Agent 被终止时联动退出码 1。报告 artifacts/flight-board-upgrade/final-supervisor-smoke.json。该测试仅验证管理行为，不算 PX4 仿真。
- 已知失败与修复：迁移初期静止链路就绪、ROS 话题发现正常，但算力侧 10 秒收不到 vehicle_status。仅 Agent 使用 UDP 仍失败；两端共同使用显式 UDPv4 后连续真实消息恢复，结果与跨容器 SHM 隔离问题一致，不宣称已完成底层共享内存故障定位。未使用 host IPC 或放宽系统权限。唯一配置源 src/leuav/contracts/fastdds_udp.xml，沿用课程已用 UDP 配置结构。
- 失败证据：run `90087dbd884f433d9b85f49e6c432676` 的 dds-diagnostic.json；仅 Agent UDP 的 run `7e3e64ad949541f98321433455479250`，报告 artifacts/adrl/validation/20261031T043534Z/report.json 为 failed。更早 c743228ffe2c400d94a24882975196f8 的静止 passed 未包含真实消息接收，不能替代通信验收；首个并发只读探针与自动关闭重叠而被中断，随后已改为顺序检查。
- 最终在线通过：run `6c5c4f1e892c4b55b316339f01c69100`；报告 artifacts/adrl/validation/20261031T043732Z/report.json 为 passed。真实 AirSim GUI、Soccer_Field_Easy 12 门、PX4 传感器/定位、Agent 实际 UDP socket、至少 15 秒静止观察、Disarmed/landed、正常 down 与无残留检查通过。dds-link.log 记录算力容器收到 `/fmu/out/vehicle_status_v4` 三条消息，时间戳 1793421484814117、1793421485318135、1793421485822154，arming_state 均为 1。
- 复验流程：tools/validate_adrl.py lifecycle 已在 up 后加入只读 check_link 探针，真实消息时间递增才继续静止观察，避免只看话题发现误判。
- 条件与证据：SSH 使用同用户实际桌面 :1 及其 Xauthority，按 require_escalated 申请 Docker/GUI/目录访问。原始 ADRL ELF 摘要保持既有基线。运行设置、镜像身份、传感器/状态分项日志和 Agent/PX4 日志均留在忽略 artifacts；成功 run 的 verification-provenance.json 保存事后源码/环境配方摘要。本次未连接 RoboPi、未解锁/起飞、未复验方向控制或完整竞速。
- 收尾：场景、RPC 代理、PX4/Agent 和算力容器均已正常回收；最终 docker ps 无运行容器。课程仓库不改，原场景包保持原位。Gazebo 新布局、原始传感器桥、RoboPi DDS 和新布局飞行仍待单独验收。

## 2026-10-31 三个基础镜像与新 runtime 的 ADRL/PC keyboard 验收

本轮按单 worktree、单应用实施，不添加并行冲突处理。构建和验收均在 LeUAV 工作区进行，未连接 RoboPi 或改动课程仓库。

### 镜像构建

通过 tools/build_images.py 顺序构建三个镜像，报告 artifacts/images/20261031T123005Z/report.json 为 passed。构建阶段无网络安装，预先拉取了明确 digest 的官方 ros-core；builder 使用已固定本机开发依赖基线。

| 镜像 | 实际 Docker image ID | 大小/B |
| --- | --- | --- |
| `uav-computer-builder:local` | `sha256:659023d969394749b47e0178e331f901d62417d92e0a1ba02bd1d1d489aa1193` | 5429041875 |
| `uav-computer:local` | `sha256:028d49ee9e1d5cb1fae7ab3ffa5398bbe7d0691efa875c99505e40bd2cdd0c78` | 725396100 |
| `flight_board:local` | `sha256:b9a6b29d2781a14d794abb2f8d0f42ad3436b16b0655304cd4042f5bca7f8637` | 4627140279 |

- builder 基线：uav-computer-ohos:local，核对实际 ID `sha256:ce4401623e23a88e84d426778b66bc988d44aa2f653c4362d4f114e8e634ab2c` 后构建。初次把本机导入镜像摘要作为公共 registry 引用失败，证据在 artifacts/images/20261031T122922Z；修正为本机 tag＋构建前 ID 检查，没有申请 registry 凭据或更换权限绕过。该依赖基线的公共分发入口仍待补，不能据本轮声明新机可只靠公开镜像从零重建 builder。
- runtime 基底：官方 `ros@sha256:def377f78b58f925e26a2f1f082708d5efed8a602ed43f66449c73618df349a9`。构建时 rclpy、Twist/String、ManualControlSetpoint/VehicleCommand/VehicleCommandAck/VehicleStatus 的 CDR 往返及 VehicleStatus v4 通过；无 GCC、colcon、Agent。上游自带 CMake 保留，不能声称所有构建相关包都已裁剪。
- flight_board 从本轮 builder 提取 Agent；仍使用既有 PX4 参数、双进程生命周期和唯一 UDP 配置，不复制整套 ROS/编译工具到飞控环境。

### 同一 builder 的 PC/OHOS 探针

按 oh-ros2 技能依赖预检确认 SDK 路径、toolchain、Clang 15.0.4、SDK CMake 3.28.2 和 SDK 26.0.1.45 后执行 tools/validate_builds.py。报告 artifacts/build-probe/20261031T123103Z/report.json 为 passed：PC 生成 x86_64 ELF 并执行输出 leuav build probe；OHOS 生成 AArch64 ELF（e_machine=183），不在主机执行。SDK 只读挂载，PC/OHOS build 目录隔离。

探针为基础 C++ 编译链接能力，不是 ROS 目标包或算法移植验收。原主机 readelf 解析较新 DWARF 时有 warning，后续工具改用匹配 SDK 的 llvm-readelf，保留原日志并重新审计现有产物；SDK 自身的 gcc-toolchain unused warning 不影响本次输出。

### 新三镜像 ADRL/keyboard

- 静止 run：dbbfba4d608a4365a02dc23f86078042；artifacts/adrl/validation/20261031T123104Z/report.json 为 passed。实际 GUI、12 赛门、PX4 传感器/定位、Agent、算力侧递增 PX4 ROS 消息、Disarmed/landed、正常 down 与无残留通过。
- 飞行 run：52145d71cce34264a48b740650f37e2b；实际使用上述新 flight_board 和 uav-computer，builder 不参与运行。真实 keyboard PTY 的 L→flight→PX4 起飞，进入 Armed/Position/failsafe=False，三次悬停 z 为 -2.02135、-2.02037、-2.01867 m。
- 短 W 输入、空格回中：即时真值起点到终点水平位移约 0.33545 m，投影到起点机体前向约 0.33370 m，has_collided=False。该结果只覆盖短前向输入，未验其余方向或持续跟踪性能。
- K 请求降落，实际确认 landed=True、arming_state=1（Disarmed）且无碰撞，之后退出 keyboard/flight 并正常 down。证据为该 run 下 pc-keyboard-validation.json、settings、场景/Agent/PX4 日志和 ULog；ULog 未做完整离线质量审阅。
- 本轮结论：三个镜像建立、PC/OHOS 基础编译、ADRL 静止与 PC keyboard 起降/短前向输入通过。RoboPi 运行、ROS 目标依赖构建、失流、完整比赛、长期稳定性与其他模拟器未因此验收。

提交包含源码、配方、操作入口、离线测试与结论索引；本机 YAML、venv、SDK、镜像、编译输出和原始日志均忽略。原场景 ELF 未修改。最终检查与离线回归结果以本节后续收尾记录为准。
