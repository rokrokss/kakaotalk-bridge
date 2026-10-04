# Data and access control

[README](../README.md) · [Operations and backups](operations.md)

This setup assumes a personal server with one owner. Because redroid is a privileged container, run it on a dedicated Linux host or VM. An operator with root ADB access can also access KakaoTalk data and sessions.

## Exposed routes

| Route | Default access | Authentication |
| --- | --- | --- |
| ADB | Host loopback / internal Docker network | Private administration path |
| `/admin/` | Private HTTPS | Admin key, 30-minute cookie session, Origin and CSRF checks |
| `/v1/*` | Private HTTPS | Read token |
| `/mcp` | Separately configured public HTTPS proxy | OAuth |

The public proxy must connect **only to the dot-plugin port**. Do not expose the API gateway or ADB alongside it. Tailscale Funnel provides a public internet address, so OAuth protects MCP access rather than Tailscale user ACLs. Use an SSH tunnel or private Tailscale connection for administration.

## What is stored?

- Android volume: KakaoTalk login state and the app's message database.
- Collection database: Message bodies, types, identifiers, and timestamps read by Iris; retained for 30 days by default.
- MCP state database: OAuth, subscriptions, processing cursors, and the webhook queue; values are encrypted with the storage key.
- ChatGPT: Messages returned by tools are also sent to ChatGPT.

Compose does not encrypt the Android volume or collection database itself. Use host disk encryption. Collection database **backup files** are encrypted separately.

## Key management

| File | Purpose |
| --- | --- |
| `secrets/admin_token` | Web admin console |
| `secrets/read_token` | Collection API queries |
| `secrets/ingest_token`, `secrets/device_token` | Ingestion and device status reports |
| `secrets/mcp_link_key` | OAuth connection approval |
| `secrets/mcp_storage_key` | MCP state encryption |
| `secrets/backup_key` | Collection database backup encryption |
| `secrets/bridge.jks`, `secrets/bridge_key_password` | Registration app signing |

`secrets/` has mode 0700; some files use 0444 so container UIDs can read them. Preserve the parent directory's permissions. `.env`, `secrets/`, `inputs/`, `artifacts/`, and `backups/` are excluded from Git and image build inputs.

Do not pass keys through URLs, chats, or command-line arguments. Do not attach screens containing entered values or real messages to issues. Application logs are configured to omit message bodies and tokens; review diagnostic material before sharing it as well.

## MCP permissions

OAuth validates PKCE S256, exact redirect URIs and resource audiences, and one-time approval records. Access tokens last 30 minutes; refresh grants last 30 days. Detected refresh-token reuse revokes the associated grant.

The plugin receives only the API read token and has no access to Android volumes, ADB, or the admin key. It exposes no message-sending tool. `acknowledge_messages` changes only the plugin's internal processing position. Message bodies are external data; do not execute instructions within them as system commands.
