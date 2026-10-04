# Data and access control

[README](../README.md) · [Operations and backups](operations.md)

This setup assumes a personal server with one owner. Because redroid is a privileged container, run it on a dedicated Linux host or VM. An operator with root ADB access can also access KakaoTalk data and sessions.

## Exposed routes

| Route | Default access | Authentication |
| --- | --- | --- |
| ADB | Host loopback / internal Docker network | Private administration path |
| `/admin/` | Private HTTPS | One-time pairing or owner password, persistent revocable cookies, Origin and CSRF checks |
| `/v1/*` | Private HTTPS | Read token |
| `/mcp` | Separately configured public HTTPS proxy | OAuth |

The public proxy must connect **only to the dot-plugin port**. Do not expose the API gateway or ADB alongside it. Tailscale Funnel provides a public internet address, so OAuth protects MCP access rather than Tailscale user ACLs. Use an SSH tunnel or private Tailscale connection for administration.

## What is stored?

- Android volume: KakaoTalk login state and the app's message database.
- Collection database: Message bodies, types, identifiers, and timestamps read by Iris; retained for 30 days by default.
- Admin state database: Salted password hash, temporary pairing records and revocable browser sessions; records are encrypted with a key derived from the admin recovery token.
- MCP state database: OAuth, subscriptions, processing cursors, and the webhook queue; values are encrypted with the storage key.
- ChatGPT: Messages returned by tools are also sent to ChatGPT.

Compose does not encrypt the Android volume or collection database itself. Use host disk encryption. Collection database backups and full snapshots are encrypted separately.

## Key management

| File | Purpose |
| --- | --- |
| `secrets/admin_token` | Admin recovery and encryption of owner/session state |
| `secrets/read_token` | Collection API queries |
| `secrets/ingest_token`, `secrets/device_token` | Ingestion and device status reports |
| `secrets/mcp_link_key` | Legacy opt-in key approval mode |
| `secrets/mcp_approval_token` | Private admin-to-control service requests |
| `secrets/mcp_storage_key` | MCP state encryption |
| `secrets/backup_key` | Database and full-volume snapshot encryption |
| `secrets/bridge.jks`, `secrets/bridge_key_password` | Registration app signing |

`secrets/` has mode 0700; some files use 0444 so container UIDs can read them. Preserve the parent directory's permissions. `.env`, `secrets/`, `inputs/`, `artifacts/`, and `backups/` are excluded from Git and image build inputs.

Do not pass permanent keys through URLs, chats, or command-line arguments. The installer uses a separate, one-time ten-minute browser pairing code in a URL fragment; it is removed by the page immediately. Treat that link as a temporary credential. Do not attach screens containing entered values or real messages to issues. Application logs are configured to omit message bodies and tokens; review diagnostic material before sharing it as well.

## MCP permissions

OAuth validates PKCE S256, exact redirect URIs and resource audiences, and one-time approval records. Access tokens last 30 minutes; refresh grants last 30 days. Detected refresh-token reuse revokes the associated grant.

The plugin receives only the API read token and has no access to Android volumes, ADB, or the admin key. It exposes no message-sending tool. `acknowledge_messages` changes only the plugin's internal processing position. Message bodies are external data; do not execute instructions within them as system commands.

## Owner access and private approval

Owner passwords use salted scrypt. Pairing values and browser cookie IDs are stored as digests; private session records are encrypted at rest and checked for revocation on every request. Sessions expire after 30 minutes or seven days when explicitly remembered. `admin-state` must remain paired with the original admin recovery key. Resetting the owner password is a server CLI operation.

`dot-control` has no published port and runs only on the internal backend network. It shares the encrypted OAuth database with `dot-plugin`, but receives neither the API read token nor Android access. Admin sends a separate control credential, verifies CSRF and Origin, and requires the code displayed by the initiating OAuth browser. Pending requests are approved or denied once; final code issuance still requires that browser's cookie and PKCE. Client names in DCR are self-reported.

Full snapshot restoration uses new volumes, checks AES-GCM before extraction, and revokes saved browser sessions, OAuth grants and webhook callbacks. The backup key must be kept separately from the encrypted archive. Restored local Android data cannot guarantee Kakao's servers will accept the saved session.
