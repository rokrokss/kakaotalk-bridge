# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS dependencies
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
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip
RUN useradd --uid 10001 --create-home collector && mkdir /data /passkeys && chown collector:collector /data /passkeys
COPY --from=dependencies /opt/venv /opt/venv
WORKDIR /app
COPY server/ server/
COPY dot_plugin/ dot_plugin/
COPY ops/ ops/
COPY assets/logo.svg assets/
USER collector
EXPOSE 8000
CMD ["uvicorn", "server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
