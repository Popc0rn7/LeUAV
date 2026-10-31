#!/usr/bin/env bash
set -euo pipefail
mode="${1:?选择 pc 或 ohos 构建目标}"
shift
# Upstream ROS setup scripts are not nounset-clean.
set +u
source /opt/ros/humble/setup.bash
source /opt/px4_ws/install/local_setup.bash
set -u
export LEUAV_BUILD_TARGET="$mode"
case "$mode" in
  pc)
    ;;
  ohos)
    : "${OHOS_SDK:?显式挂载 OHOS SDK native 根目录并设置 OHOS_SDK}"
    : "${OHOS_ARCH:?显式设置目标架构，例如 arm64-v8a}"
    test -f "$OHOS_SDK/build/cmake/ohos.toolchain.cmake"
    test -x "$OHOS_SDK/llvm/bin/clang"
    export CMAKE_TOOLCHAIN_FILE=/opt/leuav/ohos-toolchain.cmake
    export PATH="$OHOS_SDK/build-tools/cmake/bin:$PATH"
    # Only host Python generator paths remain. Target packages must be explicit.
    unset AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH
    ;;
  *) echo '构建目标只支持 pc / ohos' >&2; exit 2 ;;
esac
if [ "$#" -eq 0 ]; then set -- /bin/bash; fi
exec "$@"
