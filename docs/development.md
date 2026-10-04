# Development

[README](../README.md) · [Architecture](design.md) · [Validation scope](implementation.md)

## Local checks

```bash
uv sync --frozen --python 3.12
uv run pytest -q
uv run ruff check .
node --check webui/static/app.js
node --check dot_plugin/static/approval.js
docker compose --profile dot config --quiet
```

Python dependencies are pinned in `uv.lock` and in `requirements.lock` with hashes. After changing dependencies, synchronize them with:

```bash
uv export --frozen --no-dev --no-emit-project --output-file requirements.lock
```

## Code layout

| Path | Purpose |
| --- | --- |
| `device/` | redroid configuration, login checks, and Iris collector |
| `iris/` | Read-only Iris entry point and license notice |
| `android/` | Registration app and web keyboard, including legacy notification collection code |
| `server/` | Storage, API, stdio MCP, and backups |
| `webui/` | Admin authentication, device control, and static web console |
| `dot_plugin/` | OAuth, remote MCP, and optional Events |
| `ops/`, `bridge` | Host CLI, isolated Lima installation, image updates and encrypted full snapshots |
| `tests/` | Synthetic-data tests and fake devices for browser previews |
| `deploy/`, `scripts/` | Lima, supervisor, installation, diagnostics, and backup tools |

## Preview the web console

Use fixtures that do not connect to ADB or a real account. You need a locally trusted localhost TLS certificate. If your existing installation's certificate is trusted:

```bash
uv run uvicorn tests.webui_preview:create_preview --factory \
  --host 127.0.0.1 --port 19443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

Open `https://localhost:19443/admin/` and use the recovery-key form with `preview-only-key-` followed by 32 zeroes. `/test/calls` shows only the names of actions sent to the fake device. This fixture supports screen controls, login checks, confirmation of both sessions and phone reports. It does not implement Aurora preparation or the private approval service; test those in an isolated stack. Do not validate the UI by installing or resetting approval on a production instance.

That fixture explicitly uses local authentication. For the default passkey UI and MCP approval flow, start the loopback-only fixture:

```bash
uv run python -m tests.passkey_preview
```

In another terminal run `node tests/passkey_browser.cjs`. Set `PLAYWRIGHT_MODULE` to an existing Playwright module path and `CHROME_EXECUTABLE` to a Chromium/Chrome binary if needed. The fixture uses ports 19446 and 19447, a disposable TLS certificate and temporary state. Restart it before each browser run.

The test uses native Chromium WebAuthn with a virtual CTAP2 authenticator: registration, re-login, a remembered session, reload, the same credential across admin/MCP ports, explicit consent, denial, PKCE exchange, refresh rotation and MCP tool discovery. It uses no real account or messages and changes no system trust. Stop the fixture with Ctrl-C afterward. Python tests separately verify actual ES256 signatures and invalid browser, origin, challenge, user verification, RP and user-handle combinations.

## Container checks

```bash
docker compose build api device-agent gateway
./scripts/smoke.sh
uv run python scripts/smoke-ingress.py
```

The smoke test inserts synthetic Iris rows into an isolated `kakaocollector-smoke-PID` project and checks HTTPS authentication, retransmission, persistence, backups, and stdio MCP. It removes only the test project's volumes and uses no real redroid instance or account. The host needs uv or Python 3.12 with dependencies. The default test subnet is `172.29.88.0/24` and the port is `18443`; avoid conflicts with existing deployments.

The ingress smoke test uses disposable Docker networks and an echo server, without production secrets or volumes. It checks private Cookie and Set-Cookie filtering, OAuth cookie preservation, private-path denial, and loopback port publishing. Set `SMOKE_SERVER_IMAGE` and `SMOKE_GATEWAY_IMAGE` when using custom tags.

Docker base images are pinned by digest. The device build runs Bridge's `assembleRelease`, `lintRelease`, and `apksigner verify`, plus Iris's Kotlin tests and `assembleRelease`. Netty versions are aligned by the overlay Gradle configuration, with the resolved report retained in `/opt/iris-dependencies.txt`.

## Contribution guidelines

English is the primary language for documentation and project-owned user interfaces. Keep Korean literals where they identify the supported KakaoTalk UI, and preserve multilingual test data. Document this distinction when describing login checks.

Keep UI explanations focused on status and the next action. Put installation and operations procedures in their respective guides, and protocol and storage details in the architecture and API documentation. Do not append progress logs or troubleshooting attempts to the README.

When changing login or authentication, verify form submission in a real browser as well as unit tests. An Origin header set directly by an HTTP client is not a substitute for browser validation. Do not include tokens, real conversations, or account information in tests or screenshots.

The OAuth approval screen can also be previewed without a real account:

```bash
uv run uvicorn tests.dot_preview:create_preview --factory \
  --host 127.0.0.1 --port 20443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

Enter the same preview key at `https://localhost:20443/test/start` to return to the local callback. State is stored in a temporary directory, without connecting to the collection API or event worker.
