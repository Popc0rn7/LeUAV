# LeUAV 架构与开发约定

本文确定框架的目标边界、目录职责与迁移方式。资源定位及 ADRL/keyboard 初版源码已落位，其余结构与接口为设计约定，按案例迁移逐步实现；不代表所有组合已经支持或经过验证。

## 目标与仓库关系

LeUAV 持续维护无人机开发所需的环境、接入、运行、构建、部署与诊断能力，以 SUPER、GCOPTER、AeroVLA、Agent 等案例验证完整链路。

课程仓库保留教学目标、阶段顺序、练习、课堂配置与交付流程。后续通过 Git submodule 引用 LeUAV 的明确提交，调用框架及案例。框架源码只有一个维护入口；课程采用更新时显式更新引用并验证。框架中的资源与源码定位不得依赖自己一定处于 Git 顶层目录。

模型、SDK、场景和已有依赖保持原位，通过资源映射定位；不使用 server-resources 目录装配机制，不因迁移重新复制重型资源。

## 系统的独立维度

| 维度 | 目标实现 | 责任 |
| --- | --- | --- |
| 模拟器 | AirSim、ProjectAirSim、Gazebo；后续 Isaac Sim | 场景、传感器、仿真时钟、碰撞与真值 |
| 飞控 | PX4、模拟器内置或简化控制方案 | 飞行状态、解锁、起降、控制指令与失效行为 |
| 执行位置 | PC、RoboPi | 进程执行、文件装配、通信、部署与诊断 |
| 推理执行 | PC NVIDIA、RoboPi Houmo NPU、远端服务 | 模型加载、推理、设备资源与服务生命周期 |
| 案例 | SUPER、GCOPTER、AeroVLA、Agent | 规划、模型输入输出、业务决策与任务编排 |

分别组织这些维度，通过运行配置组合。组合具有能力要求和兼容约束，不做任意组合均可运行的承诺。Gazebo 简化控制的具体实现待接入时选择；Isaac Sim 暂不实现、不预建空目录。

算法位置与推理位置独立：PC Agent 可以调用 RoboPi 模型服务，RoboPi 算法也可以调用 PC 服务。ROS 用于需要其消息语义的链路，模型推理统一通过独立 FastAPI 服务提供 HTTP 进程间通信；纯 Python 业务不因此强制封装成 ROS 节点。

## 目录职责

以下为初版职责布局。已建立的模块目录以说明文件标记待接入范围，尚无具体后端实现；Isaac Sim 等未来后端按实际需要再创建。

```text
leuav/
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
├── AGENTS.md
├── resources.example.yaml
├── src/leuav/
│   ├── resources.py          # 外部资源配置与定位
│   ├── adrl/                 # ADRL 案例 Python 实现
│   ├── teleop/               # keyboard 案例 Python 实现
│   ├── contracts/            # 公共状态、指令、坐标与时间契约
│   ├── runtime/              # 配置装配、实例与生命周期、运行记录
│   ├── simulation/           # 各模拟器 SDK、传感器与场景接入
│   ├── flight/               # PX4 等飞控接入、控制转换
│   ├── inference/            # 模型服务协议与客户端公共能力
│   ├── deployment/           # PC 容器、RoboPi 部署与目标诊断
│   └── diagnostics/          # 采集、日志、评测公共能力
├── native/                  # 框架公共 C/C++、ROS 包与消息定义
├── cases/
│   ├── adrl/
│   ├── keyboard/
│   ├── super/
│   ├── gcopter/
│   ├── aerovla/
│   └── agent/
├── services/                # 独立 FastAPI 模型服务及硬件适配
├── profiles/                # 明确的系统组合与运行参数
├── environments/
│   ├── flight_board/        # 现成 PX4/Gazebo＋Agent 的精简增量镜像
│   ├── px4/                 # 旧环境导航，指向 flight_board
│   ├── humble/              # uav-computer-builder / uav-computer 配方
│   └── robopi-cross/        # 统一 builder 的 OHOS 目标配置，不另建镜像
├── tools/                   # 构建、转换、装配、审计等维护入口
├── tests/                   # 公共能力测试及跨组件集成测试
└── docs/                    # 开发、接入、环境准备与验证记录
```

`src/leuav` 维护可复用的 Python 框架。`native/` 只放公共原生包；案例特有的 C++、ROS 包、Python 代码留在对应案例内。算法核心可在 `cases/<name>/core/` 保留原有包布局、第三方来源与许可证，不按语言拆散整棵源码树。

案例通常包含核心源码、适配代码、配置、构建装配入口、测试和说明，按实际需要设置子目录。可导入的 Python 案例实现采用具名包并明确安装方式；不靠注入旧仓库根路径或不断修改 sys.path 运行。框架不反向依赖案例；运行配置显式选择案例入口。迁移时确定具体包布局，不要求所有案例具有同一套内部目录。

框架不以课程 stage 编号组织能力。首个 ADRL/keyboard 案例以 src/leuav/adrl、src/leuav/teleop 安装具名包，cases 维护操作与来源索引。案例的唯一操作入口说明准备、构建、运行与恢复；课程文档描述学习任务并引用框架，避免另维护一套基础安装流程。

## Docker 与执行环境

固定维护三个基准镜像；一个镜像可以启动多个容器，构建镜像不必参与日常运行。

| 镜像 | 环境与责任 | 输入与输出 |
| --- | --- | --- |
| `uav-computer-builder` | ROS 2 Humble 主机构建工具，支持 PC 原生构建与 OpenHarmony 交叉构建；包含编译器、CMake/Ninja、colcon、消息生成工具及工具链接入 | 挂载唯一源码；OHOS SDK 与目标依赖快照通过资源映射挂载；PC/OHOS 产物分别输出 |
| `uav-computer` | PC ROS 2 Humble 运行环境；运行算法/控制节点、消息类型支持与 Python SDK | 消费已构建的 PC 产物，开发时挂载源码与配置；不要求 GCC/CMake/colcon 等构建工具 |
| `flight_board` | PX4 SITL、MicroXRCEAgent 与 Gazebo 运行环境；原始传感器桥按后端逐步接入 | AirSim 模式启动 PX4＋Agent；Gazebo 模式另启相应仿真组件；输出飞控日志及 ULog |

三个名称是框架镜像角色，配置可暂时绑定已验证的兼容镜像；不把逻辑名称当成已有本机 tag。builder 与 computer 可通过一个多阶段 Dockerfile 导出，三个镜像配方已建立并实际构建。environments/humble/Dockerfile 的 builder/computer 两个 target 分开导出；builder 复用固定开发依赖基线，computer 从官方 ros-core 派生并复制 PC 消息产物，flight_board 从 builder 提取 Agent。基线资源和探针边界见环境总入口。

PC build 与 OHOS build 在同一 builder 中显式选择目标。主机工具与目标 sysroot 分开，不能让交叉编译回退链接 PC 库。builder 输出的 PC install、OHOS install、缓存和部署包按目标分别存放；运行镜像消费必要可执行文件、ROS 安装产物、Python 模块和动态库，不能只复制一个算法 ELF。

RoboPi 原生运行 OpenHarmony ROS 2 Humble，不在板上要求 Docker，也不新增独立的 ohbuild 镜像。普通 Python 应用可直接装配；其目标原生依赖需要构建时使用统一 builder。已有宿主机构建脚本只作迁移参考，不成为框架隐式依赖。

PC Linux 与 RoboPi OpenHarmony 的二进制分别构建。对齐 ROS 发行版不代表 ABI 相同；不得复用 Linux install 作为板端产物，也不把 apt 依赖清单整体复制到板端。

模拟器根据后端选择宿主机或容器。AirSim、ProjectAirSim 可先保留宿主机运行；Gazebo 按实际镜像接线；Isaac Sim 后续独立接入。NVIDIA 模型服务可用专属容器，不把全部推理依赖装进 Humble 基础镜像。

镜像维护系统依赖，源码通过挂载参与开发。修改源码按需重启或重新编译；修改环境依赖则重建镜像。基础镜像记录来源与 digest，增量配方进入 Git；案例特有的重型依赖采用增量环境，避免基础镜像无限膨胀。GPU、显示、网络与设备权限由明确运行配置启用。

宿主机管理 CLI 当前要求 Python 3.12。Humble 容器的 Python 和板端 Python 分别按各自环境固定，不能要求所有执行端安装同一宿主机包或使用同一 venv。迁移时拆清主机管理代码与目标运行代码的依赖闭包，分别测试；跨端协议记录兼容版本。

## 接口与运行装配

模拟器接口提供传感器、时钟及场景生命周期；真值专用于诊断与评测，不能默默进入算法定位。飞控接口提供状态与控制能力。模拟器内置飞控可保留在对应模拟器适配中，向上满足飞控契约；AirSim/PX4 HIL 等组合接线由运行装配显式组织，避免假装它与两侧版本无关。

公共契约按实际接入需求提取，至少明确坐标系、单位、时间源、采集时间、QoS、命名空间、频率及超时语义。world ENU/body FLU 与飞控 NED/FRD 在适配边界转换；点云必须实际变换 XYZ，不能只改 frame_id。仿真时间与通信看门狗墙钟分别使用，不相减两机绝对单调时间。

飞控后端声明支持的位置、速度、加速度等控制能力；不支持的能力在启动前拒绝。简化控制与 PX4 的动力学、状态估计和故障行为分别验证。

`profiles/` 使用 YAML 表达一个运行组合，描述：

- 案例、模拟器、飞控及其兼容参数。
- 进程角色、执行端、镜像和依赖的资源 ID。
- ROS 域、端点、命名空间、通信方式与时钟来源。
- 案例参数、任务配置、显式故障策略与产物位置。

第一版按案例验证这些字段，再提取公共 schema；本文不固定尚未实现的 API 或 CLI。配置引用外部资源 ID，不嵌入维护者 home 路径。运行管理器解析宿主机资源后生成容器挂载及容器内路径，宿主机路径、容器路径和板端路径分别记录。

生命周期保留 up/status/task/land/stop/down 的明确含义，并按能力开放：进程存在、服务 ready、飞控可控和任务完成分别报告。降落请求不等于 Disarmed，急停不等于降落成功。只管理当前实例拥有的进程、容器和板端目录，部署显式选择设备，保留诊断与恢复入口。

## 外部资源与产物

已实现的资源定位使用用户级 `~/.config/leuav/resources.yaml`，遵循 XDG_CONFIG_HOME。工作区 `resources.local.yaml` 按资源名称覆盖用户映射并被 Git 忽略。相对路径相对于声明它的配置文件，支持 `~`；多工作区与未来课程 submodule 共用用户映射。

本机 YAML 只记录实际路径。仓库保存配置示例，并在案例接入时声明资源用途、版本要求、来源、许可、必要文件及校验依据。当前资源模块仅检查路径存在，不能据此宣称模型或 SDK 兼容。

不自动扫描整个 home、不自动搬移、不自动修改资源；后续若增加发现工具，只读扫描用户指定范围，由显式配置确定最终绑定。权重、SDK 和原始依赖默认只读挂载。模型转换输出与应用私有运行包另行生成，不覆盖共享输入。

PC 构建、OHOS 构建、模型转换和运行产物隔离；可写产物使用工作区忽略目录或显式外部输出位置。构建身份至少区分源码、镜像、目标 ABI、工具链和依赖快照，不能跨工作区盲用同名 install。Git 不保存模型、大型场景、SDK、构建缓存、日志、真实密钥或本机配置。

远端推理服务地址属于运行配置，不伪装成文件路径资源；凭证从本机私有配置注入。

## 典型案例如何适配

### SUPER 与 GCOPTER：原生算法、ROS 2 Humble 与上板

算法核心及其 ROS 包保留在各自案例中。ROS 1 到 ROS 2 Humble 的移植修改属于案例源码，记录上游版本、补丁与许可证。公共消息生成、容器执行、交叉工具链调用、ELF 依赖审计和部署清单可逐步共享。

PC 路径为 Humble 容器内构建与运行；RoboPi 路径为交叉编译容器生成原生目标产物，再由 PC 管理入口部署。共享源码，不共享 PC/板端 install。目标依赖通过设备或匹配镜像导出快照核验；区分主机 rosidl 生成工具与目标 Python/ROS 原生库。

SUPER 和 GCOPTER 可共用定位、配准点云、时钟、目标输入与 PX4 控制接入；地图、搜索、优化、轨迹表示、FSM 及执行反馈仍按实际算法保留。通过显式适配转换到公共控制契约，不能为统一接口偷偷替换算法路径或改变终止条件。

当前课程源码核对依据：`stage2/super/core/`、`stage2/gcopter/core/`、`stage2/robopi/compile/` 和 `stage2/gcopter/Planner-alignment.md`。GCOPTER 当前共享链路的实现范围包含 RoboPi 后端，不能把历史独立 PC 示例算成新框架 PC 后端已验收。旧 GCOPTER README 中仍有子模块历史描述，源码归属应以当前实际目录及较新开发记录为准。

### AeroVLA：Python 应用与独立模型服务

AeroVLA 应用位于 cases/aerovla，负责采集业务输入、构造请求、处理模型结果和执行任务。应用通过 HTTP 调用独立 FastAPI 服务，不直接加载 HMM、TCIM 或 NVIDIA 推理库。Python 应用按自己的依赖装配部署，不因为模型运行在 RoboPi 就要求应用交叉编译。

模型服务位于 services，负责模型加载、模型所需预处理、推理和硬件资源管理。Houmo 的 TCIM/HAL、目标 Python 原生绑定及其 ABI 检查仅属于服务内部；NVIDIA 服务独立维护对应环境。已有匹配且验证过的运行库优先复用，需要构建目标原生依赖时使用交叉编译容器。模型转换单独记录来源与产物，不能从已有 HMM 推断具备转换能力。

应用与服务可以同机或跨机运行，分别构建、部署和管理生命周期。请求、响应、超时、错误、协议版本、忙时行为与健康状态需要明确；具体 schema 随首个服务接入确定。inference 维护公共客户端和协议，services 维护服务端与硬件依赖，cases 维护任务语义。应用侧的业务输入整理与服务侧的模型预处理按请求协议划界，避免两端重复处理。

HMM、embedding、词表等由服务通过资源映射读取。服务推理成功不代表飞行任务闭环成功。切换 NVIDIA/Houmo 时分别验证协议兼容与数值效果，不承诺同一模型文件跨硬件直接运行。

当前核对依据为课程仓库 houmo/src/aerovla/README.md、runner/服务布局及 stage3/framework/deployment.py；这些是迁移来源，不是 LeUAV 运行依赖。现有实现向 FastAPI 服务迁移尚未完成。已有推理证据覆盖预处理张量与 token 输入，迁移后的接口、任意图文输入与飞行闭环分别验收。

### Agent：任务编排与分布式模型服务

案例维护任务协议、提示词、决策循环和工具编排；复用飞控、传感器与推理服务接口。应用通过 HTTP 调用独立 FastAPI 模型服务，服务可部署到 NVIDIA 或 Houmo。任务预算与模型服务并发限制分别管理。模型建议经过确定性输入与控制约束检查后进入执行层。

## 迁移、验证与交接

先迁一个完整案例，再从第二个案例的实际共同需求提取框架能力。先以 ADRL＋AirSim＋PX4 与 keyboard 的 PC/RoboPi 控制路径校准仿真和通信边界，再以 SUPER 的 PC/RoboPi 路径校准算法构建与部署，再以 GCOPTER 验证规划后端边界，以 AeroVLA/Agent 验证 Python 与分布式推理路径。

每批迁移固定来源提交、本地补丁、资源身份、已有验证及已知缺口。旧课程仓库作为参考，迁入代码以 LeUAV 为维护入口；接回课程前避免长期双向维护。迁移可以复用未变化层的证据，但必须验证新路径、装配和运行环境，不依赖旧仓库目录、旧 sys.path 或个人缓存才能启动。

验收逐层推进：

1. 独立导入、配置解析与资源定位。
2. PC 构建或目标交叉构建、包清单与 ABI/依赖审计。
3. 目标加载、服务 ready 或双向消息。
4. 静止传感器、坐标、时钟与地图。
5. 低速短程及故障恢复。
6. 完整任务与可重复性。

按实际案例选择必要步骤，纯推理案例不强制飞行。组合记录支持、实验中或未验证状态；更换模拟器、飞控、镜像或执行端后，明确需要重验的层。

每次运行保留源码身份、镜像 digest、资源版本、目标 ABI、配置快照、run ID，以及报告、节点日志、ULog 或评测索引。文档只提交结论与证据索引，原始日志保存为忽略产物。没有设备或模型条件时明确未测，不以静态检查替代在线验收。

本文确认组织方案可以容纳上述案例；ADRL 与 keyboard 已接入；旧布局有一次 PC 短起降证据，flight_board 新镜像已构建并通过静止及真实 PX4 消息验证，新布局飞行与 RoboPi 另行验收。框架验证记录应随实际迁移建立，不能将课程历史结果直接标记为 LeUAV 已通过。

## flight_board 进程边界

MicroXRCEAgent 与 PX4 同属 flight_board，由统一入口管理进程组、退出与健康状态。任一关键进程退出时停止同实例的另一进程，不能把 Agent 进程存在当作 PX4 传感器就绪。Agent 私有动态库只作用于 Agent 子进程，不改变 PX4/Gazebo 的库搜索路径。

AirSim GUI 和 settings 在 host；keyboard、PC flight 在 uav-computer，板端模式只将 flight 迁至 RoboPi。uav-computer 容器可保持空闲供显式启动控制程序，不再承担 Agent。px4_msgs 及其绑定仍由 PC/板端算力环境提供。

当前默认入口覆盖 AirSim 外部 HIL；镜像继承原有 Gazebo 能力，具体 Gazebo 启动组合、原始传感器桥和多机实例尚未在新布局验收，不宣称所有模式均已接入。

当前每个 worktree 按单应用测试推进，不引入多实例端口分配与并行调度。共用的是基础镜像和只读资源，实际应用运行仍由本工作区 profile 与 run ID 管理。
