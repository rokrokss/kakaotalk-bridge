# HTTP API와 stdio MCP

[README](../README.md) · [원격 OAuth MCP](dot-plugin.md)

## HTTP 조회

모든 `/v1/*` 경로는 read 토큰이 필요합니다. ingest·device 토큰으로 조회할 수 없습니다. 아래 예시는 Linux 서버에서 실행하며 TLS 인증서를 검증합니다.

```bash
# 토큰은 curl 인자가 아닌 stdin으로 전달합니다.
{ printf 'header = "Authorization: Bearer '; tr -d '\n' < secrets/read_token; printf '"\n'; } |
  curl --config - --cacert secrets/tls_cert.pem https://127.0.0.1:8443/v1/messages
```

| API | 용도 |
| --- | --- |
| `GET /v1/messages?after=0&limit=50` | 저장 순서로 메시지 조회 |
| `GET /v1/search?q=검색어&after=0&limit=50` | 본문 부분 문자열 검색 |
| `GET /v1/conversations?after=0&limit=50` | 관찰된 방 참조 조회. 같은 방이 반복될 수 있음 |
| `GET /v1/status` | 수집 상태·누락 구간·대기열 |
| `GET /health/live`, `/health/ready` | 프로세스·DB 상태 |

`next_cursor`를 다음 요청의 `after`로 보내고 `has_more`를 확인합니다. `coverage.cursor_epoch`가 바뀌면 DB 복원이 있었으므로 소비자의 커서를 초기화합니다. `pruned_through_cursor` 이하의 기록은 보관 기간에 따라 삭제되었습니다.

Iris 행의 `source`는 `iris_db`입니다. `database_ref`에는 DB 메시지·방·발신자 ID가 문자열로 들어갑니다. `conversation_ref`는 기기·등록 epoch·방 ID로 범위를 구분합니다. 이전 알림 기록은 `source=notification`, `conversation_ref=null`로 남아 있습니다.

`coverage.complete`는 항상 `false`입니다. redroid에 수신되지 않았거나 이미 삭제된 행을 복구하지 못하며, 전체 카카오톡 대화의 원장으로 사용할 수 없습니다.

## stdio MCP

수집 API가 실행 중인 상태에서 MCP 클라이언트에 다음을 설정합니다. 프로젝트 경로는 실제 절대 경로로 바꾸세요.

```json
{
  "mcpServers": {
    "kakaotalk": {
      "command": "docker",
      "args": ["compose", "--project-directory", "/absolute/path/kakaotalk-mcp-events", "--profile", "mcp", "run", "--rm", "--no-deps", "-T", "mcp"]
    }
  }
}
```

도구는 `get_recent_messages`, `search_messages`, `list_conversations`, `get_collector_status`입니다. 원격 서버에서는 SSH를 통해 명령을 실행하도록 설정합니다. MCP 서비스는 `up`으로 띄워 두지 않고 클라이언트가 `run`으로 시작합니다.
