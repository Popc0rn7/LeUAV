# Shared PC/OHOS builder. Heavy dependencies remain an explicit, pinned baseline.
ARG BUILDER_BASE=uav-computer-ohos:local
ARG RUNTIME_BASE=ros@sha256:def377f78b58f925e26a2f1f082708d5efed8a602ed43f66449c73618df349a9
FROM ${BUILDER_BASE} AS builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY environments/humble/build_target.sh /opt/leuav/build_target.sh
COPY environments/robopi-cross/toolchain.cmake /opt/leuav/ohos-toolchain.cmake
RUN source /opt/ros/humble/setup.bash \
    && command -v gcc && command -v g++ && command -v cmake && command -v ninja && command -v colcon \
    && python3 -c 'import em, catkin_pkg, lark, ament_package, rosidl_generator_py' \
    && grep -Fx 'px4_msgs=57f88be3c01a8c593c23507e4ca136767115ca22' /opt/uav/sources.txt
LABEL io.leuav.image.role="uav-computer-builder"
WORKDIR /work
ENTRYPOINT ["/bin/bash", "/opt/leuav/build_target.sh"]
CMD ["pc", "/bin/bash"]

FROM ${RUNTIME_BASE} AS computer
COPY --from=builder /opt/px4_ws/install/ /opt/px4_ws/install/
COPY --from=builder /opt/uav/sources.txt /opt/leuav/build-sources.txt
COPY environments/humble/runtime_entrypoint.sh /opt/leuav/runtime_entrypoint.sh
COPY environments/humble/check_runtime.py /opt/leuav/check_runtime.py
RUN /bin/bash -c 'source /opt/ros/humble/setup.bash && source /opt/px4_ws/install/local_setup.bash && python3 /opt/leuav/check_runtime.py'
ENV ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp PYTHONDONTWRITEBYTECODE=1
LABEL io.leuav.image.role="uav-computer"
WORKDIR /work
ENTRYPOINT ["/bin/bash", "/opt/leuav/runtime_entrypoint.sh"]
CMD ["sleep", "infinity"]
