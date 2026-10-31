# Humble：统一 builder 与 PC runtime

本目录多阶段 Dockerfile 导出 uav-computer-builder 和 uav-computer。构建命令、依赖基线与探针说明只在 [环境总入口](../README.md) 维护。

builder 复用固定的已验证开发依赖基线。入口 build_target.sh 显式选择 pc/ohos；pc 加载主机 Humble 与消息环境，ohos 要求外部 OHOS_SDK、OHOS_ARCH，保留主机 Python 消息生成路径并清除主机 CMake/ament 前缀，使用独立目标 toolchain。PC 与 OHOS 不共用 build/install。

runtime 从固定的官方 ros-core 派生，仅复制 PC px4_msgs 安装产物，加载自己的 ROS/Python。构建时 check_runtime.py 验证导入、CDR 往返、消息版本以及 GCC/colcon/Agent 不存在。它不复制 builder 中的算法开发库；后续案例按实际依赖闭包增补运行库。

MicroXRCEAgent 构建产物留在 builder，运行产物由 flight_board 提取；runtime 不启动 Agent。宿主机管理 CLI 仍是独立 Python 3.12 项目环境，容器内 ROS 使用自己的 Python；挂载框架代码后追加 PYTHONPATH，不覆盖 ROS 路径。
