# Build on the host; keep compiler caches off the Pi SD card.
FROM rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9 AS build
RUN apt-get update && apt-get install -y --no-install-recommends python3 gcc-aarch64-linux-gnu libc6-dev-arm64-cross && rm -rf /var/lib/apt/lists/*
RUN rustup target add aarch64-unknown-linux-gnu
ENV CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc
WORKDIR /build
COPY tools/build_receiver.py tools/receiver_events.rs /build/tools/
COPY local/runtime/librespot-0.8.0.crate /build/local/runtime/librespot-0.8.0.crate
RUN --mount=type=cache,target=/usr/local/cargo/registry --mount=type=cache,target=/build/local/runtime/receiver-target python3 tools/build_receiver.py --pi && cp local/runtime/receiver-target/aarch64-unknown-linux-gnu/release/librespot /build/echo-librespot
FROM scratch
COPY --from=build /build/echo-librespot /echo-librespot
COPY --from=build /build/third_party/licenses/librespot-MIT.txt /librespot-MIT.txt
