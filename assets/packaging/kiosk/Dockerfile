# syntax=docker/dockerfile:1
FROM debian:trixie-slim AS image-tools
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates sudo binfmt-support qemu-user-static novnc \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v2.9.0 https://github.com/raspberrypi/rpi-image-gen.git /opt/image-gen \
    && test "$(git -C /opt/image-gen rev-parse HEAD)" = d2d5705bcb37284c4b08c0ce43c039b1f1004e25 \
    && apt-get update && /opt/image-gen/install_deps.sh

FROM --platform=linux/arm64 debian:trixie-slim AS application
ENV DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1 MAKEFLAGS=-j2
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-dev python3-venv build-essential pkg-config gettext \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libgl1-mesa-dev libgles2-mesa-dev libegl1-mesa-dev libgbm-dev libdrm-dev \
    libwayland-dev libxkbcommon-dev libmtdev-dev libhidapi-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /buildenv \
    && /buildenv/bin/pip install poetry==2.1.3 poetry-plugin-export==1.9.0 build==1.2.2.post1
ENV PATH=/buildenv/bin:$PATH
WORKDIR /src
COPY pyproject.toml poetry.lock ./
RUN poetry export --only main --without-hashes -o /requirements.txt \
    && pip wheel --no-binary=kivy --wheel-dir=/output/wheels -r /requirements.txt
COPY . .
ARG KIOSK_VERSION
ARG KIOSK_COMMIT
RUN python assets/packaging/kiosk/build_bundle.py "${KIOSK_VERSION}" "${KIOSK_COMMIT}" /output

FROM image-tools AS image
COPY assets/packaging/kiosk /project/kiosk
COPY --from=application /output /project/kiosk/payload
COPY scripts/kiosk.py /project/kiosk/kiosk.py
COPY carveracontroller/kiosk_state.py carveracontroller/runtime_profile.py carveracontroller/kiosk_touch.py /project/kiosk/runtime/
RUN chmod +x /project/kiosk/build-image.sh
ENTRYPOINT ["/project/kiosk/build-image.sh"]
