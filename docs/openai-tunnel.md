# Personal OpenAI Secure MCP Tunnel

[README](../README.md) · [HTTPS/OAuth](dot-plugin.md) · [Security](security.md)

Use this mode when only your own OpenAI account needs MCP access and you do not
want to publish an MCP HTTPS address. It also works on a remote Linux server.
The existing HTTPS/OAuth path can run alongside it for other clients.

```text
Your browser → localhost / SSH / HTTPS admin → passkey login and tunnel approval
OpenAI ↔ outbound tunnel client → internal MCP listener → collector read API
Other MCP clients → public HTTPS /mcp → existing OAuth listener (optional)
```

The server's tunnel client opens the connection to OpenAI. OpenAI does not need
inbound access to your server, a Funnel address, or an open router port for MCP.
Admin is separate: use localhost on your computer, SSH forwarding to a remote
server, or an existing trusted HTTPS address. Tailscale is optional. The tunnel
does not carry the admin UI, ADB or the collector's private API.

## Before setup

1. Open [OpenAI tunnel settings](https://platform.openai.com/settings/organization/tunnels)
   and create a tunnel using an account with **Tunnels Read + Manage**.
2. Associate it with the ChatGPT workspace where you will use Bridge. Copy the
   `tunnel_…` ID and obtain a runtime API key with **Tunnels Read + Use**.
3. Return to Bridge's connection form with these two values. Bridge starts the
   tunnel client for you; then follow the client completion steps below.

If the controls or tunnel are missing, check organization permissions and the
workspace association with your administrator. See the current
[OpenAI Secure MCP Tunnel instructions](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
Your OpenAI organization/workspace must support tunnel connections. Restrict
tunnel access to yourself: everyone allowed to use it gets the same Bridge
permissions. Bridge implements one owner, not per-workspace-user accounts.

The admin form accepts the runtime key in a password-masked field and clears it
after submission; it never returns the saved key to the browser. The CLI uses
hidden input. For noninteractive setup, save the key in a private file on the
machine running the command, not in a command argument or chat. Provisioning
copies it into the installation's protected `secrets/` directory and generates
a separate local service credential. On Mac, the CLI transfers it into the VM
through a temporary private directory. No key is stored in `.env` or job history.

## Add a tunnel to an existing installation

First update the installed Bridge images/source using the normal
[update procedure](operations.md), then run `./bridge up` in that installation to
enable the web setup service. Existing installations retain their admin address.

1. Sign in to admin and open **AI connections → Add or change a connection**.
2. Choose **ChatGPT → Personal tunnel · no public address**. Enter the tunnel ID
   and runtime API key under **Connection settings**. For the same configured ID,
   leave the key blank to reuse it, or enter a replacement.
3. Review the access checkbox and select **Set up and allow tunnel**. The page
   reports service startup, approval and server verification. You can leave and
   reopen the page while it runs. Approval is included in this web flow.
4. Follow [Finish in your AI client](web-ui.md#finish-in-your-ai-client): create
   a custom MCP plugin in ChatGPT, select **Tunnel** with the saved ID and
   **No authentication**, then install it and select it in a conversation.
   The runtime API key belongs in Bridge's setup form, not the client connection.
5. Ask the connected client for collector status, then retrieve a message you
   sent from your phone. The overview records the successful tool call separately
   from approval. A running tunnel alone does not verify message collection.

Reopen the tunnel's **Connection instructions** at any time. The ID and guidance
remain available after **Check server connection** and browser reloads. Existing
settings are collapsed; expand **Connection settings** to change them. For
failures, follow the displayed recovery message and select **Review and retry**.
Creating the tunnel and adding it to ChatGPT still require your provider account.

### Terminal alternative

Run `./bridge setup-connection --method openai-tunnel` from the installation
directory. It prompts for credentials, starts services and opens admin. Unlike
the web form, CLI provisioning requires a separate **Allow personal tunnel**
action in admin **AI connections**. Then complete the same client setup and
verification above. For noninteractive provisioning:

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

## Approval lifetime

Approval has no automatic expiration and survives normal service restarts and
server reboots when the stored configuration, keys and volumes are preserved.
Disconnecting, changing the tunnel ID, or resetting the passkey policy invalidates
it. No periodic browser approval is required. The tunnel services use Docker's
`unless-stopped` restart policy; Docker must start with the server.
The client retries startup connections for up to 60 seconds so it can recover
when Docker starts the tunnel before the private MCP listener is ready.

If you approved a tunnel with an older version's 30-day policy, choose **Remove
approval expiration** in **AI connections** once. This explicitly converts the existing
approval while preserving its subscriptions. An already expired approval needs
**Allow personal tunnel** again. Updates do not silently extend old approvals.

The connection uses the same eight MCP tools and event
implementation as public OAuth. It can read/search messages and manage requested
event subscriptions and acknowledgement cursors; it cannot send KakaoTalk
messages. [Event subscriptions](events.md) remain an explicit separate action.
Event delivery also requires enabling the conversation in admin **Conversation
events**. All conversations default off, and the same switches apply to OAuth
and tunnel clients.

## Fresh installation without external connections

```bash
./bridge up
```

This prepares local admin and KakaoTalk collection without either Tailscale or
an OpenAI tunnel. Add a tunnel later through the web flow above, or run
`./bridge setup-connection --method openai-tunnel`.
On a remote server, add `--no-browser` and use [SSH forwarding](quickstart.md#local-and-ssh-admin-access)
to open the localhost admin link on your own computer.

For unattended provisioning with existing credentials:

```bash
./bridge up --connection openai-tunnel \
  --tunnel-id tunnel_REPLACE_WITH_YOUR_32_CHARACTER_ID \
  --api-key-file /private/path/openai-runtime-key
```

`--admin-url https://admin.example.com` is optional if you already have a trusted
private admin proxy; route it to the admin gateway or an existing shared ingress.
With local admin, the tunnel does not start the public HTTP MCP ingress. Older
HTTPS admin routes through that ingress are preserved. Later `./bridge up`
reuses the stored credentials and admin address. Public HTTPS/OAuth can be added
separately through **AI connections → Add or change a connection**, or
`./bridge setup-connection`.

## Check, revoke and restore

In admin, **Check server connection** verifies server services. **Refresh
connections** reloads approvals and recorded activity. **Last successful tool
call** records past use, not current reachability; discovery and failed tool
calls do not update it. Calls made before this version are not backfilled.

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

The startup retry covers refused connections, not Docker DNS failures. If the
client started while `dot-tunnel` had no DNS entry, wait for that service to be
healthy and run `docker compose --profile dot --profile tunnel restart openai-tunnel`.

## Validation scope

Local automated tests cover public/private credential isolation, all eight tools,
legacy initialization, persistent approval across time and restarts, revocation,
legacy expiry and policy changes, event
delivery and pending/acknowledgement behavior, and provisioning rollback. Compose
configuration is checked for private networks and absence of tunnel host ports.
The official v0.0.15 source was checked for file-backed headers and startup probes.
A separate Linux test installation also connected to OpenAI with a real runtime
key, exercised browser approval and revocation, preserved approval across service
restarts and HTTPS/OAuth setup, and recovered from a 12-second MCP startup delay.
On 2026-10-05, the tunnel was moved from that empty test installation to an
existing logged-in collector. A self-sent test message was retrieved through the
private MCP listener and then through the connected KakaoTalk Bridge app in
ChatGPT, which returned the matching message and timestamp. The existing Android
and collector containers were preserved. The improved admin flow was also
checked on the real deployment: a server check kept saved instructions visible,
and a successful tunnel MCP status call appeared in the activity overview.
Synthetic browser checks covered setup failure/retry and a 390-pixel mobile
viewport. See [UX validation](implementation.md#admin-ux-and-connection-setup-2026-10-05).
End-to-end OpenAI event delivery and a
full VM reboot remain deployment acceptance checks. Readiness alone does not
verify message retrieval or event delivery.
