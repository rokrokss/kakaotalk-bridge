# ChatGPT 연결

[README](../README.md) · [Events](events.md) · [보안](security.md)

`dot-plugin`은 수집 API에 저장된 메시지를 OAuth로 제공하는 원격 MCP 서버입니다. 카카오톡에 다시 로그인하지 않으며, 메시지 조회·검색·수집 상태 확인에 사용합니다.

## 연결하기

먼저 아래 배포 절차로 공개 HTTPS 주소를 준비합니다.

1. ChatGPT에서 맞춤형 MCP 서버를 추가합니다. 이름은 `KakaoTalk Dot`, URL은 `https://<서버주소>/mcp`, 인증은 OAuth로 설정합니다.
2. 서버의 승인 화면에서 `secrets/mcp_link_key`를 입력합니다. 카카오 비밀번호나 관리자 키가 아닙니다.
3. 연결 후 최근 메시지 조회나 검색을 요청합니다. 예: “KakaoTalk Dot에서 최근 메시지를 확인해줘.”

Mac에서는 키를 출력하지 않고 복사할 수 있습니다.

```bash
pbcopy < secrets/mcp_link_key
```

플러그인 연결은 이벤트 구독이나 자동 작업을 생성하지 않습니다. [Events](events.md)는 필요할 때 별도로 구독합니다.

## 도구

| 도구 | 용도 |
| --- | --- |
| `get_recent_messages` | 최근 수집 행 조회·커서 기반 페이지 탐색 |
| `search_messages` | 본문 부분 문자열 검색 |
| `list_conversations` | 관찰된 방 참조. 같은 방이 반복될 수 있음 |
| `get_collector_status` | 수집 상태와 현재 연결의 구독·전달 상태 |
| `get_profile` | 연결 식별용 불투명 프로필 ID |
| `get_pending_messages` | consumer별 미처리 메시지 조회 |
| `acknowledge_messages` | 조회한 페이지까지 처리 완료 기록 |

`get_recent_messages`의 기본 범위는 최근 N개 커서 위치입니다. 방 필터가 있으면 그 안의 일치 행만 반환하므로 N개보다 적을 수 있습니다. 메시지 전송·로그인·ADB 조작 도구는 없습니다.

## Linux에 배포

API와 Iris가 실행 중인 서버에서 `.env`의 `DOT_PUBLIC_URL`을 실제 HTTPS origin으로 설정합니다. 끝의 `/`와 `/mcp`는 제외합니다.

```bash
uv run python scripts/init-dot-secrets.py
sudo chown 10001:10001 secrets/mcp_link_key secrets/mcp_storage_key
sudo chmod 400 secrets/mcp_link_key secrets/mcp_storage_key
docker compose --profile dot build dot-plugin
docker compose --profile dot up -d --no-deps dot-plugin
```

공개 HTTPS 프록시의 목적지는 기본 `127.0.0.1:18787`입니다. **이 포트만 공개**하고 API gateway와 관리 화면은 사설 경로로 유지합니다. dot-plugin은 API read 토큰만 사용하며 Android 볼륨과 admin 토큰은 받지 않습니다.

## Mac의 Lima 배포

컨테이너는 Mac의 Docker Desktop이 아닌 Lima에서 실행합니다. 키는 VM에도 복사하고 VM 안에서 UID 10001이 읽도록 소유권을 맞춥니다. 이미지를 전달하는 방법은 [Mac 설치](local-redroid.md)를 따릅니다.

제공된 터널 구성은 다음 경로를 사용합니다.

```text
Tailscale Funnel HTTPS :443
  → Mac 127.0.0.1:18788
  → SSH 터널 → Lima 127.0.0.1:18787 → dot-plugin:8787
```

`scripts/dot-tunnel.sh`를 실행하거나 `deploy/dev.kakaocollector.dot-tunnel.plist.example`의 절대 경로를 맞춰 사용자 LaunchAgent로 설치합니다. 머신별 plist는 Git에서 제외되는 `deploy/*.local.plist`에 보관합니다. 이후 Tailscale Funnel을 Mac의 `127.0.0.1:18788`에 연결합니다. 기존 Funnel 설정이 있다면 목적지를 확인하고 충돌하지 않게 구성하세요.

Mac의 잠자기·종료, Lima 또는 Tailscale 정지는 공개 연결도 중단합니다. Funnel 주소가 공개되어도 `/mcp`에는 OAuth 인증이 필요합니다.

## 확인과 문제 해결

```bash
./scripts/lima-compose.sh --profile dot ps
./scripts/lima-compose.sh logs --tail 30 dot-plugin
tailscale funnel status
uv run python scripts/smoke-dot.py https://your-host.example
```

Linux에서는 `scripts/lima-compose.sh` 대신 `docker compose`를 사용합니다. smoke 검사는 임시 OAuth grant로 TLS·인증·도구 검색·실제 최신 행 조회를 확인한 뒤 철회합니다. 본문과 키는 출력하지 않으며 이벤트 구독도 만들지 않습니다.

| 오류 | 확인 |
| --- | --- |
| `invalid_origin` | `DOT_PUBLIC_URL`과 브라우저 주소의 scheme·host·port 일치 여부. 승인 HTML의 Referrer-Policy는 `same-origin`이어야 함 |
| `invalid_approval` | 10분이 지났거나 쿠키가 없는 승인 화면. ChatGPT에서 연결을 다시 시작 |
| `invalid_link_key` | `mcp_link_key`를 사용했는지 확인 |
| 연결 후 도구 오류 | 수집 API 상태와 read 토큰, 수집 승인 상태 |

승인 폼의 Origin·쿠키 검사와 PKCE 검증은 유지해야 합니다. 폼 정책 변경 후에는 실제 브라우저에서 승인과 ChatGPT 복귀까지 확인하세요.

## 프로토콜

MCP `2026-07-28`과 `kakao.read`, `kakao.events` 범위를 제공합니다. DCR과 ChatGPT CIMD를 지원하며, CIMD fetch 실패 시 임의 redirect를 허용하지 않습니다. CIMD는 `none`, DCR은 `none`·`client_secret_basic`·`client_secret_post`를 지원합니다. `private_key_jwt`는 지원하지 않습니다.

[OpenAI MCP Events](https://developers.openai.com/plugins/build/mcp-events) · [OAuth 인증](https://developers.openai.com/plugins/build/auth) · [ChatGPT 연결](https://developers.openai.com/plugins/build/app-quickstart#connect-your-mcp-server-in-chatgpt)
