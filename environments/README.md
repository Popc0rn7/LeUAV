# 三个通用基础镜像

| 镜像 | 职责 | 当前内容 |
| --- | --- | --- |
| `uav-computer-builder:local` | PC 原生构建与 OHOS 交叉构建 | Humble 生成工具、GCC/CMake/Ninja/colcon、公共开发依赖和 Agent 构建产物；SDK 外部挂载 |
| `uav-computer:local` | PC 算法与控制运行 | 官方 Humble ros-core＋固定 px4_msgs；无 GCC、colcon 或 Agent，算法特有运行库随案例追加 |
| `flight_board:local` | 飞控与仿真接线 | 现成 PX4/Gazebo＋从 builder 提取的 Agent、双进程管理与显式 UDP 配置 |

当前采用一个 worktree 测试一个应用，不开发并行实例或端口分配机制。基础镜像只提供运行/构建能力，源码、任务与资源绑定由工作区提供；构建产物、SDK、模型、场景和日志不提交 Git。

## 基线与资源准备

当前 builder 采用已验证的本机 `uav-computer-ohos:local` 依赖基线，实际 image ID 固定为 `sha256:ce4401623e23a88e84d426778b66bc988d44aa2f653c4362d4f114e8e634ab2c`。它源自课程的 Humble 开发镜像与 OHOS 工具增量，包含已有公共构建依赖。构建脚本先核对本机 image ID，不把本机导入镜像的记录摘要当作公共 registry 可拉取的地址。

该基线镜像的外部分发/下载入口尚待补充；新机器须先取得此镜像，当前不宣称仅靠公开镜像可从零重建整个 builder。后续可以替换为完整源码配方，但须重验依赖及产物。原配方的维护来源为课程仓库 tools/docker/Dockerfile 与 Dockerfile.ohos；它们是来源记录，不是新框架的运行目录依赖。

runtime 使用官方 `ros@sha256:def377f78b58f925e26a2f1f082708d5efed8a602ed43f66449c73618df349a9`，flight_board 的 PX4 基底固定为配方中的公开 digest。两者需在本机可用；拉取缺失公共镜像涉及网络，按权限流程执行。运行镜像只复制 builder 的 PC 消息安装产物，不复制其工具链或整套开发环境。

`resources.local.yaml` 或用户级 resources.yaml 中绑定 `ohos_sdk` 到 SDK native 根目录；仅 OHOS 构建需要。ADRL 场景绑定见案例入口。SDK 和目标 ROS 依赖快照保持外部只读输入，不封进镜像；目标依赖按实际算法显式选择。

## 构建与检查

在 LeUAV 根目录、已安装项目环境且具有 Docker 权限的 PC 执行：

```sh
uv run --no-sync python tools/build_images.py
uv run --no-sync python tools/validate_builds.py
```

第一个命令顺序构建三个镜像，RUN 阶段无网络下载，保存配方摘要、镜像身份和构建日志到 artifacts/images。底层基础镜像必须先准备好；脚本失败时保留日志，不继续后续镜像。

第二个命令使用同一 builder 的 pc/ohos 目标构建同一个 C++ 探针；PC 产物实际执行，OHOS 只审计 ELF 架构/程序头/动态依赖，不在 PC 执行。SDK 缺失时停止；实际 OHOS 构建前按 oh-ros2 技能预检。探针输出在 artifacts/build-probe 中按目标隔离。探针通过不等于算法、ROS 目标包或板端业务通过。

PC runtime 在 Docker build 中检查 rclpy、标准消息、四种 PX4 消息 CDR 往返及 VehicleStatus v4，确认无 GCC、colcon、Agent。上游 ros-core 自带的 CMake 仍保留；运行链路不依赖它，不宣称已删除上游所有构建相关包。

环境角色细节见 [Humble 构建/运行](humble/README.md)、[OHOS 目标](robopi-cross/README.md) 与 [flight_board](flight_board/README.md)。实际结果统一见 [Validation](../docs/Validation.md)。

## 应用验证

将本机 ADRL profile 绑定 `flight_board:local` 与 `uav-computer:local`，按 [SSH/GUI 标准流程](../docs/ssh-validation.md) 做静止/DDS/关闭验证，再按 [Keyboard](../cases/keyboard/README.md) 做真实键盘操作。builder 不参与日常仿真运行。模型 FastAPI 服务仍独立部署。
