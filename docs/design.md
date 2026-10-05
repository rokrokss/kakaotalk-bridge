# System architecture

[README](../README.md) · [Iris implementation](iris.md) · [API](api.md)

The stack runs one account and one redroid instance. Iris is the default collection path. The original notification-based design and implementation history remain in Git.

The diagram below shows the optional shared-HTTPS deployment. The default admin
entry point is localhost or SSH forwarding; OpenAI tunnel and stdio connections
are alternatives to public HTTPS. See [connection diagrams](../README.md#connect-your-ai).

![Shared-HTTPS example: admin and MCP share port 443 with passkey and OAuth authentication. Iris runs inside redroid, and the collector stores messages through the API in SQLite.](assets/architecture.svg)

[Architecture diagram source](assets/architecture.svg) · [Simplified message flow](assets/message-flow.svg)

## Service boundaries

| Service | Responsibility |
| --- | --- |
| `redroid` | Run Android; the only privileged container |
| `iris-collector` | Check the Iris process inside Android, fetch rows, and retry storage |
| `api` | Authentication, deduplication, atomic message/cursor storage, queries, and retention cleanup |
| `device-agent` | Check ADB state and registration information |
| `gateway` | Private HTTPS and API/admin routing |
| `admin` | Passkey login, operating overview, setup progress, connection/event controls, restricted screen/input commands, and login confirmation |
| `dot-control` | Private passkey authority, OAuth/tunnel approval and revocation, activity metadata and conversation event policy |
| `dot-plugin` | Passkey verification, explicit OAuth consent, remote MCP, and optional event delivery |
| `dot-ingress` | Shared entry point; route admin and MCP, filter admin cookies on MCP routes, reject internal routes |
| `admin-local` | Optional loopback-only admin entry point with an exact localhost Host check |
| `dot-tunnel`, `openai-tunnel` | Optional private MCP listener and outbound OpenAI tunnel client; no published tunnel port |
| Host setup agent | Finite connection operations over a private Unix socket; runs outside Compose under systemd or a service manager |
| `adb-init` | Offline provisioning of the two collector public keys before Android starts |
| `bootstrap`, `mcp` | One-time installation and the client-launched stdio adapter, respectively |

Iris runs as an `app_process` inside redroid, not as a separate Compose service. The registration app handles configuration and web input. In Iris mode, it stops legacy notification observation and uploads.

## Login and collection approval

1. On a fresh tablet, setup prepares Korean and Aurora. After KakaoTalk installation, component setup verifies its signature, deploys Bridge and Iris, creates registration data and leaves collection locked. Repeating setup preserves existing enrollment and approval; the legacy CLI bootstrap remains a separate maintenance action.
2. `login-check` reads tablet settings and the selected “Use with other devices” option (“다른 기기와 함께 사용”) on the Korean KakaoTalk screen. It does not press the login button.
3. The operator signs in and manually checks both the phone and tablet sessions.
4. `confirm-secondary` checks that the precheck is less than 30 minutes old, the app version and device match, and both confirmations are present, then saves the approval record.
5. An app version or Android fingerprint change, or a phone sign-out report, invalidates collection approval.

A tablet model name and resolution alone do not authorize simultaneous login. Phone confirmation is a timestamped operator record, not remote monitoring.

The admin guide tracks **Prepare → Sign in → Collect**, independently of optional
AI setup. Once the collector is running, the overview shows collector state,
remote tool activity and manual phone confirmation. Tablet inspection expires
after 60 seconds or a device action; the UI retains its last-observed approval
label while requiring fresh inspection for dependent actions. Folding the tablet
workspace suspends screen polling, not collection.

## Connection setup and activity

The web form selects a user destination, then a method. It sends only validated
operations to the host setup agent; the admin container has no Docker socket.
The agent provisions settings and services, reports bounded progress messages,
and persists job status. A successful non-check job saves the preferred method
separately. Running, failed or interrupted work can be inspected after reopening
the page; interrupted changes require an explicit retry.

HTTPS/tunnel instructions derive from saved configuration, not the last job.
This lets service checks and failures retain useful client instructions without
claiming that configuration implies successful access. See [setup security](security.md#web-connection-setup).

After a successful remote tool call, the MCP application stores only
`last_tool_at` in a separate `connection_activity` record keyed by grant ID in
`dot-state`. It does not rewrite the grant or save arguments/message content.
The control service exposes the timestamp for active OAuth/tunnel approvals.
Discovery and failed calls do not update it; a new grant starts without prior
activity. The UI presents this as historical use, independently of server checks,
event delivery and local stdio calls.

## Storage and retries

Iris decrypts rows read through fixed SELECT queries. The Python collector waits for the API's commit acknowledgment for each row. The server saves the row and the latest Iris cursor in the same SQLite transaction. Lost acknowledgments can be recovered by querying and sending again.

Message IDs are derived from the registration epoch, database identity, and log ID. Rows with different log IDs remain distinct even when their bodies match. Invalid rows, database replacement, and IDs moving backwards are not skipped automatically. Edits and deletions of existing rows are not synchronized.

## Networking and recovery

The default setup publishes admin on loopback HTTP for localhost or SSH forwarding, alongside the internal HTTPS API gateway. AI connections are optional. The local admin ingress rejects non-admin routes and requires the exact configured localhost Host. An optional public HTTPS proxy targets only dot-ingress: `/admin/*` forwards to admin and OAuth/MCP routes forward to dot-plugin. Separate Docker networks keep the public application away from Android and admin controls, while allowing read API and passkey assertion requests. The ingress has an edge network for loopback port publishing and separate internal links to dot-plugin and admin. It does not join device, API or control networks. The public MCP process does not join the admin ingress network. See [Security](security.md) for the cookie boundary and remaining risks.

Automatic restarts are disabled for redroid. An optional host supervisor provides a limited number of recovery attempts. Follow [Operations](operations.md) for database backups and Android snapshots.

## Optional Events

There are no automatic subscriptions. Admin **Conversation events** controls a shared conversation allowlist; every room defaults off. A separately requested client subscription sends new row identifiers only from enabled rooms, starting at each room's activation cursor. Disabling a room cancels queued sends and filters pending reads. Events act as wake-up signals; message bodies are read through MCP tools. Each consumer has its own acknowledged cursor, independent of KakaoTalk read status. See [Events](events.md).
