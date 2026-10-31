# SSH 下的仿真验证与权限处理

SSH 是命令入口，GUI 在目标 PC 已登录的本机桌面运行。使用同一用户的实际 DISPLAY 与 Xauthority，先验证授权及 Vulkan，再启动场景。不是通过 SSH X11 转发把 Unreal 渲染到客户端；也不默认 :0。

## 权限处理

| 操作 | 所需访问 | 处理方式 |
| --- | --- | --- |
| 修改 LeUAV 或本机配置 | 对实际目录的写权限 | 若目录在代理沙箱可写范围外，申请该目录写入对应的命令授权 |
| Docker 镜像/容器 | Docker daemon socket | socket/组权限因沙箱不可见时，直接用 require_escalated 重试原能力；不换 socket、不 chmod、不擅自 sudo |
| 读取图形会话、连接 X11、使用 GPU | 同用户桌面认证及相关系统资源 | 通过受批准的沙箱外命令读取会话与授权路径，用 xdpyinfo/Vulkan 核实；不输出 Xauthority cookie，不使用 xhost + |
| 安装 Python 依赖或构建镜像 | 项目产物写入及所需网络 | 明确目标 venv/镜像并申请相应执行授权；不修改主机全局 Python |
| HDC 设备 | 主机工具、连接设备及显式目标 | 先核实版本/设备列表，再按技能预检；无设备则标未测，不重启 server 或改设备模式凑通过 |
| 解锁、起飞、移动 | 明确的仿真控制范围 | 工具授权说明对象、动作和收尾；真实设备另行授权，不能沿用仿真授权 |

代理在 exec_command 中使用 sandbox_permissions=require_escalated，justification 写明动作、对象与原因；可申请范围明确的可复用命令前缀，不申请任意 Python/shell 执行权限。用户已授权的范围持续有效，不用文字反复确认相同事项。工具仍要求执行审批时走审批渠道。

先区分沙箱限制与宿主机本身缺少权限。沙箱外仍被拒绝时，保留错误并说明需要管理员提供的权限，不通过更换工具、改组、放宽目录/显示权限绕过。自动审批拒绝时，明确报告被拒动作与原因，只继续不依赖它的工作。

## 标准预检与静止生命周期

在 LeUAV 根目录、已安装 AirSim extra 且资源/profile 已绑定的环境中执行：

```sh
uv run --no-sync python tools/validate_adrl.py --profile profiles/adrl.local.yaml preflight
uv run --no-sync python tools/validate_adrl.py --profile profiles/adrl.local.yaml lifecycle
```

代理调用这两个命令涉及 Docker/X11 及项目产物写入时，使用已批准的沙箱外执行方式。脚本不能自行获取操作系统或代理权限。

脚本优先读取当前 DISPLAY/XAUTHORITY；SSH 未提供时，仅从同 UID 的已知桌面会话进程中提取三个图形相关变量，要求唯一候选。多会话或无法读取时显式指定：

```sh
uv run --no-sync python tools/validate_adrl.py \
  --profile profiles/adrl.local.yaml \
  --display '<实际 display>' --xauthority '<实际授权文件>' lifecycle
```

不要复制历史机器的 display/授权路径。预检检查 xdpyinfo、Vulkan、本机 Docker 和两张明确镜像。lifecycle 在没有未停止实例时执行 up，先从算力容器订阅真实、时间递增的 PX4 状态，再默认观察至少 15 秒的传感器/定位及 Agent ready、Disarmed、landed，再正常 down 并核实资源无残留。不会开赛、解锁或起飞。失败记录错误并对本轮实例执行限定急停恢复；不接管已有实例。

证据位于 profile output 下 `validation/<UTC时间>/report.json` 与分项日志；实际运行日志仍在 `<run-id>/`。只将结论与索引写入 Validation，不提交原始日志或本机配置。

## 控制验证分层

静止流程通过后，按 [Keyboard 唯一操作入口](../cases/keyboard/README.md) 开赛并运行真实 keyboard/flight。SSH 键盘使用带 PTY 的终端，TERM 必须可供 curses 使用。终端 L/K 是实际输入，不以直接 commander 起降替代键盘链路验收。

分别保留：收到起飞请求、ACK/状态推进、Armed、Position、实际高度/速度、K 降落后的 landed 与 Disarmed、程序退出、正常 down。先做一次短起降；方向输入、失流、完整比赛、重复成功率另行记录，不能从悬停推断通过。

RoboPi 路径先完成 HDC/oh-ros2 必需依赖预检，验证板端加载/序列化及双向 DDS，再运行相同键盘试验。PC 结果不能替代板端结果。
