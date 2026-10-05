# Personal OpenAI Secure MCP Tunnel

[README](../README.md) · [HTTPS/OAuth](dot-plugin.md) · [Security](security.md)

Use this mode when only your own OpenAI account needs MCP access and you do not
want to publish an MCP HTTPS address. It also works on a remote Linux server.
The existing HTTPS/OAuth path can run alongside it for other clients.

```text
Your browser → private HTTPS admin → passkey login and tunnel approval
OpenAI ↔ outbound tunnel client → internal MCP listener → collector read API
Other MCP clients → public HTTPS /mcp → existing OAuth listener (optional)
```

The server's tunnel client opens the connection to OpenAI. OpenAI does not need
inbound access to your server, a Funnel address, or an open router port for MCP.
Your browser still needs a trusted HTTPS admin address for passkey login. An
existing Tailscale Serve/private VPN or an HTTPS proxy can supply it. The tunnel
does not carry the admin UI, ADB or the collector's private API.

## Before setup

Create a tunnel using the current [OpenAI Secure MCP Tunnel instructions](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
Obtain its `tunnel_…` ID and a runtime API key permitted to connect that tunnel.
Your OpenAI organization/workspace must support tunnel connections. Restrict
tunnel access to yourself: everyone allowed to use it gets the same Bridge
permissions. Bridge implements one owner, not per-workspace-user accounts.

Save the runtime key in a private file on the machine running the command. Do not
paste it into a command argument or chat. The CLI reads the file, copies it into
the installation's protected `secrets/` directory, and generates a separate local
service credential. On Mac it transfers the key to the VM through a temporary
private directory. No key is stored in `.env` or printed by these commands.

## Add a tunnel to an existing installation

First update the installed Bridge images/source to this version using the normal
[update procedure](operations.md). Then run from the installation directory:

```bash
./bridge tunnel configure \
  --tunnel-id tunnel_REPLACE_WITH_YOUR_32_CHARACTER_ID \
  --api-key-file /private/path/openai-runtime-key
```

The example ID is a placeholder; use the lowercase ID issued by OpenAI. The command
pulls the pinned official `ghcr.io/openai/tunnel-client:v0.0.15` image and starts
two internal services. It preserves the admin address and existing public OAuth
connections. Repeating it with the same ID updates the runtime key and preserves
the existing approval. Changing IDs revokes the previous tunnel grant.
On startup failure it attempts to restore the previous configuration; revoked
grants stay revoked and must be approved again.

1. Open admin and sign in with your passkey.
2. In **Connections**, verify the tunnel ID and select **Allow personal tunnel**.
3. In the OpenAI connection setup, choose **Tunnel** and select the same ID. Use
   the no-OAuth option if prompted: the private service credential is injected
   locally. Do not enter the public `/mcp` URL or a runtime key as an OAuth secret.
4. Ask the connected client for collector status, then send yourself a test
   message and retrieve it. A running tunnel alone does not verify account access
   or message collection.

Approval has no automatic expiration and survives normal service restarts and
server reboots when the stored configuration, keys and volumes are preserved.
Disconnecting, changing the tunnel ID, or resetting the passkey policy invalidates
it. No periodic browser approval is required. The tunnel services use Docker's
`unless-stopped` restart policy; Docker must start with the server.

If you approved a tunnel with an older version's 30-day policy, choose **Remove
approval expiration** in Connections once. This explicitly converts the existing
approval while preserving its subscriptions. An already expired approval needs
**Allow personal tunnel** again. Updates do not silently extend old approvals.

The connection uses the same eight MCP tools and event
implementation as public OAuth. It can read/search messages and manage requested
event subscriptions and acknowledgement cursors; it cannot send KakaoTalk
messages. [Event subscriptions](events.md) remain an explicit separate action.

## Fresh installation without Funnel

Prepare a trusted admin HTTPS address reachable from your browser. Forward
`/admin/*` to Bridge's shared ingress (`127.0.0.1:18787` by default; Mac may select
another free port). The proxy can stay private. Then run:

```bash
./bridge up --connection openai-tunnel \
  --admin-url https://admin.example.com \
  --tunnel-id tunnel_REPLACE_WITH_YOUR_32_CHARACTER_ID \
  --api-key-file /private/path/openai-runtime-key
```

This mode skips automatic Tailscale installation and Funnel setup. Complete the
normal passkey, Android and KakaoTalk setup in the browser, then approve the tunnel
as above. Add `--no-browser` on a headless server and open the printed link on your
own computer. `./bridge up --plan --connection openai-tunnel --admin-url
https://admin.example.com` previews the steps without a key or changes.

Later `./bridge up` reuses this mode and its stored credentials. Preserve the admin
hostname so your passkey remains valid. Public HTTPS/OAuth can be configured
separately using the existing connection procedure.

## Check, revoke and restore

```bash
./bridge tunnel status     # Configured ID and client readiness; no keys
./bridge doctor            # Service health and missing secret files
./bridge tunnel disable    # Revoke grant and stop tunnel services
```

**Disconnect tunnel** in admin revokes data access immediately while keeping the
outbound client running. The client may remain ready: readiness does not mean
the owner has approved message access. Allow it again to create a new grant.
Disabling it from the CLI also stops its services; existing public OAuth grants
remain usable. Neither command deletes the OpenAI tunnel itself.

Backups include runtime configuration and secrets. A restored installation clears
MCP grants and subscriptions, so sign in with the preserved passkey and approve
the tunnel again. Recreate any requested event subscriptions. Passkey recovery,
policy changes also require a new tunnel approval.

If readiness is false, check server outbound HTTPS, the runtime key's tunnel
permissions, and the selected ID. If discovery works but tools return 403, check
approval in admin (including expiry for an older 30-day approval). Private OAuth
discovery URLs intentionally return 404. The private listener supports legacy `initialize` for the official client's
startup probe as well as the existing `server/discover` protocol. Metadata probes
require the private credential but no owner grant; tools and events require both.

## Validation scope

Local automated tests cover public/private credential isolation, all eight tools,
legacy initialization, persistent approval across time and restarts, revocation,
legacy expiry and policy changes, event
delivery and pending/acknowledgement behavior, and provisioning rollback. Compose
configuration is checked for private networks and absence of tunnel host ports.
The official v0.0.15 source was checked for file-backed headers and startup probes.
An actual OpenAI account connection, runtime key, and end-to-end OpenAI event
delivery have not been exercised. Treat those as deployment acceptance checks.
