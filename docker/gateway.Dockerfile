# syntax=docker/dockerfile:1
# Official-library images lag the 2.11.7 fix for the 2.11.6 HTTP/2 proxy panic.
FROM --platform=$BUILDPLATFORM caddy:2.11.6-alpine@sha256:c776e0c6413b544d0459665e54ec7b8b2a15000c0cbee8b254da0067b1d184ff AS download
ARG TARGETARCH
RUN case "$TARGETARCH" in \
      amd64) checksum=a7a433a1b133efc3c8d10eb0b99d52a24b5ef5c322dc77f5282182b1c0402139ab83f3a99f0c52409df77d20123fb0b523edad8a66d8f5e49136197bf61ef0e7 ;; \
      arm64) checksum=3db36ba90c7a6e8dda40ee3dd71fa08844c76b5fb08f61b31e5e78d2ed38e71c51dc7baed875e50d1ca1279196e84302967237386ae87c91ae9f2aaceada682e ;; \
      *) exit 1 ;; \
    esac \
    && wget -q "https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_linux_${TARGETARCH}.tar.gz" -O /tmp/caddy.tar.gz \
    && echo "$checksum  /tmp/caddy.tar.gz" | sha512sum -c - \
    && mkdir /out && tar -xzf /tmp/caddy.tar.gz -C /out caddy

FROM caddy:2.11.6-alpine@sha256:c776e0c6413b544d0459665e54ec7b8b2a15000c0cbee8b254da0067b1d184ff
RUN apk upgrade --no-cache
COPY --from=download /out/caddy /usr/bin/caddy
