# HTTP API와 stdio MCP

[README](../README.md) · [원격 OAuth MCP](dot-plugin.md)

<a id="http-queries"></a>
## HTTP 조회

이름이 포함된 메시지, 발신 시각 기준 최근 조회, 대화·발신자·시간 필터와 문맥 조회에는 [v2 조회 API](mcp-queries.md)를 사용하세요. 아래 v1 경로는 기존 소비자를 위해 수집 순서를 유지합니다.

모든 `/v1/*`, `/v2/*` 경로에는 읽기 토큰이 필요합니다. 수집·기기 토큰으로는 조회할 수 없습니다. 다음 예시는 Linux 서버에서 TLS 인증서를 검증하며 실행합니다.

```bash
# Pass the token through stdin, not as a curl argument.
{ printf 'header = "Authorization: Bearer '; tr -d '\n' < secrets/read_token; printf '"\n'; } |
  curl --config - --cacert secrets/tls_cert.pem https://127.0.0.1:8443/v1/messages
```

| API | 용도 |
| --- | --- |
| `GET /v1/messages?after=0&limit=50` | 저장 순서로 메시지 조회 |
| `GET /v1/search?q=keyword&after=0&limit=50` | 본문 부분 문자열 검색 |
| `GET /v1/conversations?after=0&limit=50` | 관측된 대화 참조 조회 (같은 대화가 중복될 수 있음) |
| `GET /v1/status` | 수집 상태, 누락 범위, 대기열 상태 |
| `GET /health/live`, `/health/ready` | 프로세스·DB 상태 |

다음 요청의 `after`에 `next_cursor`를 전달하고 `has_more`를 확인하세요. `coverage.cursor_epoch`가 바뀌면 DB가 복구된 것이므로 소비자는 커서를 초기화해야 합니다. `pruned_through_cursor` 이하의 기록은 보관 정책에 따라 삭제되었습니다.

Iris 메시지는 `source=iris_db`입니다. `database_ref`의 DB 메시지·대화·발신자 ID는 문자열입니다. `conversation_ref`는 기기·등록 세대·대화 ID로 범위를 구분합니다. 이전 알림 기록은 `source=notification`, `conversation_ref=null`을 유지합니다.

`coverage.complete`는 항상 `false`입니다. redroid에 도착하지 않았거나 이미 삭제된 메시지는 복구할 수 없으므로 카카오톡 전체 대화의 완전한 보관본이 아닙니다.

<a id="stdio-mcp"></a>
## stdio MCP

수집 API가 실행 중일 때 **AI 연결 → 연결 추가 또는 변경 → 내 컴퓨터의 AI 앱**을 여세요. **AI 앱에서 Bridge 실행 · 로컬 또는 SSH**에서 `./bridge mcp` 설정을 복사할 수 있습니다. 원격 서버는 SSH 호스트 별칭 또는 `user@host`를 입력하세요. 해당 계정에 비대화형 SSH 인증과 Docker 접근 권한이 필요합니다. CLI에서는 `./bridge setup-connection --method stdio`를 사용하세요.

클라이언트가 필요할 때 어댑터를 시작합니다. 공개 HTTPS, OAuth, Tailscale, OpenAI 터널은 필요하지 않습니다. 수집 상태를 요청하고 테스트 메시지를 찾아 연결을 확인하세요. 로컬 stdio 호출은 관리 화면의 **원격 AI 사용 기록**에 표시되지 않습니다.

수동 Docker 설치에서는 아래 설정을 직접 사용할 수도 있습니다. 경로를 Docker 호스트의 실제 절대 경로로 바꾸세요.

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

도구는 `get_recent_messages`, `search_messages`, `list_conversations`, `get_conversation_context`, `get_collector_status`입니다. 원격 서버에서는 SSH로 명령을 실행하도록 설정하세요. MCP 서비스는 클라이언트가 `run`으로 시작하며 `up`으로 계속 실행해 두지 않습니다.
