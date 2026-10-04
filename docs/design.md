# System architecture

[README](../README.md) · [Iris implementation](iris.md) · [API](api.md)

The stack runs one account and one redroid instance. Iris is the default collection path. The original notification-based design and implementation history remain in Git.

![Administrators control the tablet over private HTTPS. Your AI connects to MCP over public HTTPS with OAuth. Iris runs inside redroid, and the collector stores messages through the API in SQLite.](assets/architecture.svg)

[Architecture diagram source](assets/architecture.svg) · [Simplified message flow](assets/message-flow.svg)

## Service boundaries

| Service | Responsibility |
| --- | --- |
| `redroid` | Run Android; the only privileged container |
| `iris-collector` | Check the Iris process inside Android, fetch rows, and retry storage |
| `api` | Authentication, deduplication, atomic message/cursor storage, queries, and retention cleanup |
| `device-agent` | Check ADB state and registration information |
| `gateway` | Private HTTPS and API/admin routing |
| `admin` | Passkey login, persistent sessions, setup guide, restricted screen/input commands, and login confirmation |
| `dot-control` | Private passkey authority, approval and revocation of OAuth connections |
| `dot-plugin` | Passkey verification, explicit OAuth consent, remote MCP, and optional event delivery |
| `dot-ingress` | Public HTTP entry point; remove private cookies and reject private routes before forwarding to MCP |
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

## Storage and retries

Iris decrypts rows read through fixed SELECT queries. The Python collector waits for the API's commit acknowledgment for each row. The server saves the row and the latest Iris cursor in the same SQLite transaction. Lost acknowledgments can be recovered by querying and sending again.

Message IDs are derived from the registration epoch, database identity, and log ID. Rows with different log IDs remain distinct even when their bodies match. Invalid rows, database replacement, and IDs moving backwards are not skipped automatically. Edits and deletions of existing rows are not synchronized.

## Networking and recovery

The default setup restricts external access to the API and ADB, publishing HTTPS on the host loopback interface. The public proxy for ChatGPT targets only dot-ingress, which forwards to dot-plugin. Separate Docker networks keep the public application away from Android and admin controls, while allowing read API and passkey assertion requests. The ingress has its own edge network for loopback port publishing and an internal link to dot-plugin. It has no direct admin, device, API or control network. See [Security](security.md) for the cookie boundary and remaining risks.

Automatic restarts are disabled for redroid. An optional host supervisor provides a limited number of recovery attempts. Follow [Operations](operations.md) for database backups and Android snapshots.

## Optional Events

There are no automatic subscriptions. A separately requested subscription sends new row identifiers through webhooks. Events act as wake-up signals; message bodies are read through OAuth tools. Each consumer has its own acknowledged cursor, independent of KakaoTalk read status. See [Events](events.md).
