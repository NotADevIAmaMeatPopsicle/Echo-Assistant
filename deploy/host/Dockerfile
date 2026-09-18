FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS speech
COPY config/tts-linux.lock.txt /tmp/tts-runtime.lock.txt
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/tts-runtime.lock.txt

FROM rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9 AS receiver
RUN apt-get update && apt-get install -y --no-install-recommends python3 pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY tools/build_receiver.py tools/receiver_events.rs /build/tools/
COPY native/librespot-0.8.0.crate /build/local/runtime/librespot-0.8.0.crate
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/build/local/runtime/receiver-target python3 tools/build_receiver.py && cp local/runtime/receiver-target/release/librespot /usr/local/bin/echo-librespot

FROM python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS aec
RUN apt-get update && apt-get install -y --no-install-recommends build-essential pkg-config swig meson ninja-build && rm -rf /var/lib/apt/lists/*
RUN python -m pip install setuptools==80.9.0 wheel==0.45.1
COPY native/aec_audio_processing-1.0.1.tar.gz deploy/host/build_aec.py /build/
RUN python /build/build_aec.py

FROM python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libsndfile1 espeak-ng ca-certificates && rm -rf /var/lib/apt/lists/*
COPY config/host-linux.lock.txt /tmp/host-linux.lock.txt
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r /tmp/host-linux.lock.txt
COPY --from=aec /wheels /tmp/aec-wheels
RUN python -m pip install --no-deps --no-index /tmp/aec-wheels/*.whl && python -c "from aec_audio_processing import AudioProcessor; AudioProcessor(enable_aec=True)"
COPY --from=receiver /usr/local/bin/echo-librespot /usr/local/bin/echo-librespot
COPY --from=speech /usr/local /opt/python312
WORKDIR /opt/echo
COPY backend /opt/echo/backend
COPY web /opt/echo/web
COPY config/tts-models.json /opt/echo/config/tts-models.json
COPY tools /opt/echo/tools
COPY deploy/host/bootstrap.py /opt/echo/deploy/host/bootstrap.py
COPY --from=receiver /build/third_party/licenses/librespot-MIT.txt /opt/echo/third_party/licenses/librespot-MIT.txt
COPY --from=aec /build/source/aec_audio_processing-1.0.1/LICENSE /opt/echo/third_party/licenses/aec-audio-processing-BSD.txt
COPY --from=aec /build/source/aec_audio_processing-1.0.1/webrtc-audio-processing/COPYING /opt/echo/third_party/licenses/webrtc-COPYING.txt
COPY --from=aec /build/source/aec_audio_processing-1.0.1/webrtc-audio-processing/webrtc/LICENSE /opt/echo/third_party/licenses/webrtc-LICENSE.txt
COPY --from=aec /build/source/aec_audio_processing-1.0.1/webrtc-audio-processing/webrtc/PATENTS /opt/echo/third_party/licenses/webrtc-PATENTS.txt
COPY --from=aec /build/source/aec_audio_processing-1.0.1/webrtc-audio-processing/subprojects/abseil-cpp-20240722.0/LICENSE /opt/echo/third_party/licenses/abseil-Apache-2.0.txt
RUN useradd --uid 10000 --create-home echo && mkdir -p local /run/echo && chown -R 10000:10000 local /run/echo
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ECHO_CONTAINER=1 ECHO_DEPLOYMENT_MODE=validation ECHO_STORAGE_KEY_FILE=/run/echo/storage.key ECHO_HOME_TOOLS_TOKEN_FILE=/run/echo/home-tools-token ECHO_TTS_PYTHON=/opt/python312/bin/python3.12 ECHO_TTS_HOME=/opt/python312 ECHO_AEC_PYTHON=/usr/local/bin/python ECHO_RECEIVER_BINARY=/usr/local/bin/echo-librespot
USER 10000:10000
CMD ["python", "deploy/host/bootstrap.py"]
