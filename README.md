# LeUAV

无人机开发框架，逐步接入 SUPER、GCOPTER、AeroVLA 与 Agent 案例。

当前已实现 YAML 外部资源定位，并接入 [ADRL＋PX4](cases/adrl/README.md) 与 [keyboard](cases/keyboard/README.md) 初版源码；本机静止生命周期与一次 PC keyboard 短起降已通过，RoboPi 未测；其余模块按案例逐步填充。

- [架构与开发边界](ARCHITECTURE.md)
- [迁移路线](docs/roadmap.md) · [验证状态](docs/Validation.md)
- [案例](cases/README.md) · [独立 FastAPI 模型服务](services/README.md)
- [Docker 环境](environments/README.md) · [运行组合](profiles/README.md)
- [GitLab 开发与 GitHub 发布](docs/publishing.md)

模型服务与应用分别部署，通过 HTTP 进程间通信。统一三镜像：uav-computer-builder 同时构建 PC/OHOS，uav-computer 承担 PC Humble 运行，flight_board 承担飞控/仿真/Agent。RoboPi 原生运行 Humble；三个镜像已实际构建，PC/OHOS 编译探针、ADRL 静止/DDS 及新镜像 PC keyboard 起降与短前向输入已通过；RoboPi 运行另行验证。

开发检查（在已安装依赖的环境中执行）：

```sh
uv run python -m unittest discover -s tests
```

## 外部资源

模型、SDK 和场景保持在原位置，不进入 Git，也不需要装配到统一资源目录。多个工作区通过用户级 YAML 共用路径映射。

在 PC 安装开发包：

```sh
uv sync
```

手动创建 `~/.config/leuav/resources.yaml`（设置了 `XDG_CONFIG_HOME` 时使用其下的 `leuav/resources.yaml`）：

```yaml
resources:
  jev_fp8:
    path: ~/models/jev-fp8
  ohos_sdk:
    path: ~/robopi/sdk
```

以上路径仅为示例，须替换为本机实际位置。仓库的 `resources.example.yaml` 可用作模板。

工作区可创建不进入 Git 的 `resources.local.yaml`，按资源名称覆盖用户配置。默认工作区是命令执行目录，也可显式指定；不依赖框架安装位置或向上搜索 Git 根目录。相对路径始终相对于声明它的 YAML 文件，支持 `~`，不展开 shell 环境变量。资源允许为文件或目录。

```sh
uv run leuav resources list
uv run leuav resources check jev_fp8
uv run leuav resources resolve jev_fp8
uv run leuav resources --workspace /path/to/course check ohos_sdk
uv run leuav resources --user-config /path/to/resources.yaml list
```

`list` 展示路径存在状态及配置来源。`resolve` 仅输出已存在资源的绝对路径；`check` 可指定多个名称，省略名称时检查全部已配置资源。缺失、未配置、格式错误时检查命令返回非零退出码；没有任何配置也不会宣称检查通过。

Python 调用方可使用 `leuav.resources.load_resources(workspace)`，得到以资源名称索引的 `path`（Path）和 `source`（配置文件 Path）。解析不代表路径已存在，调用方应按案例检查所需资源。

当前只验证路径存在，不代表模型版本、SDK ABI 或运行链路通过。资源需求、版本、来源、许可和必要文件检查随案例接入补充；用户映射只记录实际路径，不扫描 home、不下载或移动文件。共享资源应作为只读输入；构建、转换和运行产物应另存，并按版本和目标环境隔离。

SSH 中的 GUI 预检、权限处理与复验入口见 [验证流程](docs/ssh-validation.md)。
