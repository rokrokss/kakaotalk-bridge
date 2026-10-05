# Development

[README](../README.md) · [Architecture](design.md) · [Validation scope](implementation.md)

## Local checks

```bash
uv sync --frozen --python 3.12
uv run pytest -q
uv run ruff check .
node --check webui/static/app.js
node --check webui/static/connection-setup.js
node --test tests/setup-flow.test.cjs tests/connection-guidance.test.cjs
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
| `install.sh`, `install.ps1`, `ops/onboarding.py` | One-command launch, dependency preparation and resumable setup |
| `ops/setup_agent.py`, `server/connection_setup.py`, `webui/setup.py` | Private host setup jobs, shared input validation and authenticated admin proxy |
| `webui/static/connection-setup.js` | Destination/method selection, saved instructions, progress and retry UI |
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

## Connection setup and overview checks

```bash
uv run pytest -q tests/test_web_connection_setup.py tests/test_connection_setup.py tests/test_tunnel.py tests/test_event_settings.py
node --test tests/connection-guidance.test.cjs tests/setup-flow.test.cjs
```

These cover the setup input boundary, job/credential handling, saved method
selection, progress isolation, persistent instructions, tunnel approval and
successful-call activity, and conversation event permissions. The pure JavaScript
guidance tests do not replace browser interaction checks.

For UI changes, use synthetic providers in an isolated fixture and verify:

- A configured, approved connection without recorded activity awaits its first
  successful tool call; a service check does not create one.
- Saved instructions survive checks, failures and reloads; an interrupted job
  reopens for review, and retry allows settings to be corrected.
- HTTPS `/mcp` input normalizes to the origin; credentials clear from the form.
- Stale inspection preserves the last-observed approval label and explains how
  to enable dependent phone-confirmation actions.
- A running collector starts with setup/tablet folded. At a 390-pixel viewport,
  navigation and controls remain reachable without horizontal overflow.
- Event permission and subscription status remain distinct; do not create real
  subscriptions merely to test layout.

On an authorized real deployment, check existing authentication, run **Check
server connection**, make a successful MCP status call and verify its timestamp.
Do not equate this with a fresh install or a full provider onboarding test. The
latest [validation scope](implementation.md#admin-ux-and-connection-setup-2026-10-05)
separates real checks from synthetic ones.

## Container checks

```bash
docker compose build api device-agent gateway
./scripts/smoke.sh
uv run python scripts/smoke-ingress.py
```

The smoke test inserts synthetic Iris rows into an isolated `kakaocollector-smoke-PID` project and checks HTTPS authentication, retransmission, persistence, backups, and stdio MCP. It removes only the test project's volumes and uses no real redroid instance or account. The host needs uv or Python 3.12 with dependencies. The default test subnet is `172.29.88.0/24` and the port is `18443`; avoid conflicts with existing deployments.

The ingress smoke test uses disposable Docker networks and an echo server, without production secrets or volumes. It checks private Cookie and Set-Cookie filtering, OAuth cookie preservation, shared admin/MCP routing, internal-path denial, and loopback port publishing. Set `SMOKE_SERVER_IMAGE` and `SMOKE_GATEWAY_IMAGE` when using custom tags.

Docker base images are pinned by digest. The device build runs Bridge's `assembleRelease`, `lintRelease`, and `apksigner verify`, plus Iris's Kotlin tests and `assembleRelease`. Netty versions are aligned by the overlay Gradle configuration, with the resolved report retained in `/opt/iris-dependencies.txt`.

ARM source builds run a probe in the pinned amd64 Android build image before
compilation. If the registered emulator fails, Bridge replaces only the
`qemu-x86_64` handler using a digest-pinned `tonistiigi/binfmt` image and reruns the
probe. This addresses a fresh Ubuntu VM failure where QEMU crashed in `cmp` and
APT reported unsupported keyring files. It requires privileged Docker access;
release-image installs and native runtime containers do not need this build step.
The pinned emulator comes from the [Lima multi-architecture guide](https://lima-vm.io/docs/config/multi-arch/).


## Contribution guidelines

English is the primary language for documentation and project-owned user interfaces. Keep Korean literals where they identify the supported KakaoTalk UI, and preserve multilingual test data. Document this distinction when describing login checks.

Keep UI explanations focused on status and the next action. Put installation and operations procedures in their respective guides, and protocol and storage details in the architecture and API documentation. Do not append progress logs or troubleshooting attempts to the README.

For automatic onboarding, start `uv run python -m tests.setup_preview`, then run
`node tests/setup-browser.cjs` with the same `PLAYWRIGHT_MODULE` and
`CHROME_EXECUTABLE` options described above. This fixture uses port 19449 and
synthetic store/device state. It verifies preparation, detection of store
installation, automatic component setup, the manual login-confirmation boundary
and reload without reinstalling. It never launches a real VM or signs in to KakaoTalk.

When changing login or authentication, verify form submission in a real browser as well as unit tests. An Origin header set directly by an HTTP client is not a substitute for browser validation. Do not include tokens, real conversations, or account information in tests or screenshots.

The OAuth approval screen can also be previewed without a real account:

```bash
uv run uvicorn tests.dot_preview:create_preview --factory \
  --host 127.0.0.1 --port 20443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

Enter the same preview key at `https://localhost:20443/test/start` to return to the local callback. State is stored in a temporary directory, without connecting to the collection API or event worker.
