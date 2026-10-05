# Passkey sign-in

Passkeys authenticate admin and MCP connection approvals without a Kakao Developers app or a hosted identity broker. The tablet still needs its normal KakaoTalk login. Passkeys are the default for admin and MCP approvals. Kakao OAuth is no longer supported.

## Set up

New installs use `http://localhost:18789` (Mac can choose another free port). On a remote server use [SSH forwarding](quickstart.md#local-and-ssh-admin-access). No certificate or Tailscale account is needed for localhost. Existing HTTPS origins are retained.

For shared HTTPS admin and MCP, choose one stable hostname before registration. For example, use `https://your-node.ts.net/admin/` and `https://your-node.ts.net/mcp` through Funnel on the same HTTPS port 443. Run `./bridge expose` or configure the reverse proxies yourself. Never publish the admin gateway through Funnel.

A trusted certificate and the same hostname let one passkey work on both ports. A passkey registered on `localhost` cannot be used at your public hostname. Setup rejects IP addresses and non-local HTTP. If admin and MCP use different hosts, web/CLI connection setup keeps the admin passkey and configures code approval in admin instead of public passkey login.

Route public traffic through `dot-ingress`, never directly to `dot-plugin`. The shared ingress forwards admin routes to the authenticated admin service and removes admin cookies from requests and responses on OAuth/MCP routes. Its dedicated admin network does not connect the public MCP process to admin. Both web applications share a browser origin; this is not browser-origin isolation.

Update the checkout and images to a version that includes passkeys, then run:

```bash
./bridge passkey-login --url https://your-node.ts.net --public-url https://your-node.ts.net
```

The command starts the private authentication service, enables passkey mode, and opens a one-use registration link that expires in ten minutes. On a headless server it prints the link. Keep the link private. Open it on your computer or phone and choose **Create a passkey**. Your device or password manager asks you to unlock it; the server receives the credential's public key.

The public MCP endpoint cannot register an owner. A fresh installation can only be claimed using the link issued by the server CLI.

## Use

Bookmark the configured admin address. Choose **Sign in with a passkey** when asked. **Keep me signed in** creates a revocable seven-day session; otherwise it lasts thirty minutes. The headless server needs no fingerprint reader: the browser's device, phone or security key performs authentication.

Add the public `/mcp` URL to your MCP client with OAuth authentication. For a shared HTTPS hostname, confirm with your passkey, inspect the client and permissions, then choose **Allow connection**. For localhost/private admin, match the connecting browser’s code in admin **AI connections** and approve there. Cancelling issues no authorization code. PKCE, refresh-token rotation, revocation and explicit event-subscription rules remain in place.

Some embedded browsers do not support third-party passkeys. Restart the connection in a supported system browser. Copying a partially completed approval URL to another browser does not transfer the browser-bound request.

## Recover

In admin, open **Tablet & settings → Passkeys and recovery** and add a passkey on another device or security key. Adding or removing a credential requires fresh passkey confirmation. At least one credential must remain. Removing a credential invalidates existing passkey admin sessions and MCP grants; reconnect clients afterward.

If every passkey is unavailable, run this on the server:

```bash
./bridge passkey-login --enroll
```

Register a replacement using the new one-use link. Successful recovery invalidates old sessions and grants. Remove the missing device's credential afterward. Old credentials remain registered until explicitly removed.

Full encrypted snapshots include `passkey-state`. Restore retains registered keys and clears pending enrollment links, challenges, reauthentication proofs, browser sessions and OAuth grants. Keep the hostname stable and preserve `mcp_approval_token`: it also derives the private passkey storage encryption key. Do not rotate it by hand.

## Existing deployments

The October 5 security update requires one new admin sign-in with your existing passkey. Older browser sessions are rejected after migration to the `/admin` cookie. Registered passkeys and existing MCP grants are preserved; do not enroll again just because admin asks you to sign in.

Update the source and both server and device images before running `./bridge passkey-login`. For a deployment still configured with `ADMIN_AUTH_MODE=kakao` or `DOT_APPROVAL_MODE=kakao`, the command switches authentication to passkeys and issues initial enrollment. Old Kakao OAuth configuration and its sessions/grants are retired on startup. Existing passkey credentials, sessions and grants are preserved when the configured origins remain unchanged. The tablet's KakaoTalk app data is unaffected.

For the older manually managed `kakaotalk-test` VM, run the CLI inside the existing runtime rather than using the Mac installer's separate VM:

```bash
limactl shell --workdir=/ kakaotalk-test sudo python3 /srv/kakaotalk-collector/ops/cli.py passkey-login \
  --url https://your-node.ts.net --public-url https://your-node.ts.net
```

Configure the shared HTTPS route first. Once registration is complete, use the hostname above for admin. Do not repeat enrollment when an existing passkey still works.

## Boundaries and verification

`dot-control` owns encrypted SQLite credentials in `passkey-state`, reachable only on the internal network. Admin uses the existing private control token. The public process receives a separate `mcp_passkey_token` restricted to assertions and setup status. It cannot enroll, remove, configure or enumerate credentials, and has neither the credential volume nor its encryption key.

Every ceremony is single-use, short-lived, bound to a browser, exact origin, purpose and (for MCP) pending OAuth ticket. User presence and verification are required; counters are updated centrally. Configuration and initial/recovery link issuance are CLI-only. Admin and MCP keep distinct sessions; ports alone do not isolate cookies. Local admin cookies have separate names, are HttpOnly and SameSite=Strict, and their stored sessions are bound to the configured localhost origin and port. HTTPS cookies retain their Secure prefixes and attributes. HTTP is accepted only for the explicitly configured localhost origin.

```bash
uv run pytest -q
uv run ruff check .
uv run python -m tests.passkey_preview
# In another terminal with Playwright available:
node tests/passkey_browser.cjs
```

`PLAYWRIGHT_MODULE` and `CHROME_EXECUTABLE` can point to installed tools. The disposable fixture uses native Chromium WebAuthn with a virtual CTAP2 authenticator and real signature verification. It covers registration, login persistence, one credential on both origins, consent, PKCE, refresh and MCP access. The client callback is intercepted and all data is synthetic. It does not establish compatibility with a user's Touch ID, phone provider or actual ChatGPT browser.
