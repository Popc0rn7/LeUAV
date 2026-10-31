# Reuse verified images: extract Agent runtime, then extend PX4/Gazebo only.
ARG AGENT_IMAGE=uav-computer-builder:local
ARG PX4_IMAGE=px4io/px4-sitl-gazebo@sha256:54a7a15ba35b3f4786256296d89edd144e000f40084cb6ed692fcbf74c9168f2
FROM ${AGENT_IMAGE} AS agent
ARG XRCE_AGENT_COMMIT=57d086216d01ec43121845d385894a25987f8a2c
COPY environments/flight_board/collect_agent.py /tmp/collect_agent.py
RUN grep -Fx "xrce_agent=${XRCE_AGENT_COMMIT}" /opt/uav/sources.txt \
    && /bin/bash -c 'source /opt/ros/humble/setup.bash && python3 /tmp/collect_agent.py'

FROM ${PX4_IMAGE}
COPY --from=agent /opt/flight-board/ /opt/flight-board/
COPY src/leuav/contracts/fastdds_udp.xml /opt/flight-board/fastdds.xml
COPY environments/flight_board/supervisor.py /opt/flight-board/supervisor.py
COPY src/leuav/flight/px4/px4_start.sh /opt/flight-board/px4_start.sh
# Private LD_LIBRARY_PATH is used only by Agent, never by PX4/Gazebo.
RUN test -x /opt/px4-gazebo/bin/px4 \
    && command -v python3 \
    && LD_LIBRARY_PATH=/opt/flight-board/lib ldd /opt/flight-board/bin/MicroXRCEAgent > /opt/flight-board/target-ldd.txt \
    && ! grep -q 'not found' /opt/flight-board/target-ldd.txt
LABEL io.leuav.flight-board.version="1"
HEALTHCHECK --interval=5s --timeout=3s --start-period=15s --retries=3 \
    CMD python3 /opt/flight-board/supervisor.py healthcheck
ENTRYPOINT ["python3", "/opt/flight-board/supervisor.py"]
CMD ["run", "/bin/bash", "/opt/flight-board/px4_start.sh"]
