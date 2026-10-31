#!/usr/bin/env bash
# Docker：外部 AirSim 的 PX4 SITL 入口，无 Gazebo。
set -euo pipefail
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:?由运行配置传入 ROS_DOMAIN_ID}"
test -x /opt/px4-gazebo/bin/px4-simulator_mavlink
test -f /opt/px4-gazebo/etc/init.d-posix/airframes/10016_none_iris
export PX4_SIM_MODEL=none_iris PX4_SYS_AUTOSTART=10016
unset PX4_SIMULATOR PX4_SIM_HOST_ADDR PX4_SIM_HOSTNAME
mkdir -p /tmp/airsim-px4/fs /flight-logs
cd /tmp/airsim-px4
ln -s /opt/px4-gazebo/etc etc
ln -s /flight-logs fs/log
# Stage 1 基线（SITL 无 GCS／无电池传感器）：
# - 没有 QGC 时 PX4 收不到 MAVLink 心跳，默认数据链丢失会 "Hold 5s → RTL"，
#   failsafe 期间拒绝切 POSCTL，正是 flight 收到 DO_SET_MODE(176) result=1 的原因；
# - rcS 在 SIM_BAT_DRAIN>0 时启动 battery_simulator，AirSim HIL 下电压读数无效，
#   commander 会按低电 failsafe 处理，arm 后被自动 disarm 或切 Hold。
# - rcS 默认 SYS_FAILURE_EN=1，SITL 的失败注入（电池/GPS/RC）会让 PX4 在起飞阶段
#   反复进入 failsafe 或内部 disarm；基线里直接关掉失败注入模块。
# 其余参数关掉电量门槛、数据链失效动作，并启用标准键盘/摇杆手动输入（COM_RC_IN_MODE=1）。
# QGC 当次仍可临时覆盖这些参数；下一次 up 回到这份基线。
battery='param set SIM_BAT_DRAIN 0\nparam set SIM_BAT_MIN_PCT 100\nparam set BAT1_SOURCE 0'
failure='param set SYS_FAILURE_EN 0'
late='param set COM_ARM_BAT_MIN 0\nparam set COM_LOW_BAT_ACT 0\nparam set NAV_DLL_ACT 0\nparam set COM_RC_IN_MODE 1\nparam set COM_RC_LOSS_T 5\nparam set COM_DLL_EXCEPT 4\nparam set COM_OBL_RC_ACT 4\nparam set COM_OF_LOSS_T 0.5\nparam set SYS_FAIL_BAT_LVL 0\nparam set SYS_FAIL_GPS_WRG 0\nparam set SYS_FAIL_RC_INST 0\nparam set SYS_FAIL_RC_UNIT 0\nparam set SYS_FAIL_RC_MODE 0\nparam set SYS_FAIL_RC_SRC 0'
if [[ ${AIRSIM_SUPER:-0} == 1 ]]; then
  # PX4 HIL clock is authoritative; DDS must not translate it to the Agent wall clock.
  late='param set UXRCE_DDS_SYNCT 0\n'${late}'\nparam set COM_RC_IN_MODE 4'
fi
sed "/^if param compare SYS_FAILURE_EN 1/i ${failure}" \
  /opt/px4-gazebo/etc/init.d-posix/rcS | \
  sed "/^if param greater SIM_BAT_DRAIN 0/i ${battery}" | \
  sed "/^uxrce_dds_client start/i ${late}" > /tmp/airsim-rcS
exec /opt/px4-gazebo/bin/px4 -d -s /tmp/airsim-rcS
