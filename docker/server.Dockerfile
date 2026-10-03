# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3 AS dependencies
WORKDIR /build
COPY requirements.lock .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3
ARG VCS_REF=development
LABEL org.opencontainers.image.source="https://github.com/rokrokss/kakaotalk-mcp-events" \
      org.opencontainers.image.revision="${VCS_REF}"
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home collector && mkdir /data && chown collector:collector /data
COPY --from=dependencies /opt/venv /opt/venv
WORKDIR /app
COPY server/ server/
COPY dot_plugin/ dot_plugin/
USER collector
EXPOSE 8000
CMD ["uvicorn", "server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
