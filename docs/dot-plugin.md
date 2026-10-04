# Connect ChatGPT

[README](../README.md) · [Events](events.md) · [Security](security.md)

`dot-plugin` is a remote MCP server that exposes messages stored in the collection API through OAuth. It does not sign in to KakaoTalk again. Use it to browse and search messages and check collection status.

## Connect

First, prepare a public HTTPS address using the deployment instructions below.

1. Add a custom MCP server in ChatGPT. Set its name to `KakaoTalk Bridge`, its URL to `https://<your-host>/mcp`, and authentication to OAuth.
2. On the server's approval screen, enter `secrets/mcp_link_key`. This is separate from your Kakao password and admin key.
3. Once connected, request recent messages or a search. For example: “Show my recent messages from KakaoTalk Bridge.”

On a Mac, copy the key without printing it:

```bash
pbcopy < secrets/mcp_link_key
```

Connecting the plugin does not create event subscriptions or automated tasks. Subscribe to [Events](events.md) separately when needed.

## Tools

| Tool | Purpose |
| --- | --- |
| `get_recent_messages` | Retrieve recent collected rows with cursor-based pagination |
| `search_messages` | Search message bodies by substring |
| `list_conversations` | Retrieve observed conversation references; the same conversation may appear more than once |
| `get_collector_status` | Collection status and subscription/delivery status for the current connection |
| `get_profile` | Opaque profile ID identifying the connection |
| `get_pending_messages` | Retrieve unprocessed messages for a consumer |
| `acknowledge_messages` | Record processing completion through a retrieved page |

By default, `get_recent_messages` covers the latest N cursor positions. A conversation filter returns matching rows within that range, so the result may contain fewer than N rows. There are no message-sending, login, or ADB-control tools.

## Deploy on Linux

On a server already running the API and Iris, set `DOT_PUBLIC_URL` in `.env` to the actual HTTPS origin, without a trailing `/` or `/mcp`.

```bash
uv run python scripts/init-dot-secrets.py
sudo chown 10001:10001 secrets/mcp_link_key secrets/mcp_storage_key
sudo chmod 400 secrets/mcp_link_key secrets/mcp_storage_key
docker compose --profile dot build dot-plugin
docker compose --profile dot up -d --no-deps dot-plugin
```

The public HTTPS proxy targets `127.0.0.1:18787` by default. **Expose only this port** and keep the API gateway and admin console private. dot-plugin uses only the API read token and receives neither Android volumes nor the admin token.

## Deploy in Lima on a Mac

Run the containers in Lima, not in the Mac's Docker Desktop. Copy the keys into the VM and set ownership there so UID 10001 can read them. Follow [Mac installation](local-redroid.md) to transfer images.

The supplied tunnel configuration uses this route:

```text
Tailscale Funnel HTTPS :443
  → Mac 127.0.0.1:18788
  → SSH tunnel → Lima 127.0.0.1:18787 → dot-plugin:8787
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

On Linux, use `docker compose` instead of `scripts/lima-compose.sh`. The smoke test uses a temporary OAuth grant to verify TLS, authentication, tool discovery, and retrieval of actual recent rows, then revokes the grant. It prints neither message bodies nor keys and creates no event subscriptions.

| Error | What to check |
| --- | --- |
| `invalid_origin` | The scheme, host, and port in `DOT_PUBLIC_URL` must match the browser address; the approval HTML's Referrer-Policy must be `same-origin` |
| `invalid_approval` | The approval screen is over 10 minutes old or its cookie is missing; restart the connection from ChatGPT |
| `invalid_link_key` | Verify that you used `mcp_link_key` |
| Tool errors after connecting | Collection API health, read token, and collection approval |

Keep the approval form's Origin/cookie checks and PKCE validation. After changing form policies, verify approval and the return to ChatGPT in a real browser.

## Protocol

The server provides MCP `2026-07-28` and the `kakao.read` and `kakao.events` scopes. It supports DCR and ChatGPT CIMD, without allowing arbitrary redirects if CIMD fetching fails. CIMD supports `none`; DCR supports `none`, `client_secret_basic`, and `client_secret_post`. `private_key_jwt` is not supported.

[OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events) · [OAuth authentication](https://developers.openai.com/plugins/build/auth) · [Connect ChatGPT](https://developers.openai.com/plugins/build/app-quickstart#connect-your-mcp-server-in-chatgpt)
