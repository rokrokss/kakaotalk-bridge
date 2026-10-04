# Validation scope

[Development and test commands](development.md) · [Current architecture](design.md)

## Verified with a real account

On 2026-10-04, using Lima/Ubuntu 24.04 arm64 on an Apple Silicon Mac:

- redroid boot with Android 14, SM-T970 tablet configuration, and 1200 × 1920 resolution at density 240.
- Screen viewing, control, and Korean text input through the web admin console.
- KakaoTalk secondary-device option check (“다른 기기와 함께 사용”, meaning “Use with other devices”) and secondary login.
- Phone session continuity, manually confirmed by the user on the phone; this was not an automated server check.
- Iris database row storage and collection of new messages sent to self after approval.
- State volume persistence across container and VM restarts.
- Public HTTPS OAuth flow and successful connection of `KakaoTalk Bridge` in ChatGPT.

## Automated checks

Python tests use synthetic data to cover authentication, CSRF, Origin, login approval conditions, database deduplication, cursors, restores, MCP queries, and event retries, revocation, and expiry. Docker smoke tests cover the API, gateway, stdio MCP, SQLite, and encrypted backups.

Image builds and API startup have been verified on amd64. This does not establish redroid or KakaoTalk compatibility on an amd64 host. Reproduction commands are in [Development](development.md).

## Onboarding changes (2026-10-04)

The new owner login, setup guide, private connection approval, installer and snapshot commands were checked separately from the real-account deployment:

- Python regression tests cover one-use/expired pairing, password authentication, restart persistence, CSRF, session revocation, private approval, PKCE, setup preservation, signature rejection and authenticated snapshot restoration.
- Both server and device images built successfully on Docker Desktop arm64. Bridge release lint and APK signature verification passed during the device build.
- A separate Docker Compose project with synthetic credentials passed HTTPS pairing, an admin restart, private approval, OAuth token exchange, MCP access, grant revocation and browser revocation. Public control paths returned 404.
- A full snapshot of the synthetic Docker volumes was encrypted and restored into new volumes; existing volumes were retained. The test also exposed and fixed unsupported xattrs on Docker Desktop host binds.
- The device image verified the publisher certificate of the previously downloaded official KakaoTalk APK.
- The setup guide and access-management layout were checked in a browser using an HTTP mock preview. The real HTTPS browser flow was not exercised for these changes because the test CA is not trusted by that browser; backend HTTPS tests explicitly trusted only the test certificate.

Before committing these changes, `uv run pytest -q` reported **152 passed** with one Starlette TestClient deprecation warning, and `uv run ruff check .` reported **All checks passed!** Both JavaScript entry points passed `node --check`; `docker compose --profile dot config --quiet` and `git diff --check` also passed. The suite includes the canonical release image namespace and reuse of the saved private Tailscale URL on Linux.

These checks did not update the signed-in redroid instance or repeat account login. Fresh Lima installation through the new CLI, the newly scripted Korean-locale preparation, both architectures of the release workflow, Tailscale route setup and published release downloads still require integration validation. The earlier manual Aurora/Korean-secondary-option check is separate evidence, not a complete installer test. Passkeys and Tailscale identity sign-in remain future work.

## Not yet verified

Compatibility with other KakaoTalk versions and hosts, completeness of conversation history, end-to-end comparison of read status before and after collection, and 24–72 hours of continuous reception require further validation. Actual Dot event execution has not been verified, and automatic subscription is not a requirement.

Details of the initial notification-based MVP and troubleshooting history remain in Git. Refer to [Iris](iris.md), [Admin console](web-ui.md), and [MCP](dot-plugin.md) for current behavior.
