# Connect ChatGPT

[README](../README.md) · [Events](events.md) · [Security](security.md)

`dot-plugin` is a remote MCP server that exposes messages stored in the collection API through OAuth. It does not sign in to KakaoTalk again. Use it to browse and search messages and check collection status. This page covers public HTTPS/OAuth; for outbound-only OpenAI access, use the optional [personal tunnel](openai-tunnel.md).

## Connect

In admin, open **AI connections → Add or change a connection**. Choose
**ChatGPT** or **Another remote AI client**, then your existing HTTPS address or
Tailscale. The form accepts an origin or full `/mcp` URL, prepares OAuth and shows
the client address. You keep the existing admin/passkey origin. For manually
managed deployments, use the instructions below.

1. Add a custom MCP server in ChatGPT. Set its name to `KakaoTalk Bridge`, its URL to `https://<your-host>/mcp`, and authentication to OAuth.
2. Follow the consent screen. With shared HTTPS admin/MCP, confirm with your passkey, review the client, callback and permissions, then choose **Allow connection**. With localhost/private admin, match the eight-character code in admin **AI connections** and choose **Approve connection**. Canceling creates no connection.
3. Ask for collector status, then retrieve recent messages or search for a message you sent from your phone. For example: “Show my recent messages from KakaoTalk Bridge.”

Tailscale is optional when you already have an HTTPS reverse proxy. Shared HTTPS
consent needs no linking key or separate admin visit; split-origin setup selects
`DOT_APPROVAL_MODE=admin` automatically and uses code approval in your private
admin. `key` remains a legacy opt-in mode. Disconnect clients under **AI
connections**.

**Server setup complete** reports service configuration, not client access. The admin
overview and connection cards distinguish approval from a recorded successful
tool call. Tool discovery and failed calls do not count, and timestamps do not
prove current reachability. Saved connection instructions stay available after
checks and reloads. See [admin status meanings](web-ui.md#what-each-status-proves).

Connecting the plugin does not create event subscriptions or automated tasks. Subscribe to [Events](events.md) separately when needed.

## Tools

| Tool | Purpose |
| --- | --- |
| `get_recent_messages` | Latest messages by sent time, with room/sender/time filters |
| `search_messages` | Literal body search with room/sender/time filters |
| `list_conversations` | List distinct rooms with available names, latest time and retained count |
| `get_conversation_context` | Retrieve earlier/later messages around a message in the same room |
| `get_collector_status` | Collection status and subscription/delivery status for the current connection |
| `get_profile` | Opaque profile ID identifying the connection |
| `get_pending_messages` | Retrieve unprocessed messages for a consumer |
| `acknowledge_messages` | Record processing completion through a retrieved page |

Recent/search return messages by sent time, newest first, with opaque pagination. Room filters apply before the limit. See [Message queries](mcp-queries.md) for names, time ranges, context and compatibility. There are no message-sending, login or ADB-control tools.

## Deploy on Linux

On a server already running the API and Iris, set `DOT_PUBLIC_URL` in `.env` to the actual HTTPS origin, without a trailing `/` or `/mcp`.

```bash
uv run python scripts/init-dot-secrets.py
sudo chown 10001:10001 secrets/mcp_link_key secrets/mcp_storage_key
sudo chmod 400 secrets/mcp_link_key secrets/mcp_storage_key
sudo chmod 444 secrets/mcp_approval_token secrets/mcp_passkey_token
docker compose --profile dot build dot-plugin dot-ingress
docker compose --profile dot up -d --no-deps dot-plugin dot-control dot-ingress
# Update the device/admin image too, then run ./bridge passkey-login.
```

The public HTTPS proxy targets `dot-ingress` at `127.0.0.1:18787` by default.
**Expose only this port**, never the API/admin gateway. Do not publish dot-plugin
directly: the ingress blocks internal paths and removes private admin cookies
on MCP routes. It joins a dedicated admin ingress network, not the device, API
or control networks. If admin must stay private, deny `/admin` and `/admin/*` at
the public proxy; otherwise the shared ingress serves authenticated admin at that
hostname. dot-plugin uses the API read token and receives neither Android volumes
nor the admin token.

## Deploy in Lima on a Mac

Run the containers in Lima, not in the Mac's Docker Desktop. Copy the keys into the VM and set ownership there so UID 10001 can read them. Follow [Mac installation](local-redroid.md) to transfer images.

The supplied tunnel configuration uses this route:

```text
Tailscale Funnel HTTPS :443
  → Mac 127.0.0.1:18788
  → SSH tunnel → Lima 127.0.0.1:18787 → dot-ingress:8786 → dot-plugin:8787
```

Run `scripts/dot-tunnel.sh`, or update the absolute paths in `deploy/dev.kakaocollector.dot-tunnel.plist.example` and install it as a user LaunchAgent. Store machine-specific plists in the Git-ignored `deploy/*.local.plist` files. Then point Tailscale Funnel to `127.0.0.1:18788` on the Mac. Check any existing Funnel destinations to avoid conflicts.

Mac sleep or shutdown, or stopping Lima or Tailscale, interrupts the public connection. Even though the Funnel address is public, `/mcp` still requires OAuth authentication.

## Verification and troubleshooting

```bash
./scripts/lima-compose.sh --profile dot ps
./scripts/lima-compose.sh logs --tail 30 dot-plugin
tailscale funnel status
uv run python scripts/smoke-dot.py https://your-host.example
```

On Linux, use `docker compose` instead of `scripts/lima-compose.sh`. The legacy smoke script requires explicit `DOT_APPROVAL_MODE=key`; it does not test passkeys. Normal installations use passkey confirmation and explicit consent. In key mode the smoke test uses a temporary OAuth grant to verify TLS, authentication, tool discovery, and retrieval of actual recent rows, then revokes the grant. It prints neither message bodies nor keys and creates no event subscriptions.

| Error | What to check |
| --- | --- |
| `invalid_origin` | The scheme, host, and port in `DOT_PUBLIC_URL` must match the browser address; the approval HTML's Referrer-Policy must be `same-origin` |
| `invalid_approval` | The approval screen is over 10 minutes old or its cookie is missing; restart the connection from ChatGPT |
| `approval_required` | Approve the matching code in private admin **AI connections** |
| Passkey sign-in needs setup | Run `./bridge passkey-login` on the server and finish registration at the private admin hostname |
| No passkey is available | Use the device or password manager where it was saved, check the hostname, and restart in a supported system browser |
| Code is incorrect or request expired | Check the initiating browser and restart a request older than ten minutes |
| Tool errors after connecting | Collection API health, read token, and collection approval |

Keep the approval form's Origin/cookie checks and PKCE validation. After changing form policies, verify approval and the return to ChatGPT in a real browser.

## Protocol

The server provides MCP `2026-07-28` and the `kakao.read` and `kakao.events` scopes. It supports DCR and ChatGPT CIMD, without allowing arbitrary redirects if CIMD fetching fails. CIMD supports `none`; DCR supports `none`, `client_secret_basic`, and `client_secret_post`. `private_key_jwt` is not supported.

[OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events) · [OAuth authentication](https://developers.openai.com/plugins/build/auth) · [Connect ChatGPT](https://developers.openai.com/plugins/build/app-quickstart#connect-your-mcp-server-in-chatgpt)
