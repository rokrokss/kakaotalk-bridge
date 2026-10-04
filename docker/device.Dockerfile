# syntax=docker/dockerfile:1
# Android Linux build tools contain x86_64 binaries; the runtime remains native per target.
FROM --platform=linux/amd64 gradle:8.11.1-jdk17@sha256:91d559b8d55f522de5bc6882f73bcedc4e2cc7b0a58e839a9fa0ed95811a988d AS android-build
USER root
ENV ANDROID_HOME=/opt/android-sdk
RUN apt-get update && apt-get install -y --no-install-recommends unzip curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 3 https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -o /tmp/sdk.zip \
    && echo '2d2d50857e4eb553af5a6dc3ad507a17adf43d115264b1afc116f95c92e5e258  /tmp/sdk.zip' | sha256sum -c - \
    && mkdir -p /opt/android-sdk/cmdline-tools \
    && unzip -q /tmp/sdk.zip -d /opt/android-sdk/cmdline-tools \
    && mv /opt/android-sdk/cmdline-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest \
    && rm /tmp/sdk.zip
RUN yes | /opt/android-sdk/cmdline-tools/latest/bin/sdkmanager --licenses >/dev/null
RUN /opt/android-sdk/cmdline-tools/latest/bin/sdkmanager 'platforms;android-35' 'build-tools;35.0.0'
FROM android-build AS iris-build
WORKDIR /iris
RUN curl -fsSL --retry 3 https://codeload.github.com/dolidolih/Iris/tar.gz/ee1dc978ec465df11642596e40f74caff497301d -o /opt/iris-source.tar.gz \
    && echo '1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0  /opt/iris-source.tar.gz' | sha256sum -c - \
    && tar -xzf /opt/iris-source.tar.gz --strip-components=1
RUN mkdir -p app/libs && curl -fsSL --retry 3 https://repo.maven.apache.org/maven2/net/zetetic/sqlcipher-android/4.10.0/sqlcipher-android-4.10.0.aar -o app/libs/sqlcipher.aar \
    && echo 'cc60b1a40d023bec06a1e56740db7172d2516668570140cd9de00ca90f84cd9f  app/libs/sqlcipher.aar' | sha256sum -c -
COPY iris/collector.gradle.kts /iris/collector.gradle.kts
RUN cat collector.gradle.kts >> app/build.gradle.kts
COPY iris/*.kt app/src/main/java/party/qwer/iris/
COPY iris/tests/ app/src/test/java/party/qwer/iris/
RUN --mount=type=cache,target=/root/.gradle,sharing=locked \
    gradle --no-daemon :app:dependencies --configuration releaseRuntimeClasspath > /opt/iris-dependencies.txt \
    && gradle --no-daemon :app:testReleaseUnitTest :app:assembleRelease

FROM android-build AS bridge-build
WORKDIR /src
COPY android/ .
RUN --mount=type=cache,target=/root/.gradle,sharing=locked \
    --mount=type=secret,id=bridge_keystore,required=true \
    --mount=type=secret,id=bridge_key_password,required=true \
    BRIDGE_KEYSTORE=/run/secrets/bridge_keystore BRIDGE_KEY_PASSWORD_FILE=/run/secrets/bridge_key_password \
    gradle --no-daemon :bridge:assembleRelease :bridge:lintRelease \
    && /opt/android-sdk/build-tools/35.0.0/apksigner verify bridge/build/outputs/apk/release/bridge-release.apk

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS web-dependencies
WORKDIR /build
COPY requirements.lock .
COPY docker/build-requirements.txt .
RUN python -m pip install --no-cache-dir --require-hashes -r build-requirements.txt \
    && python -m venv --without-pip /opt/venv \
    && python -m pip --python /opt/venv install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
ARG VCS_REF=development
LABEL org.opencontainers.image.source="https://github.com/rokrokss/kakaotalk-bridge" \
      org.opencontainers.image.revision="${VCS_REF}"
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends adb ca-certificates openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip && rm -rf /usr/local/lib/python3.12/ensurepip
COPY --from=web-dependencies /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/state
WORKDIR /app
COPY device/ device/
COPY server/ server/
COPY webui/ webui/
COPY dot_plugin/ dot_plugin/
COPY --from=android-build /opt/android-sdk/build-tools/35.0.0/lib/apksigner.jar /opt/apksigner.jar
COPY assets/logo.svg assets/
COPY --from=bridge-build /src/bridge/build/outputs/apk/release/bridge-release.apk /opt/bridge.apk
COPY --from=iris-build /iris/app/build/outputs/apk/release/app-release-unsigned.apk /opt/iris.apk
COPY --from=iris-build /opt/iris-source.tar.gz /opt/iris-source.tar.gz
COPY --from=iris-build /opt/iris-dependencies.txt /opt/iris-dependencies.txt
COPY iris/ /opt/iris-overlay/
COPY docker/device.Dockerfile /opt/iris-build.Dockerfile
ENTRYPOINT ["python", "-m", "device.cli"]
CMD ["watch"]
