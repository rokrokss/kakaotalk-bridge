# HTTP API and stdio MCP

[README](../README.md) · [Remote OAuth MCP](dot-plugin.md)

## HTTP queries

For named messages, latest-by-send-time queries, room/sender/time filters and context, use the [v2 query API](mcp-queries.md). The v1 endpoints below retain ingestion-order behavior for existing consumers.

All `/v1/*` and `/v2/*` routes require the read token. Ingest and device tokens cannot query them. This example runs on the Linux server and verifies the TLS certificate.

```bash
# Pass the token through stdin, not as a curl argument.
{ printf 'header = "Authorization: Bearer '; tr -d '\n' < secrets/read_token; printf '"\n'; } |
  curl --config - --cacert secrets/tls_cert.pem https://127.0.0.1:8443/v1/messages
```

| API | Purpose |
| --- | --- |
| `GET /v1/messages?after=0&limit=50` | Retrieve messages in storage order |
| `GET /v1/search?q=keyword&after=0&limit=50` | Search message bodies by substring |
| `GET /v1/conversations?after=0&limit=50` | Retrieve observed conversation references; the same conversation may appear more than once |
| `GET /v1/status` | Collection status, coverage gaps, and queue state |
| `GET /health/live`, `/health/ready` | Process and database health |

Pass `next_cursor` as `after` in the next request and check `has_more`. If `coverage.cursor_epoch` changes, the database has been restored and consumers must reset their cursors. Records at or below `pruned_through_cursor` have been deleted under the retention policy.

Iris rows have `source=iris_db`. `database_ref` contains database message, conversation, and sender IDs as strings. `conversation_ref` is scoped by device, registration epoch, and conversation ID. Legacy notification records retain `source=notification` and `conversation_ref=null`.

`coverage.complete` is always `false`. Rows that never reached redroid or were already deleted cannot be recovered, so this is not a complete archive of all KakaoTalk conversations.

## stdio MCP

With the collection API running, open **AI connections → Add or change a
connection → An AI app on my computer** in admin. **Run Bridge from my AI app ·
local or SSH** provides copyable configuration for `./bridge mcp`. For a remote
server, enter its SSH host alias or `user@host`; the account needs noninteractive
SSH authentication and Docker access. The CLI alternative is
`./bridge setup-connection --method stdio`.

The client starts the adapter when needed. This requires neither public HTTPS,
OAuth, Tailscale nor an OpenAI tunnel. Confirm it by asking your client for
collector status and retrieving a test message. Local stdio calls do not appear
in admin's **Remote AI activity** card.

For a manually managed Docker installation, you can also configure the client
directly. Replace the project path with its actual absolute path on the Docker
host:

```json
{
  "mcpServers": {
    "kakaotalk": {
      "command": "docker",
      "args": ["compose", "--project-directory", "/absolute/path/kakaotalk-bridge", "--profile", "mcp", "run", "--rm", "--no-deps", "-T", "mcp"]
    }
  }
}
```

The tools are `get_recent_messages`, `search_messages`, `list_conversations`, `get_conversation_context`, and `get_collector_status`. For a remote server, configure the command to run over SSH. The client starts the MCP service with `run`; do not leave it running through `up`.
