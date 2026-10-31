# 统一 builder 的 OHOS 目标

不建立第四个镜像。uav-computer-builder 同时支持 PC 和 OHOS，入口显式选择目标；基础镜像构建与探针命令见 [环境总入口](../README.md)。

SDK native 根目录通过资源 ohos_sdk 定位，容器内只读挂载并设置 OHOS_SDK；架构通过 OHOS_ARCH 显式选择。toolchain.cmake 加载 SDK 官方 toolchain，对目标库、头文件和 CMake 包限定目标搜索；主机程序搜索仍用于生成工具。实际算法需要目标 ROS/第三方安装前缀时显式提供 OHOS_TARGET_PREFIX，并按其 ABI/消息版本核实依赖闭包。

本轮 C++ 探针验证宿主机工具可用、SDK Clang 交叉编译链接和 AArch64 ELF 生成；未执行板端 ELF，也不代表目标 ROS 包、Python 扩展或真实 DDS 已通过。RoboPi 原生运行 Humble，不需要 Docker。SDK、依赖快照、构建产物保持仓库外或忽略目录；不复用 PC install 上板。
