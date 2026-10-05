# Data and access control

[README](../README.md) · [Operations and backups](operations.md)

This setup assumes a personal server with one owner. Because redroid is a privileged container, run it on a dedicated Linux host or VM. An operator with root ADB access can also access KakaoTalk data and sessions.

## Exposed routes

| Route | Default access | Authentication |
| --- | --- | --- |
| ADB | Host loopback / internal Docker network | Preseeded collector RSA keys (`ro.adb.secure=1`) |
| `/admin/` | Private HTTPS | Passkey login, persistent revocable cookies, Origin and CSRF checks |
| `/v1/*` | Private HTTPS | Read token |
| `/mcp` | Separately configured public HTTPS proxy | OAuth |
| Private tunnel `/mcp` | Docker-internal listener; no published port | Locally injected service credential and owner-approved grant |

The public proxy must connect **only to the dot-ingress port** (`127.0.0.1:18787` by default). Do not bypass this cookie-filtering proxy with a direct dot-plugin route. Do not expose the API gateway or ADB alongside it. Tailscale Funnel provides a public internet address, so OAuth protects MCP access rather than Tailscale user ACLs. The default shared HTTPS origin also serves `/admin/`, protected by passkeys. The admin login page is publicly reachable. To retain a tailnet-only admin in an advanced split-origin deployment, explicitly deny `/admin` and `/admin/*` at the public reverse proxy.

## What is stored?

- Android volume: KakaoTalk login state and the app's message database.
- Collection database: Message bodies, types, identifiers, and timestamps read by Iris; retained for 30 days by default.
- Admin state database: Emergency links and revocable browser sessions; records are encrypted with a key derived from the admin recovery token. Any legacy salted password hash remains for explicit local mode.
- MCP state database: Pending consent requests, OAuth grants, subscriptions, processing cursors, and the webhook queue; values are encrypted with the storage key.
- Passkey database: Encrypted public credentials, RP/origin configuration and short-lived enrollment/verification state. Private keys stay with the authenticator.
- ChatGPT: Messages returned by tools are also sent to ChatGPT.

Compose does not encrypt the Android volume or collection database itself. Use host disk encryption. Collection database backups and full snapshots are encrypted separately.

## Key management

| File | Purpose |
| --- | --- |
| `secrets/admin_token` | Admin recovery and encryption of owner/session state |
| `secrets/read_token` | Collection API queries |
| `secrets/ingest_token`, `secrets/device_token` | Ingestion and device status reports |
| `secrets/mcp_link_key` | Legacy opt-in key approval mode |
| `secrets/mcp_approval_token` | Private admin-to-control requests and passkey-state encryption derivation |
| `secrets/mcp_passkey_token` | Assertion-only public-to-control requests |
| `secrets/mcp_storage_key` | MCP state encryption |
| `secrets/openai_tunnel_api_key` | OpenAI tunnel runtime authentication; mounted only in the tunnel client |
| `secrets/mcp_tunnel_authorization` | Tunnel client to private MCP listener; never accepted as public OAuth |
| `secrets/backup_key` | Database and full-volume snapshot encryption |
| `secrets/bridge.jks`, `secrets/bridge_key_password` | Registration app signing |

`secrets/` has mode 0700; some files use 0444 so container UIDs can read them. Preserve the parent directory's permissions. `.env`, `secrets/`, `inputs/`, `artifacts/`, and `backups/` are excluded from Git and image build inputs.

Do not pass permanent keys through URLs, chats, or command-line arguments. Passkey registration and emergency pairing each use a separate, one-time ten-minute code in a URL fragment, removed by the page immediately. Treat that link as a temporary credential. Do not attach screens containing entered values or real messages to issues. Application logs are configured to omit message bodies and tokens; review diagnostic material before sharing it as well.

## MCP permissions

OAuth validates PKCE S256, exact redirect URIs and resource audiences, and one-time approval records. Access tokens last 30 minutes; refresh grants last 30 days. Detected refresh-token reuse revokes the associated grant.

The plugin receives the API read token and its own OAuth/passkey-assertion secrets, without mounting Android volumes or the admin key. It exposes no message-sending tool. `acknowledge_messages` changes only the plugin's internal processing position. Separate Docker networks restrict it to the read API, assertion endpoints and public ingress. It has no direct container-network connection to admin, the private gateway or Android. The shared ingress does expose authenticated admin routes. Message bodies are external data; do not execute instructions within them as system commands.

## Owner access and connection approval

The optional [personal OpenAI tunnel](openai-tunnel.md) uses a separate internal
listener and an outbound tunnel client. Only the client and listener receive the
local service credential. It is sent in `X-Bridge-Tunnel-Authorization` so
connector-forwarded `Authorization` cannot replace it. Neither container has an
Android or admin/control network connection. The listener has read-API and
passkey-assertion access, and shares encrypted MCP state with the public service.

Approval in the authenticated admin console creates a grant without automatic
expiration, bound to the configured tunnel ID and current passkey policy.
Tools and event operations check
this grant on every request. Revocation, policy changes and tunnel-ID changes
block access; normal restarts retain approval. Older 30-day approvals retain their
expiry until the owner explicitly removes it in admin. Public OAuth grant expiry
is unchanged. Credential-authenticated protocol discovery can succeed
before approval for the official client's startup probe; it exposes schemas and
instructions only. The private listener has no browser OAuth or passkey routes.
The existing public listener continues to require OAuth.

This is a single-owner connection: every caller permitted to use that tunnel by
OpenAI receives the same approved collector access. Bridge cannot determine the
individual OpenAI user. Restrict the tunnel to yourself in OpenAI; shared-workspace
user isolation is not implemented. Admin approval does not subscribe to events.
The existing public service runs the one shared event worker, including for tunnel
grants. Outbound webhook delivery still requires a reachable destination.

[Passkeys](passkeys.md) are the default. Only the server CLI can issue the one-time, ten-minute initial or recovery registration link. Fresh user verification is required to add or remove a key through admin. The public MCP endpoint cannot register an owner.

`dot-control` owns encrypted credentials in `passkey-state`, with an encryption key derived from `mcp_approval_token`. It has no published port. Public `dot-plugin` receives only the separate assertion-only `mcp_passkey_token`; it cannot register, list, remove or configure credentials and has neither the credential volume nor its encryption key.

Each WebAuthn challenge binds the browser, purpose, exact origin and pending OAuth request and can be verified once. Registration and authentication require user verification. Cross-origin/iframe ceremonies are rejected. One passkey works on the shared admin/MCP origin and also across ports of the same hostname. Ports do not isolate cookies.

A successful assertion opens a separate consent page. No MCP code is issued until a same-origin POST explicitly allows the listed permissions. Cancel returns `access_denied`. The client, callback, scope, resource and PKCE challenge remain bound throughout. Client names are self-reported, so the page also shows the client ID and callback origin. The MCP application has no admin routes or admin volume; the separate ingress routes `/admin/*` to the admin service. Admin sessions use a `/admin` cookie. A separate Caddy ingress strips all private admin cookies from requests and private `Set-Cookie` values from responses before forwarding public traffic. Keep this ingress outside the public application container with a read-only configuration. Only ingress and admin join `admin-ingress-net`; ingress never joins the device, API or control networks. Cookie filtering prevents the MCP upstream from receiving or overwriting admin cookies, but the default shared port means both frontends share a browser origin. A compromised frontend or same-origin script can act through a signed-in browser; this setup does not claim browser-origin isolation. Use a separate admin origin and deny admin paths at the public proxy when that isolation is required.

Browser cookie IDs and emergency pairing values are stored as digests. Private session records are encrypted and checked for revocation on every request. Sessions last 30 minutes, or seven days when explicitly remembered; emergency access is limited to 30 minutes. Passwords use salted scrypt only in explicit `ADMIN_AUTH_MODE=local`. Password/key login is disabled in passkey mode.

Removing a credential or completing CLI recovery invalidates passkey sessions and MCP grants. The last credential cannot be removed through the UI. Keep `admin-state` paired with the original admin recovery key and preserve `mcp_approval_token` with `passkey-state`. Do not rotate these encryption inputs by hand.

Kakao OAuth has been removed. Startup deletes its encrypted configuration, pending flows and provider-bound sessions/grants while retaining passkey and local-mode records. Normal source/image updates do not rotate the passkey policy. The October 5 security migration rejects browser sessions created before cookie isolation and requires one admin sign-in; registered passkeys and MCP grants are retained.

Full snapshot restoration verifies AES-GCM before extraction and uses new volumes. It retains passkey credentials but clears pending enrollment, browser sessions, OAuth grants and webhook callbacks. Keep the backup key separately. Restored Android data cannot guarantee Kakao's servers will accept the saved session.

## Security fixes: 2026-10-05

The following records describe the earlier split-port deployment. The shared-port
change exposes authenticated admin routes and changes the browser trust boundary
as described above; historical public-admin 404 results are not its current behavior.

The October 4–5 review found missing Iris caller authentication, a conditional public-to-admin escalation path, anonymous OAuth registration exhaustion, outdated dependencies and Android patch debt. Application fixes and dependency updates are deployed on the existing ARM64 Lima host. **Android patch debt remains unresolved.** This was a bounded review, not evidence that every possible vulnerability has been found.

| Finding | Applied change | Verification |
| --- | --- | --- |
| Iris data readable without caller authentication | Per-enrollment random bearer in a root-only Android file; authenticate before database access. A nonce/HMAC challenge verifies the listener before sending the credential. | Missing/bad bearer and Android UID 2000 return 401; authenticated empty-page read succeeds; UID 2000 cannot read the secret |
| Public process could capture admin cookies and reach device controls | Separate API-read, assertion and private-control networks; `/admin` session cookie; old browser sessions rejected; separate public ingress filters private cookies in both directions and blocks private routes | Direct private IP/DNS probes fail; synthetic ingress tests cover duplicate Cookie headers and preserve OAuth cookies; old session replay rejected |
| Unauthenticated root ADB on the Android network | `adb-init` seeds only the two collector public keys offline; enable `ro.adb.secure=1`; private keys remain in their original volumes | A disposable Android instance accepted both seeded keys and rejected an unseeded client; production handshake requires AUTH |
| Anonymous DCR fills persistent client quota | Short-lived encrypted registration tickets, persisted only after owner consent; atomic quota check for approved clients | 150 anonymous registrations create no stored clients; expired/tampered tickets fail; approved and legacy clients still work |
| Vulnerable dependency versions | Aligned Netty `4.1.138.Final`, Caddy `2.11.7`, distribution updates; current pinned pip in build stage, no pip/ensurepip in runtime | Retained Gradle report, OSV and final image scans; see scope below |
| Unbounded container process/memory usage | Explicit memory and PID limits for application services and both proxies | Effective Compose/container configuration checked |

Implementation: [Iris authentication](../iris/CollectorAuth.kt), [credential provisioning](../device/iris.py), [ADB initialization](../device/adb_auth.py), [network boundaries](../compose.yaml), [public proxy](../docker/Caddyfile.public), [admin sessions](../webui/app.py), [OAuth registration](../dot_plugin/auth.py).

The public process still holds the API read token because reading messages is its purpose. If that process is compromised, the messages available to that token are exposed. These changes restrict escalation to administration; they cannot make a compromised authorized reader harmless. A compromised ingress, host/root operator, passkey device or privileged Android instance also remains inside a relevant trust boundary.

### Dependency results and remaining Android risk

Final images are `server:security-20261005-r2`, `device:security-20261005-r2` and `gateway:security-20261005` under `kakaotalk-collector/`. Grype 0.120.0 used its valid `2026-10-04T08:11:47Z` database. Raw package/advisory matches changed from 289 → 276 for server, 370 → 357 for device, and 213 → 5 for Caddy. **No High/Critical match with an available distribution fix remained in those three images.** Raw counts include unused features and repeated advisories; they are not counts of exploitable application paths. Unfixed/distribution-accepted matches and Medium Python runtime matches remain; their applicability has not been exhaustively reviewed. Redroid is not included in this three-image result.

All 14 resolved Netty modules are aligned to `4.1.138.Final`; individual OSV queries returned no advisories for that version on this date. The retained `/opt/iris-dependencies.txt` records the resolved Gradle dependency graph. The [Netty release](https://github.com/netty/netty/releases/tag/netty-4.1.138.Final) and [Caddy 2.11.7 release](https://github.com/caddyserver/caddy/releases/tag/v2.11.7) replace versions flagged during the review. Official-library Caddy image publication lagged the HTTP/2 fix, so the gateway Dockerfile verifies the official release binary's SHA-512 before copying it into the updated image.

The deployed Redroid Android 14 image still reports security patch `2024-05-05`, userdebug and disabled SELinux, and requires a privileged container. Enabling authenticated ADB removes an exposed root entry point; it does not patch the Android OS. Inspected official Android 15 and 16 images report `2024-11-05` and `2025-06-05`, respectively, so moving to a higher Android version alone would not bring security patches current. The logged-in Android data was not migrated to an unverified major version. Resolving this requires a maintained, security-patched compatible build and a separate migration test; it remains open.

Run this workload in its dedicated VM without host directory or Docker socket mounts, install no unrelated Android applications, and keep host disk encryption enabled. The inspected Lima deployment has no host-directory mounts and the Mac has FileVault enabled. These controls reduce exposure; they do not repair missing Android patches. The review did not attempt a malicious APK, kernel exploitation, destructive load testing or exhaustive native-code analysis.

### Verification record

Commands run from the repository root:

| Command/check | Actual result |
| --- | --- |
| `uv run pytest -q` | `227 passed, 1 warning` (Starlette test-client deprecation) |
| `uv run ruff check .` | `All checks passed!` |
| Device image build | Bridge release checks, Iris Kotlin tests and APK build passed; resolved Netty report retained |
| `SMOKE_SERVER_IMAGE=kakaotalk-collector/server:security-20261005-r2 SMOKE_GATEWAY_IMAGE=kakaotalk-collector/gateway:security-20261005 uv run python scripts/smoke-ingress.py` | 15 cookie cases, 5 denied private paths; private request/response cookie values removed, OAuth cookies retained; published loopback port tested |
| `node tests/passkey_browser.cjs` with bundled Playwright and Chrome | Native virtual-authenticator registration/login, scoped seven-day session, same passkey on both ports, explicit consent, PKCE, refresh, MCP discovery, denial and code replay rejection passed |
| `grype docker:<final-image> -o json --file <report>` for the three images | Counts and limits above; reports retained locally |
| Production read-only checks | Iris missing/bad credentials return 401; authenticated empty page succeeds; untrusted ADB requires AUTH; direct public-to-private network probes fail; public admin routes return 404 and unauthenticated MCP returns 401 |
| Existing connected MCP `get_profile` and `get_collector_status` | Both succeeded after deployment; `collecting_partial`, Iris connected, no warnings, no pending deliveries |

Raw reports, build output and deployment checks are retained in ignored `artifacts/security-fix-20261005/`. Probes did not request message bodies, send messages, change acknowledgments or create event subscriptions. Browser and ADB negative tests used synthetic data/disposable Android volumes.

Before migration, a full AES-GCM snapshot including Android, all seven state volumes, configuration and secrets was authenticated without extracting plaintext. It is kept on the deployment host at `backups/security-20261005-r1/snapshot.kcs` with mode 0600. The initial backup verification hit a permissions error before service changes; the corrected retry passed. Both Iris migrations checked old/new APK hashes and retained the prior binary. Passkey identities, MCP grants and profile identity were compared before and after. Secure ADB required one Android restart; the final dependency/ingress rollout did not restart Android. The owner must sign in to admin once again with the existing passkey. Phone session continuity still requires the owner's manual check.

The first ingress rollout briefly returned 502: its copied configuration had mode 0600, and Docker did not publish ports when its only network was internal. The configuration is now readable by its non-root UID, with private writable tmpfs directories. A separate edge network enables host-loopback publishing without joining any admin/device/control network. A health check and an actual published-port smoke test cover this deployment failure; final public-route and existing MCP calls passed.
