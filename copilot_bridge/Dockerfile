ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-zeroconf

COPY rootfs /

RUN chmod a+x /etc/services.d/copilot_bridge/run
